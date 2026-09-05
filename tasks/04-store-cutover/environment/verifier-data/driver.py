#!/usr/bin/env python3
"""Drive a submitted migration through its real entry points and write down
what happened.

This decides nothing. It runs the scenarios — advance the migration, take a
writer down mid-write, freeze one worker inside a ledger write while a second
one takes the migration off it, hold the authority flip open while production
keeps writing, put rows in the destination that the ledger never had — and
records observations. Whether those observations are correct is the model's
business, and the model does not share a line of code with the service.

Two scenarios run, on a box put back to the start in between:

  cutover   one timeline with everything happening at once: adversarial crash
            points, divergence in all three directions, a frozen worker whose
            in-flight write lands after the world moved on, and legacy writes
            arriving inside the cutover window.
  handover  the same migration carried by two workers taking turns, the lease
            changing hands legitimately at every step. A worker that answers a
            lost lease by giving up for good cannot finish this one.

Nothing here loads anything from /app. The service is exercised over HTTP, the
destination is read with the database's own client, and the legacy store is read
with sqlite3. What the store actually wrote comes from the store's own log.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

# The phase sequence, as the workspace declares it.
ORDER = [
    "INIT", "SHADOW_COPY", "DUAL_READ", "CATCH_UP", "RECONCILE",
    "CUTOVER", "LATE_REPLAY", "LEGACY_RETIRED", "COMPLETE",
]

# The slot the frozen worker is held in. The flip is held by a plan rule, which
# parks in the store's own unnamed slot.
PARKED_SLOT = "parked_worker"
FORCED_SLOT = "forced"
# The slot a worker is held in while it is part-way through recording a phase.
PUBLISH_SLOT = "parked_publish"


def at_least(phase, target):
    """Whether a phase is the target or past it. A migration driven by a worker
    that should have been refused can be further along than expected, and the
    driver has to keep making sense in that case rather than reporting nothing."""
    if phase not in ORDER or target not in ORDER:
        return False
    return ORDER.index(phase) >= ORDER.index(target)


class HarnessFailure(Exception):
    """Something the submission is not answerable for."""


def log(message):
    print(f"driver: {message}", flush=True)


# ----------------------------------------------------------------- the store


class Control:
    """The storage service's operator channel."""

    def __init__(self, path):
        self.path = path

    def call(self, request, timeout=180):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps(request) + "\n").encode())
            buffer = b""
            while not buffer.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    raise HarnessFailure("the storage service closed the control channel")
                buffer += chunk
        reply = json.loads(buffer.decode())
        if not reply.get("ok", False):
            raise HarnessFailure(f"control {request.get('op')}: {reply.get('error')}")
        return reply

    def reset(self):
        return self.call({"op": "reset"})

    def plan(self, rules):
        return self.call({"op": "plan", "rules": rules})

    def fired(self):
        return self.call({"op": "fired"})["fired"]

    def oplog(self, path):
        return self.call({"op": "oplog", "path": path})

    def arm_stall(self, slot, pid=0, target_op="", value_contains=None):
        return self.call({
            "op": "arm_stall", "id": slot, "pid": pid, "target_op": target_op,
            "value_contains": value_contains or [],
        })

    def stall_stats(self):
        return self.call({"op": "stall_stats"})

    def parked_in(self, slot):
        stats = self.stall_stats().get("slots") or {}
        return int((stats.get(slot) or {}).get("parked", 0))

    def release_stall(self, slot=""):
        return self.call({"op": "release_stall", "id": slot})


class Peer:
    """A writer of the destination that is not the submission: how a row the
    ledger never had, or a second copy of one it did, gets there."""

    def __init__(self, path):
        self.path = path

    def call(self, request, timeout=180):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(self.path)
            sock.sendall((json.dumps(request) + "\n").encode())
            buffer = b""
            while not buffer.endswith(b"\n"):
                chunk = sock.recv(65536)
                if not chunk:
                    raise HarnessFailure("the storage service closed the client channel")
                buffer += chunk
        reply = json.loads(buffer.decode())
        if not reply.get("ok", False):
            raise HarnessFailure(f"store {request.get('op')}: {reply.get('error')}")
        return reply

    def entry_add(self, entries):
        return self.call({"op": "entry_add", "entries": entries})


class Destination:
    """Reads of the destination database, taken with its own client."""

    def __init__(self, dsn):
        self.env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/root",
            "GEL_DSN": dsn,
            "GEL_CLIENT_TLS_SECURITY": "insecure",
        }

    def query(self, edgeql):
        done = subprocess.run(
            ["gel", "query", "-F", "json", edgeql],
            capture_output=True, text=True, env=self.env, timeout=300,
        )
        if done.returncode != 0:
            raise HarnessFailure(f"the destination would not answer: {done.stderr.strip()[:400]}")
        return json.loads(done.stdout or "[]")

    def export(self):
        return {
            "members": self.query(
                "select Member {member_id, tier, balance_cents, version, deleted}"
                " order by .member_id"
            ),
            "entries": self.query(
                "select LedgerEntry {member_id, seq, global_seq, delta_cents}"
                " order by .global_seq then .seq"
            ),
            "meta": self.query(
                "select MigrationMeta {phase, authority, fence, cursor, divergence}"
            ),
        }

    def entry_count(self):
        return self.query("select count(LedgerEntry)")[0]


