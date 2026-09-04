from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FaultRule:
    service: str = "*"
    tool: str = "*"
    throttle_every: int = 0
    throttle_burst: int = 1
    server_error_every: int = 0
    max_page_size: int = 0
    latency_seconds: float = 0.0

    def matches(self, service: str, tool: str) -> bool:
        if self.service not in (service, "*"):
            return False
        return self.tool in (tool, "*")


def rules_from(config: dict[str, Any] | None) -> list[FaultRule]:
    raw_rules: list[dict[str, Any]] = (config or {}).get("rules", [])
    return [
        FaultRule(
            service=str(raw.get("service", "*")),
            tool=str(raw.get("tool", "*")),
            throttle_every=int(raw.get("throttle_every", 0)),
            throttle_burst=max(1, int(raw.get("throttle_burst", 1))),
            server_error_every=int(raw.get("server_error_every", 0)),
            max_page_size=int(raw.get("max_page_size", 0)),
            latency_seconds=float(raw.get("latency_seconds", 0.0)),
        )
        for raw in raw_rules
    ]
