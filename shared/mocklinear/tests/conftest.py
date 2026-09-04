import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from mocklinear.clock import parse_ts
from mocklinear.linear.load import load
from mocklinear.linear.state import LinearState

SCENARIO_CLOCK = "2026-03-04T10:00:00Z"
FIXTURE = Path(__file__).parent / "fixtures" / "linear.json"
SEED = 7


@pytest.fixture
def now() -> datetime:
    return parse_ts(SCENARIO_CLOCK)


@pytest.fixture
def scenario() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def state(scenario: dict[str, Any], now: datetime) -> LinearState:
    return load(scenario["linear"], SEED, now)