class Legacy:
    """Reads and behind-the-back writes of the legacy ledger."""

    def __init__(self, path):
        self.path = path

    def with_db(self, body):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            return body(db)
        finally:
            db.close()

    def rows(self, sql, params=()):
        return self.with_db(lambda db: [dict(r) for r in db.execute(sql, params)])

    def scalar(self, sql, params=()):
        return self.with_db(lambda db: db.execute(sql, params).fetchone()[0])

    def export(self):
        return {
            "members": self.rows(
                "SELECT member_id, tier, balance_cents, version, deleted FROM members"
                " ORDER BY member_id"),
            "entries": self.rows(
                "SELECT member_id, seq, global_seq, delta_cents FROM ledger_entries"
                " ORDER BY global_seq"),
        }

    def max_global_seq(self):
        return int(self.scalar("SELECT COALESCE(MAX(global_seq), 0) FROM ledger_entries"))

    def entry_count(self):
        return int(self.scalar("SELECT COUNT(*) FROM ledger_entries"))

    def member(self, member_id):
        found = self.rows(
            "SELECT member_id, tier, balance_cents, version, deleted, updated_at"
            " FROM members WHERE member_id = ?", (member_id,))
        return found[0] if found else None

    def ledger(self, member_id):
        return self.rows(
            "SELECT member_id, seq, global_seq, delta_cents FROM ledger_entries"
            " WHERE member_id = ? ORDER BY seq", (member_id,))

    def busy_members(self, beyond):
        """Members whose history runs past a global sequence position."""
        return [
            row["member_id"] for row in self.rows(
                "SELECT member_id, COUNT(*) c FROM ledger_entries WHERE global_seq > ?"
                " GROUP BY member_id ORDER BY c DESC, member_id", (beyond,))
        ]

    def movement_at(self, position):
        """One movement from the early ledger, to be written into the
        destination a second time."""
        found = self.rows(
            "SELECT entry_id, member_id, seq, global_seq, delta_cents, reason, written_at"
            " FROM ledger_entries WHERE global_seq <= ? ORDER BY global_seq DESC LIMIT 1",
            (position,))
        if not found:
            raise HarnessFailure("the seeded ledger has no movement below the boundary")
        return found[0]

    def append(self, member_id, delta_cents, reason, written_at):
        """Write a ledger movement straight into legacy, the way a caller that
        got there before the authority moved would have."""
        entry_id = str(uuid.uuid4())

        def body(db):
            db.execute("BEGIN IMMEDIATE")
            seq = int(db.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM ledger_entries WHERE member_id = ?",
                (member_id,)).fetchone()[0])
            global_seq = int(db.execute(
                "SELECT COALESCE(MAX(global_seq), 0) + 1 FROM ledger_entries").fetchone()[0])
            db.execute(
                "INSERT INTO ledger_entries (entry_id, member_id, seq, global_seq,"
                " delta_cents, reason, written_at) VALUES (?,?,?,?,?,?,?)",
                (entry_id, member_id, seq, global_seq, delta_cents, reason, written_at))
            db.execute(
                "UPDATE members SET balance_cents = balance_cents + ?, version = version + 1,"
                " updated_at = ? WHERE member_id = ?", (delta_cents, written_at, member_id))
            db.commit()
            return seq, global_seq

        seq, global_seq = self.with_db(body)
        return {
            "entry_id": entry_id, "member_id": member_id, "seq": seq,
            "global_seq": global_seq, "delta_cents": delta_cents,
            "reason": reason, "written_at": written_at,
        }

    def poison(self, member_id, balance_cents):
        """Change the legacy row behind the service's back. After retirement
        nobody should be able to see this."""
        def body(db):
            db.execute(
                "UPDATE members SET balance_cents = ?, version = version + 1000"
                " WHERE member_id = ?", (balance_cents, member_id))
            db.commit()
        self.with_db(body)
        return self.member(member_id)

    # -- the member book is not frozen -----------------------------------
    #
    # Members join, leave and change tier while a migration runs, and none of
    # that touches the ledger. Everything below is an ordinary business event
    # that happens to land after the book was first copied.

    def quiet_members(self, count):
        """Members with the least ledger history, so a change to their book
        row cannot be confused with a change to the ledger."""
        rows = self.rows(
            "SELECT m.member_id FROM members m"
            " LEFT JOIN ledger_entries e ON e.member_id = m.member_id"
            " WHERE m.deleted = 0"
            " GROUP BY m.member_id ORDER BY COUNT(e.entry_id), m.member_id LIMIT ?",
            (count,))
        return [row["member_id"] for row in rows]

    def next_member_id(self):
        """A member id one past the highest this fixture holds. Derived rather
        than named, so each dataset stays inside its own id range."""
        highest = str(self.scalar("SELECT MAX(member_id) FROM members"))
        prefix, _, number = highest.rpartition("-")
        if not number.isdigit():
            raise HarnessFailure(f"member ids are not of the expected shape: {highest}")
        return f"{prefix}-{int(number) + 1:0{len(number)}d}"

    def create_member(self, tier, written_at):
        """A member who joins after the shadow copy and has not transacted."""
        member_id = self.next_member_id()

        def body(db):
            db.execute(
                "INSERT INTO members (member_id, tier, balance_cents, version,"
                " deleted, updated_at) VALUES (?,?,0,0,0,?)",
                (member_id, tier, written_at))
            db.commit()

        self.with_db(body)
        return self.member(member_id)

    def close_member(self, member_id, written_at):
        """A member who closes their account. Their history stays."""
        def body(db):
            db.execute(
                "UPDATE members SET deleted = 1, updated_at = ? WHERE member_id = ?",
                (written_at, member_id))
            db.commit()
        self.with_db(body)
        return self.member(member_id)

    def retier(self, member_id, tier, written_at):
        """A member who moves to another tier. No movement is involved."""
        def body(db):
            db.execute(
                "UPDATE members SET tier = ?, updated_at = ? WHERE member_id = ?",
                (tier, written_at, member_id))
            db.commit()
        self.with_db(body)
        return self.member(member_id)


# --------------------------------------------------------------- the service


