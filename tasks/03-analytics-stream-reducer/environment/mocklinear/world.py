from __future__ import annotations

from typing import Any

from .clock import iso_seconds, parse_ts
from .linear.load import load
from .linear.state import LinearState
from .scenario import SERVICE, scenario_sha256


class World:
    def __init__(self, scenario: dict[str, Any], seed: int) -> None:
        self.seed = seed
        self.clock = parse_ts(scenario["clock"])
        self.scenario_sha256 = scenario_sha256(scenario)
        self.faults_config: dict[str, Any] = scenario.get("faults") or {}
        self.linear: LinearState = load(scenario.get(SERVICE, {}), seed, self.clock)

    def snapshot(self) -> dict[str, Any]:
        return {
            "clock": iso_seconds(self.clock),
            "seed": self.seed,
            "scenario_sha256": self.scenario_sha256,
            "services": [SERVICE],
            SERVICE: self.linear.id_map(),
        }
