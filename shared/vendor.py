#!/usr/bin/env python3
"""Vendor a shared mock service package into a task's build context.

Each task directory has to be a self-contained Harbor task, so shared material
is copied in rather than referenced. `shared/mock<service>` is the *starting
point* for a task, not a running source of truth: once a task has extended its
vendored copy, that task owns it, and this script leaves it alone unless told
`--force`.

Default pairs:

    mocklinear   tasks/01-linearizable-scan
    mocklinear   tasks/02-recurring-events
    mocklinear   tasks/03-analytics-stream-reducer
    mocklinear   tasks/04-draft-recovery
    mockgmail    tasks/08-envelope-intake
    mockgithub   tasks/11-store-cutover
    mockgithub   tasks/12-readmodel-rebuild

Usage: python3 shared/vendor.py [--force] [<package> <task-dir>]...
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared"
DEFAULT_PAIRS = (
    ("mocklinear", "tasks/01-linearizable-scan"),
    ("mocklinear", "tasks/02-recurring-events"),
    ("mocklinear", "tasks/03-analytics-stream-reducer"),
    ("mocklinear", "tasks/04-draft-recovery"),
    ("mockgmail", "tasks/08-envelope-intake"),
    ("mockgithub", "tasks/11-store-cutover"),
    ("mockgithub", "tasks/12-readmodel-rebuild"),
)
IGNORE = shutil.ignore_patterns("__pycache__", "tests", "*.pyc", ".venv", ".pytest_cache")


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg != "--force"]
    force = "--force" in sys.argv
    if len(args) % 2:
        print(__doc__, file=sys.stderr)
        return 2
    pairs = list(zip(args[::2], args[1::2], strict=True)) or list(DEFAULT_PAIRS)
    skipped = False
    for package, task in pairs:
        source = SHARED / package
        if not (source / "__init__.py").is_file():
            print(f"missing shared package: {source}", file=sys.stderr)
            return 1
        task_dir = (ROOT / task).resolve()
        if not (task_dir / "task.toml").is_file():
            print(f"not a task directory: {task_dir}", file=sys.stderr)
            return 1
        destination = task_dir / "environment" / package
        if destination.exists() and _diverged(source, destination) and not force:
            print(f"task-owned, left alone -> {destination.relative_to(ROOT)}")
            skipped = True
            continue
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=IGNORE)
        print(f"vendored {package} -> {destination.relative_to(ROOT)}")
    if skipped:
        print("\nTask-owned mocks were left as they are; --force discards those edits.")
    return 0


def _diverged(source: Path, destination: Path) -> bool:
    for path in source.rglob("*.py"):
        if "__pycache__" in path.parts or "tests" in path.parts:
            continue
        mirror = destination / path.relative_to(source)
        if not mirror.exists() or mirror.read_bytes() != path.read_bytes():
            return True
    for path in destination.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if not (source / path.relative_to(destination)).exists():
            return True
    return False


if __name__ == "__main__":
    raise SystemExit(main())