class Instance:
    """One membershipd process, started the way the box starts one."""

    def __init__(self, name, port, holder, binary, run_dir, clock_file, boundary,
                 lease_ttl, store_socket):
        self.name = name
        self.port = port
        self.holder = holder
        self.binary = binary
        self.run_dir = run_dir
        self.clock_file = clock_file
        self.boundary = boundary
        self.lease_ttl = lease_ttl
        self.store_socket = store_socket
        self.process = None
        self.starts = 0

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"

    def env(self):
        return {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/agent",
            "TZ": "Etc/UTC",
            "LEDGER_CONFIG": "/app/config/migration.yaml",
            "LEDGER_LISTEN": f"127.0.0.1:{self.port}",
            "LEDGER_LEASE_HOLDER": self.holder,
            "LEDGER_SHADOW_BOUNDARY": str(self.boundary),
            # This deployment's numbers, handed over the way the box hands them
            # over. Neither is the number the workspace's own config file
            # happens to hold, and no deployment's are another's.
            "LEDGER_LEASE_TTL_SECONDS": str(self.lease_ttl),
            "LEDGER_CLOCK_FILE": self.clock_file,
            "LEDGER_STORE_SOCKET": self.store_socket,
            "LEDGER_LEGACY_PATH": "/app/data/legacy.db",
        }

    def start(self):
        # If something is already answering here it is not the submission being
        # graded, and every answer after this would be that stranger's.
        if self.responding(timeout=1):
            raise HarnessFailure(f"something was already listening on {self.base}")
        self.starts += 1
        stdout = open(os.path.join(self.run_dir, f"{self.name}.log"), "ab")
        # env -i keeps every verifier path out of the process, and it runs as
        # the account that owns /app, never as root.
        command = ["env", "-i"] + [f"{k}={v}" for k, v in self.env().items()] + [self.binary]
        self.process = subprocess.Popen(
            ["setpriv", "--reuid", "agent", "--regid", "agent", "--clear-groups", "--"] + command,
            stdout=stdout, stderr=subprocess.STDOUT, start_new_session=True,
        )
        deadline = time.time() + 90
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise HarnessFailure(f"{self.name} exited at start-up with {self.process.returncode}")
            if self.responding(timeout=2):
                return
            time.sleep(0.25)
        raise HarnessFailure(f"{self.name} never answered on {self.base}")

    def responding(self, timeout=2):
        try:
            code, _ = self.get("/healthz", timeout=timeout)
            return code == 200
        except Exception:
            return False

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def dying(self, grace=10):
        """True once the process is gone. A request can fail a moment before
        the exit is reaped, so give the reap a little room."""
        deadline = time.time() + grace
        while time.time() < deadline:
            if not self.alive():
                return True
            time.sleep(0.1)
        return False

    def stop(self):
        if not self.alive():
            return
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)

    def request(self, method, path, body=None, timeout=300):
        url = self.base + path
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read().decode()
                return response.status, safe_json(payload)
        except urllib.error.HTTPError as error:
            return error.code, safe_json(error.read().decode())

    def get(self, path, timeout=300):
        return self.request("GET", path, timeout=timeout)

    def post(self, path, body=None, timeout=300):
        return self.request("POST", path, body=body, timeout=timeout)

    def status(self):
        code, body = self.get("/admin/migration/status")
        if code != 200 or not isinstance(body, dict):
            raise HarnessFailure(f"{self.name} would not report its migration status ({code})")
        return body


def safe_json(text):
    try:
        return json.loads(text)
    except ValueError:
        return {"_raw": text[:400]}


# ------------------------------------------------------------ one scenario


