#!/usr/bin/env python3
"""Stops the submitted service and everything it started.

Killing the process the verifier forked is not enough. `npm start` is a shell
that spawns tsx that spawns node that spawns esbuild, all of it under `su`, and
`su` puts its child in a session of its own -- so the listener is neither the
process the verifier forked nor a member of its process group. Signal the
wrapper alone and the listener is reparented to init and survives: it keeps the
port, and it keeps an open handle on a store that has already been deleted, so
it answers the next run's deliveries from the previous run's data. That failure
grades a submission against a process it never started.

Two passes, in this order:

  1. the process tree below the recorded pids, collected once and up front,
     because a parent reaped first orphans its children beyond reach, and
     signalled leaves-first for the same reason;
  2. whatever still holds the port, found by matching the listening socket's
     inode against every process's open descriptors -- which does not care how
     the process is related to us, or whether it is related at all.

Exits 0 when the port is free, 1 when something still holds it. The caller
treats that as a harness failure rather than grading the run.

    stop_service.py --port 8421 [pid ...]
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import time


def parent_of(pid: int) -> int | None:
    # The comm field can contain spaces and parentheses, so split after the
    # last ") " rather than on whitespace.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8", errors="replace") as handle:
            tail = handle.read().rsplit(") ", 1)[1].split()
        return int(tail[1])
    except (OSError, IndexError, ValueError):
        return None


def live_pids() -> list[int]:
    return sorted(int(name) for name in os.listdir("/proc") if name.isdigit())


def process_tree(roots: list[int]) -> list[int]:
    """Every live descendant of roots, parents before children."""
    children: dict[int, list[int]] = {}
    for pid in live_pids():
        parent = parent_of(pid)
        if parent is not None:
            children.setdefault(parent, []).append(pid)

    ordered: list[int] = []
    seen: set[int] = set()
    queue = [pid for pid in roots if pid > 1]
    while queue:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        ordered.append(pid)
        queue.extend(children.get(pid, ()))
    return ordered


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def signal_all(pids: list[int], sig: signal.Signals) -> None:
    # Leaves first: killing a parent before its children hands the children to
    # init, and the recorded pids no longer reach them.
    for pid in reversed(pids):
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def port_free(port: int) -> bool:
    probe = socket.socket()
    probe.settimeout(0.5)
    try:
        probe.connect(("127.0.0.1", port))
    except OSError:
        return True
    finally:
        probe.close()
    return False


def listening_inodes(port: int) -> set[str]:
    """Inodes of sockets listening on port, from both v4 and v6 tables."""
    wanted = f"{port:04X}"
    inodes: set[str] = set()
    for table in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(table, encoding="utf-8", errors="replace") as handle:
                next(handle, None)
                for line in handle:
                    fields = line.split()
                    if len(fields) < 10:
                        continue
                    local, state, inode = fields[1], fields[3], fields[9]
                    # 0A is LISTEN.
                    if state == "0A" and local.rsplit(":", 1)[-1] == wanted:
                        inodes.add(inode)
        except OSError:
            continue
    return inodes


def holders(port: int) -> list[int]:
    inodes = listening_inodes(port)
    if not inodes:
        return []
    found: list[int] = []
    for pid in live_pids():
        if pid == os.getpid():
            continue
        directory = f"/proc/{pid}/fd"
        try:
            entries = os.listdir(directory)
        except OSError:
            continue
        for entry in entries:
            try:
                target = os.readlink(f"{directory}/{entry}")
            except OSError:
                continue
            if target.startswith("socket:[") and target[8:-1] in inodes:
                found.append(pid)
                break
    return found


def wait_until(predicate, budget_s: float) -> bool:
    deadline = time.monotonic() + budget_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--grace", type=float, default=6.0)
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the port is free and signal nothing at all",
    )
    parser.add_argument("pids", nargs="*")
    args = parser.parse_args()

    # On a shared build machine the thing on this port may belong to someone
    # else, and the precondition check must never signal it.
    if args.check:
        if port_free(args.port):
            return 0
        print(
            f"port {args.port} is in use (pids {holders(args.port) or 'unknown'})",
            file=sys.stderr,
        )
        return 1

    roots = []
    for raw in args.pids:
        raw = raw.strip()
        if raw.isdigit():
            roots.append(int(raw))

    # Collected before anything is signalled: this is the only moment the tree
    # is still intact.
    tree = process_tree(roots)

    if tree:
        signal_all(tree, signal.SIGTERM)
        wait_until(lambda: not any(alive(pid) for pid in tree), args.grace)
        signal_all(tree, signal.SIGKILL)
        wait_until(lambda: not any(alive(pid) for pid in tree), 3.0)

    # Anything still on the port is unrelated to the tree, or was orphaned by an
    # earlier run that did not clean up after itself. Either way it cannot be
    # allowed to answer the next run.
    if not port_free(args.port):
        stragglers = holders(args.port)
        if stragglers:
            signal_all(process_tree(stragglers), signal.SIGKILL)
        wait_until(lambda: port_free(args.port), 5.0)

    if not port_free(args.port):
        print(
            f"port {args.port} is still held after teardown"
            f" (pids {holders(args.port) or 'unknown'})",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
