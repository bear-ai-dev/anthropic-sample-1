from typing import Any

from mockgithub.registry import ServiceRegistry, build_registries
from mockgithub.scenario import scenario_sha256, validate_scenario
from mockgithub.tests.require import require
from mockgithub.world import World


def test_the_world_carries_its_clock_seed_and_scenario_digest(scenario: dict[str, Any]) -> None:
    world = World(validate_scenario(scenario), seed=7)
    assert world.seed == 7
    assert world.snapshot()["clock"] == "2026-03-04T10:00:00Z"
    assert world.snapshot()["seed"] == 7
    assert world.snapshot()["scenario_sha256"] == scenario_sha256(validate_scenario(scenario))
    assert world.snapshot()["services"] == ["github"]


def test_the_snapshot_maps_human_keys_to_the_identifiers_the_tools_return(
    scenario: dict[str, Any],
) -> None:
    world = World(validate_scenario(scenario), seed=7)
    snapshot = world.snapshot()
    assert snapshot["github"]["users"]["rhea-menon"] == world.github.viewer.id
    ledger = require(world.github.repo("ExampleCo", "membership-ledger"))
    assert snapshot["github"]["ExampleCo/membership-ledger"]["issues"] == [
        issue.number for issue in ledger.issues
    ]


def test_a_world_without_a_github_section_is_empty_but_usable() -> None:
    world = World(validate_scenario({"version": 1, "clock": "2026-03-04T10:00:00Z"}), seed=7)
    assert world.github.repos == ()
    assert world.faults_config == {}


def test_the_fault_configuration_travels_with_the_world(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"enabled": False, "rules": []}
    world = World(validate_scenario(scenario), seed=7)
    assert world.faults_config == {"enabled": False, "rules": []}


def test_the_registry_answers_only_for_the_github_service() -> None:
    registries = build_registries()
    assert list(registries) == ["github"]
    registry = registries["github"]
    assert isinstance(registry, ServiceRegistry)
    assert registry.service == "github"
    assert registry.get("no_such_tool") is None
    assert registry.errors.rate_limited("x").is_error


def test_a_scenario_whose_faults_are_null_loads_as_no_faults(scenario: dict[str, Any]) -> None:
    scenario["faults"] = None
    world = World(validate_scenario(scenario), seed=7)
    assert world.faults_config == {}