class Scenario:
    """Shared machinery for driving one timeline on a box put back to the
    start. Subclasses supply `play`."""

    name = "scenario"

    def __init__(self, args, box):
        self.args = args
        self.box = box
        self.run_dir = args.run_dir
        self.control = box.control
        self.peer = box.peer
        self.destination = box.destination
        self.legacy = box.legacy
        self.truth = []
        self.observations = {
            "config": {"shadow_boundary": args.boundary,
                       "lease_ttl_seconds": args.lease_ttl},
            "checks": {},
            "restarts": [],
            "divergence_injected": 0,
            "extra_injected": 0,
            "duplicate_injected": 0,
            "window_injected": 0,
            "late_injected": 0,
            "book_changed": {},
            "advance_calls": 0,
            "notes": [],
            "seam": "unknown",
        }
        self.clock = args.clock_start
        self.started = []

    def first_member(self):
        """A member the fixture is known to have. Taken from the ledger rather
        than named here, so a fixture in its own member id range -- which is how
        the box's own data, the archived cutover and a graded run are kept from
        sharing an identifier -- drives exactly the same way."""
        return min(row["member_id"] for row in self.truth)

    def lease_free(self):
        """Move the deployment clock just past the lease lifetime this
        deployment configured, so a lease that has not been renewed is free and
        a worker that read `lease_ttl_seconds` can tell that it is. A worker
        that assumed a longer lifetime than the deployment set still sees a
        lease it thinks is held, and does not take its turn."""
        self.set_clock(self.clock + self.args.lease_ttl + 2)

    # -- bookkeeping ----------------------------------------------------

    @property
    def truth_path(self):
        return os.path.join(self.run_dir, f"truth-{self.name}.jsonl")

    @property
    def oplog_path(self):
        return os.path.join(self.run_dir, f"oplog-{self.name}.jsonl")

    def note(self, message):
        log(f"[{self.name}] {message}")
        self.observations["notes"].append(message)

    def record_truth(self, entry, origin):
        row = dict(entry)
        row["origin"] = origin
        self.truth.append(row)

    def write_truth(self):
        with open(self.truth_path, "w", encoding="utf-8") as handle:
            for row in sorted(self.truth, key=lambda r: r["global_seq"]):
                handle.write(json.dumps(row, sort_keys=True) + "\n")

    def set_clock(self, value):
        self.clock = value
        with open(self.args.clock_file, "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")
        os.chmod(self.args.clock_file, 0o644)

    def oplog(self):
        rows = []
        if not os.path.exists(self.oplog_path):
            return rows
        with open(self.oplog_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
        return rows

    def oplog_mark(self):
        rows = self.oplog()
        return rows[-1]["n"] if rows else 0

    def snapshot(self, extra=None):
        payload = {"destination": self.destination.export(),
                   "truth_upto": self.legacy.max_global_seq()}
        if extra:
            payload.update(extra)
        return payload

    def stamp(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock))

    def instance(self, name, port, holder):
        made = Instance(
            name=f"{self.name}-{name}", port=port, holder=holder, binary=self.args.binary,
            run_dir=self.run_dir, clock_file=self.args.clock_file,
            boundary=self.args.boundary, lease_ttl=self.args.lease_ttl,
            store_socket=self.args.store_socket,
        )
        self.started.append(made)
        return made

    # -- driving --------------------------------------------------------

    def advance_until(self, instance, target, budget_seconds=420, attempts=80):
        """Call advance until the migration reaches a phase, restarting the
        process whenever a write takes it down."""
        deadline = time.time() + budget_seconds
        last = None
        for _ in range(attempts):
            if time.time() > deadline:
                break
            if not instance.alive():
                self.note(f"{instance.name} is gone; starting it again")
                self.observations["restarts"].append({"instance": instance.name, "at": target})
                instance.start()
            # Read the phase before pushing, so a submission that reaches the
            # target sooner than expected is never driven past it.
            last = instance.status()
            if at_least(last["phase"], target):
                return last
            try:
                code, _ = instance.post("/admin/migration/advance")
                self.observations["advance_calls"] += 1
            except Exception as error:
                if instance.dying():
                    self.note(f"{instance.name} died during an advance ({type(error).__name__})")
                    continue
                raise
            if code == 501:
                self.observations["seam"] = "absent"
                return None
            self.observations["seam"] = "present"
        if instance.alive():
            last = instance.status()
        return last

    def advance_one_phase(self, worker, was, budget_seconds=300, attempts=20):
        deadline = time.time() + budget_seconds
        for _ in range(attempts):
            if time.time() > deadline:
                return None
            if not worker.alive():
                self.observations["restarts"].append({"instance": worker.name, "at": was})
                worker.start()
            current = worker.status()
            if current["phase"] != was:
                return current
            try:
                worker.post("/admin/migration/advance")
                self.observations["advance_calls"] += 1
            except Exception:
                if not worker.dying():
                    raise
        return None

    def wait_parked(self, slot, thread, seconds=90):
        """Wait for a write to be held in a slot. A submission that never makes
        that write is recorded as not having been parked rather than hanging
        the run."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            if self.control.parked_in(slot) >= 1:
                return True
            if thread is not None and not thread.is_alive():
                return False
            time.sleep(0.2)
        return False

    # -- the shape shared by both timelines ------------------------------

    def catch_up_faults(self):
        """Three ways a write goes wrong, placed by what the write carries
        rather than by how many writes a submission happens to make, plus one
        that takes the writer down while it is folding member rows. Between
        them, a process is taken down on both sides of the pair of writes a
        movement needs, whichever order a submission makes them in."""
        boundary = self.args.boundary
        tail = self.legacy.max_global_seq()
        span = max(6, tail - boundary)
        first = boundary + span // 6
        second = boundary + span // 3
        third = boundary + span // 2
        rules = [
            {"id": "withheld_committed", "op": "entry_add",
             "action": "unknown_after_commit", "global_seq_min": first, "limit": 1},
            {"id": "withheld_lost", "op": "entry_add",
             "action": "unknown_after_rollback", "global_seq_min": second, "limit": 1},
            {"id": "recycled", "op": "entry_add",
             "action": "kill_client_after_commit", "global_seq_min": third, "limit": 1},
        ]
        self.note(f"faults armed at global_seq {first}, {second}, {third} of {tail}")
        return rules

    def fold_kill(self):
        """A writer taken down the instant a member row became durable. A
        submission that writes the fold before the movements it counts is left
        with a member claiming rows the store has not got; one that writes them
        the other way round has already been taken down between the two by the
        rule above. Either way the store, not the submission's own note of
        where it had reached, is the only thing that can put it right."""
        return {"id": "folded", "op": "member_put",
                "action": "kill_client_after_commit", "limit": 1}

    def finish(self):
        for instance in self.started:
            try:
                instance.stop()
            except Exception:
                pass
        self.observations["oplog"] = self.oplog()
        self.observations.setdefault("faults_fired", {})
        self.write_truth()

    def run(self):
        for row in load_jsonl(self.args.seed_truth):
            self.record_truth(row, "seed")
        self.note(f"the seeded ledger has {len(self.truth)} movement(s)")
        self.set_clock(self.args.clock_start)
        try:
            self.play()
        finally:
            self.finish()
        return self.observations


# --------------------------------------------------- scenario: the cutover


class CutoverScenario(Scenario):
    """One timeline with everything at once."""

    name = "cutover"

    def play(self):
        worker_a = self.instance("a", self.args.port_a, "membershipd-a")
        worker_a.start()

        code, body = worker_a.get(f"/v1/members/{self.first_member()}")
        if code != 200 or "balance_cents" not in (body or {}):
            raise HarnessFailure(f"the ledger would not serve a member ({code})")
        self.note("the service is up and serving the ledger")

        code, _ = worker_a.post("/admin/migration/advance")
        if code == 501:
            self.observations["seam"] = "absent"
            self.note("advance is not implemented; nothing to drive")
            return
        self.observations["seam"] = "present"

        self.stage_shadow_copy(worker_a)
        self.stage_dual_read(worker_a)
        self.stage_catch_up(worker_a)
        worker_b = self.stage_cutover(worker_a)
        self.stage_late_replay(worker_b)
        self.stage_retire(worker_b)

    def stage_shadow_copy(self, worker):
        status = self.advance_until(worker, "SHADOW_COPY")
        if not status or not at_least(status["phase"], "SHADOW_COPY"):
            self.note("the migration never reached the end of the shadow copy")
            return
        self.observations["checks"]["after_shadow_copy"] = self.snapshot(
            {"status": status, "legacy": self.legacy.export()}
        )
        self.note("shadow copy recorded")

    def stage_dual_read(self, worker):
        status = self.advance_until(worker, "DUAL_READ")
        if not status or not at_least(status["phase"], "DUAL_READ"):
            self.note("the migration never reached dual-read")
            return
        candidates = self.legacy.busy_members(self.args.boundary)
        if not candidates:
            raise HarnessFailure("no member has history past the phase-one boundary")
        member_id = candidates[0]

        code, adjust = worker.post(
            f"/v1/members/{member_id}/adjust", {"delta_cents": 2750, "reason": "dual-read probe"}
        )
        probe = {
            "member_id": member_id,
            "adjust": {"http_status": code, "body": adjust},
        }
        if code == 200 and isinstance(adjust, dict) and "entry" in adjust:
            self.record_truth(adjust["entry"], "api")
        read_code, read_body = worker.get(f"/v1/members/{member_id}")
        ledger_code, ledger_body = worker.get(f"/v1/members/{member_id}/ledger")
        probe["member_read"] = {"http_status": read_code, "body": read_body}
        probe["ledger_read"] = {"http_status": ledger_code, "body": ledger_body}
        probe["legacy_member"] = self.legacy.member(member_id)
        probe["truth_upto"] = self.legacy.max_global_seq()
        probe["status"] = status
        self.observations["checks"]["dual_read_probe"] = probe
        self.note(f"dual-read probed on {member_id}")

    def stage_catch_up(self, worker):
        self.control.plan(self.catch_up_faults() + [self.fold_kill()])
        status = self.advance_until(worker, "CATCH_UP")
        # Read the tally before clearing the plan, because installing one resets it.
        self.observations["faults_fired"] = self.control.fired()
        self.control.plan([])
        if not status or not at_least(status["phase"], "CATCH_UP"):
            self.note("the migration never finished catching up")
            return
        self.observations["checks"]["after_catch_up"] = self.snapshot({"status": status})
        self.note(f"catch-up recorded; faults fired {self.observations['faults_fired']}")

    # -- divergence in all three directions ------------------------------

    def inject_divergence(self):
        """Production keeps writing, and the destination has picked up two rows
        that are nothing to do with the ledger. All three of these land after
        reconciliation last reported itself clean."""
        busy = self.legacy.busy_members(0)
        for index in range(3):
            entry = self.legacy.append(
                busy[index], 1300 + index, "post-reconcile", self.stamp())
            self.record_truth(entry, "divergence")
            self.observations["divergence_injected"] += 1

        # A row the ledger has never had, at a sequence number no member will
        # ever reach, so nothing in the log can be confused with it.
        ghost_member = busy[4 % len(busy)]
        ghost = {
            "entry_id": str(uuid.uuid4()), "member_id": ghost_member,
            "seq": 900_001, "global_seq": 900_001, "delta_cents": -7654,
            "reason": "not from the ledger", "written_at": self.stamp(),
        }
        self.peer.entry_add([ghost])
        self.observations["extra_injected"] = 1
        self.observations["extra_key"] = [ghost["member_id"], ghost["seq"]]

        # And a movement the destination already holds, written a second time.
        twice = self.legacy.movement_at(self.args.boundary)
        self.peer.entry_add([{
            "entry_id": str(uuid.uuid4()), "member_id": twice["member_id"],
            "seq": twice["seq"], "global_seq": twice["global_seq"],
            "delta_cents": twice["delta_cents"], "reason": twice["reason"],
            "written_at": twice["written_at"],
        }])
        self.observations["duplicate_injected"] = 1
        self.observations["duplicate_key"] = [twice["member_id"], twice["seq"]]
        self.note(
            "three movements landed in legacy, one row the ledger never had and one "
            "second copy of a movement landed in the destination"
        )

    def churn_the_book(self):
        """The membership itself moves while the migration runs.

        None of this is a ledger movement: a member joins and has not
        transacted yet, another closes their account, a third changes tier.
        All three land after the book was first copied and none of them
        appears anywhere in the append log, so a migration that treats the
        member book as something copied once carries a book that is out of
        date into the destination.
        """
        quiet = self.legacy.quiet_members(4)
        if len(quiet) < 3:
            raise HarnessFailure("the fixture has too few members to change the book")
        joined = self.legacy.create_member("bronze", self.stamp())
        closed = self.legacy.close_member(quiet[0], self.stamp())
        was = self.legacy.member(quiet[1])["tier"]
        moved_to = "platinum" if was != "platinum" else "gold"
        retiered = self.legacy.retier(quiet[1], moved_to, self.stamp())
        self.observations["book_changed"] = {
            "joined": joined["member_id"],
            "closed": closed["member_id"],
            "retiered": {"member_id": retiered["member_id"], "from": was, "to": moved_to},
        }
        self.note(
            f"the member book moved on: {joined['member_id']} joined, "
            f"{closed['member_id']} closed, {retiered['member_id']} went "
            f"{was} to {moved_to}"
        )

    def stage_cutover(self, worker_a):
        status = self.advance_until(worker_a, "RECONCILE")
        if not status or not at_least(status["phase"], "RECONCILE"):
            self.note("the migration never reached reconciliation")
            return worker_a

        self.inject_divergence()
        self.churn_the_book()

        # Freeze worker A inside a ledger write. It is not sleeping and not
        # racing: it is stopped with a lease it believes in and a batch it
        # believes is missing, and it will be let go long after both stopped
        # being true.
        stale = {"pid": worker_a.process.pid, "attempted": False,
                 "oplog_mark": self.oplog_mark()}
        self.control.arm_stall(PARKED_SLOT, pid=worker_a.process.pid, target_op="entry_add")
        held = {}

        def freeze():
            try:
                held["response"] = worker_a.post("/admin/migration/advance", timeout=900)
            except Exception as error:
                held["error"] = f"{type(error).__name__}: {error}"

        frozen = threading.Thread(target=freeze, daemon=True)
        frozen.start()
        stale["parked"] = self.wait_parked(PARKED_SLOT, frozen)
        self.note(f"worker a frozen inside a ledger write: {stale['parked']}")

        # Its lease runs out on the deployment clock while it is frozen, and a
        # second worker takes over. The clock moves past the lifetime this
        # deployment configured and no further, so a worker that assumed a
        # longer one never gets its turn. It does not move again until worker a
        # has had its say, so worker b's lease stays live throughout: nothing
        # worker a does afterwards is a legitimate handover.
        self.lease_free()
        worker_b = self.instance("b", self.args.port_b, "membershipd-b")
        worker_b.start()
        self.note("worker b started and the deployment clock moved past a's lease")

        self.flip_under_load(worker_b)

        stale["status_before"] = worker_b.status()
        stale["fence"] = stale["status_before"]["fence"]
        # Where in the store's log the second worker first acted. Past that
        # point the first worker has no authority left.
        stale["takeover_mark"] = next(
            (row["n"] for row in self.oplog() if row.get("pid") == worker_b.process.pid),
            stale["oplog_mark"],
        )

        # Now let worker a go. The write it is holding lands — that one is in
        # flight and nothing can call it back — and everything it does next is
        # a write made on a lease it lost a long time ago.
        stale["release_mark"] = self.oplog_mark()
        self.control.release_stall(PARKED_SLOT)
        frozen.join(timeout=900)
        stale["attempted"] = bool(held)
        stale["response"] = describe(held)

        # And again, from the top, with everything it believes now stale. Two
        # attempts rather than many: a worker that is wrongly allowed to carry
        # on will advance a phase per attempt, and driving it to the end of the
        # migration would leave nothing further to observe.
        stale["retries"] = []
        for _ in range(2):
            if not worker_a.alive():
                break
            try:
                code, body = worker_a.post("/admin/migration/advance", timeout=300)
                stale["retries"].append({"http_status": code, "body": trim(body)})
                stale["attempted"] = True
            except Exception as error:
                stale["retries"].append({"error": f"{type(error).__name__}: {error}"})
        stale["status_after"] = worker_b.status()
        self.observations["stale"] = stale
        self.note(f"frozen worker's write landed: {stale['response']}")
        worker_a.stop()
        return worker_b

    def flip_under_load(self, worker_b):
        """Drive the takeover worker to the cutover, holding it inside the
        write that names the destination as the authority. What the stores hold
        at that instant is the cutover gate; what reaches legacy while the
        write is still open is a late write like any other, and the fact that
        the flip is not instantaneous is the whole point of the window."""
        self.control.plan([{
            "id": "flip", "op": "meta_put", "action": "stall",
            "pid": worker_b.process.pid, "value_contains": ["destination"], "limit": 1,
        }])

        outcome = {}

        def push():
            try:
                outcome["status"] = self.advance_until(worker_b, "CUTOVER", budget_seconds=900)
            except Exception as error:
                outcome["error"] = f"{type(error).__name__}: {error}"

        pushing = threading.Thread(target=push, daemon=True)
        pushing.start()

        if self.wait_parked(FORCED_SLOT, pushing, seconds=600):
            # The gate, judged at the instant the authority moves and not at
            # whatever the previous phase happened to find.
            self.observations["checks"]["at_cutover"] = self.snapshot(
                {"status": None, "parked": True})
            self.note("the authority flip is open; the stores were compared at that instant")
            for index in range(4):
                members = self.legacy.busy_members(0)
                entry = self.legacy.append(
                    members[(index * 3) % len(members)], 700 + index * 9,
                    "inside the window", self.stamp())
                self.record_truth(entry, "window")
                self.observations["window_injected"] += 1
            self.note("four movements reached legacy while the authority was moving")
            self.control.release_stall(FORCED_SLOT)
        else:
            self.note("the authority flip was never held open")

        # Only this slot: the frozen worker is being held in another one and it
        # is not time to let it go yet.
        pushing.join(timeout=900)
        self.control.release_stall(FORCED_SLOT)
        self.control.plan([])

        status = outcome.get("status")
        if status and status.get("authority") == "destination":
            check = self.observations["checks"].get("at_cutover")
            if check is not None:
                check["status"] = status
            else:
                self.observations["checks"]["at_cutover"] = self.snapshot({"status": status})
            self.note("the authority moved")
        else:
            self.note("worker b never moved the authority")

    def stage_late_replay(self, worker):
        status = worker.status()
        if status["authority"] != "destination":
            self.note("skipping late replay: the authority never moved")
            return
        self.observations["checks"]["before_late_replay"] = self.snapshot()
        members = self.legacy.busy_members(0)
        for index in range(8):
            entry = self.legacy.append(
                members[(index * 5) % len(members)], 900 + index * 11, "in flight", self.stamp()
            )
            self.record_truth(entry, "late")
            self.observations["late_injected"] += 1
        self.note("eight more movements reached legacy after the authority moved")

        self.probe_the_open_ledger(worker, members[0])

        # Whatever phase runs next, it must not report itself finished while
        # legacy holds movements the destination has not got. Which phase that
        # is depends on where the migration had got to, so this waits for the
        # next boundary rather than for a particular name.
        moved = self.advance_one_phase(worker, status["phase"])
        if not moved:
            self.note("the migration would not move past the late writes")
            return
        self.observations["checks"]["after_late_replay"] = self.snapshot({"status": moved})
        self.note(f"the first boundary after the late writes was {moved['phase']}")

    def probe_the_open_ledger(self, worker, member_id):
        """Read and write the ledger after the authority has moved and before
        the drain that follows it has run.

        The authority names the destination, and the destination has not got
        the movements that reached legacy while the write naming it was still
        open. So this is the one stretch of the migration where the store the
        record points at cannot answer for the ledger, and where the ledger is
        still taking movements because legacy has not been retired.
        """
        status = worker.status()
        read_code, read_body = worker.get(f"/v1/members/{member_id}")
        ledger_code, ledger_body = worker.get(f"/v1/members/{member_id}/ledger")
        probe = {
            "member_id": member_id,
            "status": status,
            "member_read": {"http_status": read_code, "body": read_body},
            "ledger_read": {"http_status": ledger_code, "body": ledger_body},
            "truth_upto": self.legacy.max_global_seq(),
        }

        # And a movement arriving through the front door in the same stretch.
        # Legacy is not retired, so there is no maintenance window to hide in.
        write_member = self.legacy.busy_members(0)[3]
        code, adjust = worker.post(
            f"/v1/members/{write_member}/adjust",
            {"delta_cents": -1875, "reason": "after the authority moved"},
        )
        probe["write"] = {
            "member_id": write_member,
            "http_status": code,
            "body": trim(adjust),
        }
        if code == 200 and isinstance(adjust, dict) and "entry" in adjust:
            self.record_truth(adjust["entry"], "api")
        self.observations["checks"]["open_ledger_probe"] = probe
        self.note(
            f"the ledger was read and written after the authority moved: "
            f"read {read_code}, write {code}"
        )

    def stage_retire(self, worker):
        status = self.advance_until(worker, "LEGACY_RETIRED")
        if not status or not at_least(status["phase"], "LEGACY_RETIRED"):
            self.note("the migration never retired legacy")
            return
        status = self.advance_until(worker, "COMPLETE") or status
        self.observations["checks"]["final"] = self.snapshot(
            {"status": status, "legacy_book": self.legacy.export()}
        )
        self.note(f"the migration finished in phase {status['phase']}")

        # With legacy retired, a change made straight to the legacy file must
        # not be visible, and the ledger's write path must be closed.
        member_id = self.legacy.busy_members(0)[1]
        poisoned = self.legacy.poison(member_id, -987_654_321)
        legacy_before = self.legacy.entry_count()
        destination_before = self.destination.entry_count()
        read_code, read_body = worker.get(f"/v1/members/{member_id}")
        adjust_code, adjust_body = worker.post(
            f"/v1/members/{member_id}/adjust", {"delta_cents": 4242, "reason": "after retirement"}
        )
        check = {
            "poison": {"member_id": member_id, "balance_cents": poisoned["balance_cents"],
                       "version": poisoned["version"]},
            "member_read": {"http_status": read_code, "body": read_body},
            "adjust": {"http_status": adjust_code, "body": trim(adjust_body)},
            "legacy_entry_count_before": legacy_before,
            "legacy_entry_count_after": self.legacy.entry_count(),
            "destination_entry_count_before": destination_before,
            "destination_entry_count_after": self.destination.entry_count(),
        }
        self.observations["checks"]["after_retire"] = check
        self.note("retirement probed with a poisoned legacy row and a refused write")


# -------------------------------------------------- scenario: the handover


class HandoverScenario(Scenario):
    """The same migration, carried by two workers taking turns.

    Every turn the deployment clock moves past the lease lifetime, so the lease
    is genuinely free and the worker whose turn it is genuinely takes it. This
    is the ordinary case — deployments roll, workers are replaced, nobody
    finishes what they started — and it is the case a submission that answers a
    lost lease by refusing to act ever again cannot get through.
    """

    name = "handover"

    def play(self):
        worker_a = self.instance("a", self.args.port_a, "membershipd-a")
        worker_b = self.instance("b", self.args.port_b, "membershipd-b")
        worker_a.start()
        worker_b.start()

        # One fault, so a restart happens in the middle of a turn as well as
        # between them.
        self.control.plan([self.catch_up_faults()[2]])

        workers = [worker_a, worker_b]
        turns = []
        seen = {}
        cleared = False
        published = False
        for turn in range(40):
            worker = workers[turn % 2]
            # The lease lifetime is the deployment's, not ours. The clock moves
            # just past it, so the lease is genuinely free on every turn and
            # reading `lease_ttl_seconds` is what tells a worker so.
            self.lease_free()
            if not worker.alive():
                self.observations["restarts"].append(
                    {"instance": worker.name, "at": "handover"})
                worker.start()
            before = worker.status()["phase"]
            try:
                code, body = worker.post("/admin/migration/advance", timeout=600)
                self.observations["advance_calls"] += 1
            except Exception as error:
                if not worker.dying():
                    raise
                turns.append({"worker": worker.name, "from": before, "died": True})
                continue
            if code == 501:
                self.observations["seam"] = "absent"
                self.note("advance is not implemented; nothing to drive")
                return
            self.observations["seam"] = "present"
            after = worker.status()["phase"] if worker.alive() else before
            turns.append({
                "worker": worker.name, "from": before, "to": after,
                "http_status": code,
                "error": (body or {}).get("error") if isinstance(body, dict) else None,
            })
            seen.setdefault(after, worker.name)

            if not cleared and at_least(after, "CATCH_UP"):
                self.observations["faults_fired"] = self.control.fired()
                self.control.plan([])
                cleared = True

            # Once the faults are out of the way and there is still migration
            # left to run, hold one worker inside recording a phase while the
            # other takes over.
            if cleared and not published and at_least(after, "CATCH_UP") \
                    and not at_least(after, "CUTOVER"):
                published = True
                self.stale_publish(workers[(turn + 1) % 2], worker)

            # Production keeps writing, and it does not stop because the
            # authority moved.
            if after == "CUTOVER" and not self.observations["late_injected"]:
                self.observations["checks"]["before_late_replay"] = self.snapshot()
                members = self.legacy.busy_members(0)
                for index in range(5):
                    entry = self.legacy.append(
                        members[(index * 7) % len(members)], 500 + index * 13,
                        "in flight", self.stamp())
                    self.record_truth(entry, "late")
                    self.observations["late_injected"] += 1
                self.note("five movements reached legacy after the authority moved")

            if after == "COMPLETE":
                break

        if not cleared:
            self.observations["faults_fired"] = self.control.fired()
            self.control.plan([])
        self.observations["turns"] = turns
        self.observations["phase_owner"] = seen
        self.note(f"the migration took {len(turns)} turn(s) across two workers")

        final = worker_b if worker_b.alive() else worker_a
        if not final.alive():
            final.start()
        status = final.status()
        self.observations["checks"]["final"] = self.snapshot(
            {"status": status, "legacy_book": self.legacy.export()}
        )
        self.observations["checks"]["after_late_replay"] = self.observations["checks"]["final"]
        self.note(f"the migration finished in phase {status['phase']}")

        if at_least(status["phase"], "LEGACY_RETIRED"):
            member_id = self.legacy.busy_members(0)[2]
            poisoned = self.legacy.poison(member_id, -123_456_789)
            legacy_before = self.legacy.entry_count()
            destination_before = self.destination.entry_count()
            read_code, read_body = final.get(f"/v1/members/{member_id}")
            adjust_code, adjust_body = final.post(
                f"/v1/members/{member_id}/adjust",
                {"delta_cents": 31, "reason": "after retirement"})
            self.observations["checks"]["after_retire"] = {
                "poison": {"member_id": member_id,
                           "balance_cents": poisoned["balance_cents"],
                           "version": poisoned["version"]},
                "member_read": {"http_status": read_code, "body": read_body},
                "adjust": {"http_status": adjust_code, "body": trim(adjust_body)},
                "legacy_entry_count_before": legacy_before,
                "legacy_entry_count_after": self.legacy.entry_count(),
                "destination_entry_count_before": destination_before,
                "destination_entry_count_after": self.destination.entry_count(),
            }
            self.note("retirement probed after the handover run")

    def stale_publish(self, victim, taker):
        """Hold a worker part-way through recording a phase, hand the migration
        to the other worker, and then let the held write go.

        This is the one seam where a worker that has been passed over still
        reaches the record. Everywhere else it is stopped before it gets there:
        its lease is plainly gone, or a data write is refused first. Here the
        write is already at the store, computed from a record that was current
        when the worker read it and is not current any more, and no check the
        worker makes afterwards can call it back.

        So the write itself has to be the thing that refuses. A phase record
        published conditionally on the record it was derived from lands as a
        failed swap and changes nothing; the same record published
        unconditionally lands on top of the worker that took over and puts the
        fence back where it was. Which of those is wanted is not stated
        anywhere: `store.Client.MetaPut` takes an expected record and returns
        whether the write took, and the archived cutover's record history is an
        unbroken chain in which every version was published from the one before
        it, across a change of holder included.
        """
        probe = {"victim": victim.name, "taker": taker.name}
        self.lease_free()
        if not victim.alive():
            victim.start()
        phase = victim.status()["phase"]
        if phase not in ORDER or ORDER.index(phase) + 1 >= len(ORDER):
            return
        target = ORDER[ORDER.index(phase) + 1]
        probe["from"] = phase
        probe["publishing"] = target

        # Matched on the phase being recorded, so this parks in the write that
        # records it and not in a checkpoint written on the way there.
        self.control.arm_stall(
            PUBLISH_SLOT, pid=victim.process.pid, target_op="meta_put",
            value_contains=[target])
        held = {}

        def publish():
            try:
                held["response"] = victim.post("/admin/migration/advance", timeout=900)
            except Exception as error:
                held["error"] = f"{type(error).__name__}: {error}"

        parking = threading.Thread(target=publish, daemon=True)
        parking.start()
        probe["parked"] = self.wait_parked(PUBLISH_SLOT, parking, seconds=300)
        if not probe["parked"]:
            self.control.release_stall(PUBLISH_SLOT)
            parking.join(timeout=300)
            self.note("no worker could be held inside recording a phase")
            self.observations["stale_publish"] = probe
            return
        self.note(f"{victim.name} is held inside recording {target}")

        # Its lease runs out, and the other worker legitimately takes the
        # migration over and moves it on under a higher fence. Again the clock
        # moves past the configured lifetime and no further.
        self.lease_free()
        if not taker.alive():
            taker.start()
        try:
            code, body = taker.post("/admin/migration/advance", timeout=600)
            probe["taker_advance"] = {"http_status": code, "body": trim(body)}
            self.observations["advance_calls"] += 1
        except Exception as error:
            probe["taker_advance"] = {"error": f"{type(error).__name__}: {error}"}
        probe["record_after_takeover"] = taker.status() if taker.alive() else None
        probe["release_mark"] = self.oplog_mark()

        self.control.release_stall(PUBLISH_SLOT)
        parking.join(timeout=900)
        probe["response"] = describe(held)
        probe["record_after_release"] = taker.status() if taker.alive() else None
        self.observations["stale_publish"] = probe
        self.note(f"the held record write landed: {probe['response']}")


# ------------------------------------------------------------------ the box


class Box:
    """The stores, and putting them back to the start between scenarios."""

    def __init__(self, args):
        self.args = args
        self.control = Control(args.control_socket)
        self.peer = Peer(args.store_socket)
        self.destination = Destination(args.dsn)
        self.legacy = Legacy(args.legacy)

    def reset(self, oplog_path):
        # Anchored, because this driver's own command line carries the binary's
        # path in --binary and an unanchored -f match kills the driver itself.
        # A worker is spawned with the path as argv[0], so it matches at the
        # start and nothing else does.
        pattern = "^" + re.escape(self.args.binary)
        subprocess.run(["pkill", "-f", pattern], check=False)
        # Waited out rather than slept off: a fixed pause is either longer than
        # the machine needs or shorter than a loaded one does, and what has to
        # be true before the stores are put back is that nothing from the last
        # scenario is still running. pgrep exits 1 when nothing matches.
        deadline = time.time() + 30
        while time.time() < deadline:
            if subprocess.run(["pgrep", "-f", pattern],
                              stdout=subprocess.DEVNULL).returncode != 0:
                break
            time.sleep(0.1)
        else:
            subprocess.run(["pkill", "-9", "-f", pattern], check=False)
        self.control.reset()
        self.control.plan([])
        self.control.oplog(oplog_path)
        for suffix in ("-wal", "-shm"):
            path = self.args.legacy + suffix
            if os.path.exists(path):
                os.remove(path)
        shutil.copyfile(self.args.legacy_pristine, self.args.legacy)
        shutil.chown(self.args.legacy, "agent", "agent")
        os.chmod(self.args.legacy, 0o644)


def describe(result):
    if "error" in result:
        return {"error": result["error"]}
    code, body = result.get("response", (0, None))
    return {"http_status": code, "body": trim(body)}


def trim(body):
    if isinstance(body, dict):
        return {k: (v if not isinstance(v, str) or len(v) < 300 else v[:300]) for k, v in body.items()}
    return body


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


SCENARIOS = [CutoverScenario, HandoverScenario]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed-truth", required=True)
    parser.add_argument("--legacy", default="/app/data/legacy.db")
    parser.add_argument("--legacy-pristine", required=True)
    parser.add_argument("--control-socket", default="/run/ledger/store-control.sock")
    parser.add_argument("--store-socket", default="/run/ledger/store.sock")
    parser.add_argument("--clock-file", default="/run/ledger/clock")
    parser.add_argument("--dsn", default="gel://admin:dev@localhost:5656/main")
    parser.add_argument("--boundary", type=int, required=True)
    parser.add_argument("--clock-start", type=int, default=1_745_000_000)
    parser.add_argument("--lease-ttl", type=int, default=8,
                        help="the deployment's lease_ttl_seconds, which is what "
                             "decides when a lease has gone free")
    parser.add_argument("--port-a", type=int, default=8080)
    parser.add_argument("--port-b", type=int, default=8081)
    parser.add_argument("--only", default="")
    args = parser.parse_args()

    os.makedirs(args.run_dir, exist_ok=True)
    box = Box(args)
    out = {"scenarios": {}, "seam": "unknown"}
    status = 0
    wanted = [name for name in args.only.split(",") if name]

    for factory in SCENARIOS:
        if wanted and factory.name not in wanted:
            continue
        scenario = factory(args, box)
        try:
            box.reset(scenario.oplog_path)
            out["scenarios"][factory.name] = scenario.run()
        except HarnessFailure as error:
            log(f"harness failure in {factory.name}: {error}")
            scenario.observations["harness_failure"] = str(error)
            out["scenarios"][factory.name] = scenario.observations
            out["harness_failure"] = f"{factory.name}: {error}"
            status = 2
        except Exception as error:  # anything unexpected here is ours, not theirs
            log(f"harness failure in {factory.name}: {type(error).__name__}: {error}")
            scenario.observations["harness_failure"] = f"{type(error).__name__}: {error}"
            out["scenarios"][factory.name] = scenario.observations
            out["harness_failure"] = f"{factory.name}: {type(error).__name__}: {error}"
            status = 2

        seam = out["scenarios"][factory.name].get("seam", "unknown")
        if seam == "absent":
            # Nothing is implemented. The remaining scenarios would say the
            # same thing more slowly.
            out["seam"] = "absent"
            break
        if seam == "present":
            out["seam"] = "present"
        if status:
            break

    with open(os.path.join(args.run_dir, "observations.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, sort_keys=True)
    return status


if __name__ == "__main__":
    sys.exit(main())
