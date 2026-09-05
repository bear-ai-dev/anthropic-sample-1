from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any


class Journal:
    def __init__(self, sink_path: str | None) -> None:
        self.sink_path = sink_path
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._create()

    def _create(self) -> None:
        if not self.sink_path:
            return
        try:
            os.close(os.open(self.sink_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600))
        except OSError as failure:
            self._report(failure)

    def _report(self, failure: OSError) -> None:
        print(
            f"mocklinear: cannot write journal {self.sink_path}: "
            f"{type(failure).__name__}: {failure}",
            file=sys.stderr,
            flush=True,
        )

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            stamped = dict(entry)
            stamped["seq"] = len(self._records)
            stamped["at"] = time.time()
            self._records.append(stamped)
            self._append(stamped)
            return stamped

    def _append(self, stamped: dict[str, Any]) -> None:
        if not self.sink_path:
            return
        line = json.dumps(stamped, separators=(",", ":"), sort_keys=True)
        try:
            with open(self.sink_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
        except OSError as failure:
            self._report(failure)

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
