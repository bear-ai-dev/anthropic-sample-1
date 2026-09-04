import json
from pathlib import Path
from typing import Any

import pytest

from mockgithub.scenario import (
    SCENARIO_VERSION,
    ScenarioError,
    load_scenario,
    scenario_sha256,
    validate_scenario,
)


def _minimal() -> dict[str, Any]:
    return {"version": 1, "clock": "2026-03-04T10:00:00Z"}


def test_the_supported_version_is_one() -> None:
    assert SCENARIO_VERSION == 1


def test_a_minimal_scenario_gains_an_empty_github_section() -> None:
    validated = validate_scenario(_minimal())
    assert validated["github"] == {}
    assert validated["faults"] == {}
    assert validated["clock"] == "2026-03-04T10:00:00Z"


def test_an_unknown_top_level_key_is_named_in_the_error() -> None:
    raw = _minimal()
    raw["linear"] = {}
    with pytest.raises(ScenarioError, match="unknown top-level key: linear"):
        validate_scenario(raw)


def test_a_missing_or_wrong_version_is_refused() -> None:
    with pytest.raises(ScenarioError, match="missing top-level key: version"):
        validate_scenario({"clock": "2026-03-04T10:00:00Z"})
    with pytest.raises(ScenarioError, match="unsupported scenario version: 2"):
        validate_scenario({"version": 2, "clock": "2026-03-04T10:00:00Z"})


def test_a_missing_or_unparseable_clock_is_refused() -> None:
    with pytest.raises(ScenarioError, match="missing top-level key: clock"):
        validate_scenario({"version": 1})
    with pytest.raises(ScenarioError, match="clock is not a timestamp: soon"):
        validate_scenario({"version": 1, "clock": "soon"})


def test_the_digest_is_independent_of_key_order() -> None:
    first = {"version": 1, "clock": "2026-03-04T10:00:00Z", "github": {"viewer": "dana"}}
    second = {"github": {"viewer": "dana"}, "clock": "2026-03-04T10:00:00Z", "version": 1}
    assert scenario_sha256(first) == scenario_sha256(second)
    assert scenario_sha256(first) != scenario_sha256(_minimal())
    assert len(scenario_sha256(first)) == 64


def test_a_scenario_is_read_and_validated_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(_minimal()), encoding="utf-8")
    assert load_scenario(str(path))["github"] == {}


def test_a_file_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "scenario.json"
    path.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ScenarioError, match="scenario is not an object"):
        load_scenario(str(path))
