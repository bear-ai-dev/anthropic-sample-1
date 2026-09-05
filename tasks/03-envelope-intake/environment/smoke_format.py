#!/usr/bin/env python3
"""Renders a run-fixture report the way the shipped goldens are written.

`sandbox/run-fixture.ts` prints `JSON.stringify(report, null, 2)`, which puts
every leaf object across five lines and makes a five-operation answer forty
lines long. The shipped `smoke.out.json` keeps a short object on one line, so a
solver can read an outcome or an outbox row as a row. That is a formatting
choice and not a content one, so it belongs in the generator rather than in
somebody's editor: `environment/gen_smoke.sh` pipes the runner's own stdout through
this and writes the result.

Two rules, which between them reproduce every shipped golden byte for byte. A
list whose items are all scalars goes on one line; a list of objects gets one
object per line, because the objects are rows and the point is to read them as
rows. An object goes on one line when it fits in `WIDTH` columns including its
indent. Key order is the runner's.

    tsx sandbox/run-fixture.ts sandbox/smoke.jsonl | python3 environment/smoke_format.py
"""

from __future__ import annotations

import json
import sys

WIDTH = 100


def one_line(value: object) -> str:
    """`json.dumps` with a space inside braces, done structurally.

    Doing it with `str.replace` would rewrite a brace inside a string, and a
    message identifier is exactly the kind of value that has one.
    """
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = ", ".join(f"{json.dumps(key)}: {one_line(item)}" for key, item in value.items())
        return "{ " + inner + " }"
    if isinstance(value, list):
        return "[" + ", ".join(one_line(item) for item in value) + "]"
    return json.dumps(value)


def render(value: object, indent: int) -> str:
    if not isinstance(value, (dict, list)):
        return json.dumps(value)
    pad = " " * (indent + 2)
    if isinstance(value, list):
        if all(not isinstance(item, (dict, list)) for item in value):
            return one_line(value)
        body = ",\n".join(f"{pad}{render(item, indent + 2)}" for item in value)
        return "[\n" + body + "\n" + " " * indent + "]"
    flat = one_line(value)
    if indent + len(flat) <= WIDTH:
        return flat
    body = ",\n".join(
        f"{pad}{json.dumps(key)}: {render(item, indent + 2)}" for key, item in value.items()
    )
    return "{\n" + body + "\n" + " " * indent + "}"


def main() -> int:
    text = sys.stdin.read().strip()
    if not text:
        sys.stderr.write("nothing on stdin: the runner printed no report\n")
        return 1
    sys.stdout.write(render(json.loads(text), 0) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
