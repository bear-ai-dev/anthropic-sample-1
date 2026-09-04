from typing import Any

from mockgmail.registry import ServiceRegistry, build_registries
from mockgmail.scenario import scenario_sha256, validate_scenario
from mockgmail.tests.require import require
from mockgmail.world import World


def test_the_world_carries_its_clock_seed_and_scenario_digest(scenario: dict[str, Any]) -> None:
    world = World(validate_scenario(scenario), seed=7)
    assert world.seed == 7
    assert world.snapshot()["clock"] == "2026-03-04T10:00:00Z"
    assert world.snapshot()["seed"] == 7
    assert world.snapshot()["scenario_sha256"] == scenario_sha256(validate_scenario(scenario))
    assert world.snapshot()["services"] == ["gmail"]


def test_the_snapshot_maps_human_keys_to_the_identifiers_the_tools_return(
    scenario: dict[str, Any],
) -> None:
    world = World(validate_scenario(scenario), seed=7)
    snapshot = world.snapshot()
    newest = world.gmail.messages[0]
    assert snapshot["gmail"]["messages"]["alcaraz-2"] == {
        "id": newest.id,
        "threadId": newest.thread_id,
    }
    assert snapshot["gmail"]["labels"]["support"] == require(world.gmail.label("Support")).id


def test_a_world_without_a_gmail_section_is_empty_but_usable() -> None:
    world = World(validate_scenario({"version": 1, "clock": "2026-03-04T10:00:00Z"}), seed=7)
    assert world.gmail.messages == ()
    assert world.faults_config == {}


def test_the_fault_configuration_travels_with_the_world(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"enabled": False, "rules": []}
    world = World(validate_scenario(scenario), seed=7)
    assert world.faults_config == {"enabled": False, "rules": []}


def test_the_registry_answers_only_for_the_gmail_service() -> None:
    registries = build_registries()
    assert list(registries) == ["gmail"]
    registry = registries["gmail"]
    assert isinstance(registry, ServiceRegistry)
    assert registry.service == "gmail"
    assert registry.get("no_such_tool") is None
    assert registry.errors.rate_limited("x").content[0]["text"] == "Error: Rate Limit Exceeded"


def test_a_scenario_whose_faults_are_null_loads_as_no_faults(scenario: dict[str, Any]) -> None:
    scenario["faults"] = None
    world = World(validate_scenario(scenario), seed=7)
    assert world.faults_config == {}
