from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer

from .admin import ADMIN_TOKEN_ENV
from .engine import Engine
from .http_handler import make_handler
from .journal import Journal
from .scenario import SERVICE, load_scenario

DEFAULT_PORT = 4570
JOURNAL_ENV = "MOCKLINEAR_JOURNAL"


def build_server(
    engine: Engine, host: str, port: int, admin_token: str | None
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), make_handler(engine, admin_token))
    server.daemon_threads = True
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mocklinear", description=f"Deterministic mock {SERVICE}")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    scenario = load_scenario(args.scenario)
    engine = Engine(scenario, args.seed, Journal(os.environ.get(JOURNAL_ENV)))
    server = build_server(engine, args.host, args.port, os.environ.get(ADMIN_TOKEN_ENV))
    port = server.server_address[1]
    print(
        f"mocklinear listening on http://{args.host}:{port} "
        f"(scenario={args.scenario}, seed={args.seed})",
        flush=True,
    )
    server.serve_forever()
    return 0
