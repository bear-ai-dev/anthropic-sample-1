import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from mockgithub.clock import parse_ts
from mockgithub.engine import Engine
from mockgithub.github.load import load
from mockgithub.github.state import GithubState
from mockgithub.journal import Journal
from mockgithub.scenario import validate_scenario

SCENARIO_CLOCK = "2026-03-04T10:00:00Z"
FIXTURE = Path(__file__).parent / "fixtures" / "github.json"
SEED = 7


@pytest.fixture
def now() -> datetime:
    return parse_ts(SCENARIO_CLOCK)


@pytest.fixture
def scenario() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def state(scenario: dict[str, Any], now: datetime) -> GithubState:
    return load(scenario["github"], SEED, now)


@pytest.fixture
def engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), SEED, Journal(None))
