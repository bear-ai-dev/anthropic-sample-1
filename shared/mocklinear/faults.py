from __future__ import annotations

import hashlib
import threading
from typing import Any

from .fault_rule import FaultRule, rules_from
from .tool_errors import Throttled, TransientServerError


class FaultInjector:
    def __init__(self, config: dict[str, Any] | None, seed: int) -> None:
        settings = config or {}
        self.seed = seed
        self.enabled: bool = bool(settings.get("enabled", True))
        self.rules: list[FaultRule] = rules_from(settings)
        self._counts: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def _rules_for(self, service: str, tool: str) -> list[FaultRule]:
        return [rule for rule in self.rules if rule.matches(service, tool)]

    def _bump(self, service: str, tool: str) -> int:
        with self._lock:
            key = (service, tool)
            self._counts[key] = self._counts.get(key, 0) + 1
            return self._counts[key]

    def _phase(self, service: str, tool: str, modulus: int) -> int:
        raw = f"{self.seed}:{service}:{tool}".encode()
        return int(hashlib.sha256(raw).hexdigest(), 16) % modulus

    def before_call(self, service: str, tool: str) -> float:
        count = self._bump(service, tool)
        if not self.enabled:
            return 0.0
        latency = 0.0
        for rule in self._rules_for(service, tool):
            latency = max(latency, rule.latency_seconds)
            if rule.server_error_every > 0:
                offset = self._phase(service, tool, rule.server_error_every)
                if (count + offset) % rule.server_error_every == 0:
                    raise TransientServerError(f"internal error for {service}:{tool}")
            if rule.throttle_every > 0:
                offset = self._phase(service, tool, rule.throttle_every)
                position = (count + offset) % rule.throttle_every
                if position == 0 or position > rule.throttle_every - rule.throttle_burst:
                    raise Throttled(f"rate limit exceeded for {service}:{tool}")
        return latency

    def page_size(self, service: str, tool: str, requested: int) -> int:
        if not self.enabled:
            return requested
        caps = [
            rule.max_page_size for rule in self._rules_for(service, tool) if rule.max_page_size > 0
        ]
        if not caps:
            return requested
        return min(requested, min(caps))

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                f"{service}:{tool}": count
                for (service, tool), count in sorted(self._counts.items())
            }
