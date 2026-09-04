from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError

SHARED = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SHARED))

from mockgmail.engine import Engine  # noqa: E402
from mockgmail.journal import Journal  # noqa: E402
from mockgmail.scenario import load_scenario  # noqa: E402
from mockgmail.serve import build_server  # noqa: E402
from mockgmail.tests.smoke_drive import FAILURES, check, drive_cli, drive_http, get  # noqa: E402

SCENARIO = Path(__file__).parent / "fixtures" / "gmail.json"
TOKEN = "smoke-token"


def drive_admin(base: str) -> None:
    print("\nAdmin plane")
    check("healthz is open", get(f"{base}/healthz") == {"ok": True, "services": ["gmail"]})
    snapshot = get(f"{base}/_admin/snapshot", {"x-mockgmail-admin-token": TOKEN})
    entry = snapshot["gmail"]["messages"]["okonjo-2"]
    check(
        "the snapshot maps a human key to opaque ids",
        len(entry["id"]) == 16 and len(entry["threadId"]) == 16,
        entry,
    )
    calls = get(f"{base}/_admin/calls", {"x-mockgmail-admin-token": TOKEN})
    vias = sorted({call["via"] for call in calls["calls"]})
    check("the journal saw both transports", vias == ["cli", "http"], vias)
    try:
        get(f"{base}/_admin/snapshot")
        check("the admin plane refuses an unauthenticated read", False, "no error raised")
    except HTTPError as error:
        check("the admin plane refuses an unauthenticated read", error.code == 403, error.code)


def main() -> int:
    engine = Engine(load_scenario(str(SCENARIO)), 7, Journal(None))
    server = build_server(engine, "127.0.0.1", 0, TOKEN)
    threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"mockgmail on {base}")
    try:
        with tempfile.TemporaryDirectory() as workdir:
            message_id, attachment_id = drive_http(base, Path(workdir))
            drive_cli(base, Path(workdir), message_id, attachment_id)
        drive_admin(base)
    finally:
        server.shutdown()
        server.server_close()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURES:")
        for failure in FAILURES:
            print(f"  - {failure}")
        return 1
    print("all smoke checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
