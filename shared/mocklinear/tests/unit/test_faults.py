from typing import Any

from mocklinear.fault_rule import FaultRule, rules_from
from mocklinear.faults import FaultInjector
from mocklinear.tool_errors import Throttled, TransientServerError

BURST_CONFIG: dict[str, Any] = {
    "rules": [
        {"service": "linear", "tool": "list_issues", "throttle_every": 3, "throttle_burst": 2}
    ]
}


def _drive(injector: FaultInjector, service: str, tool: str, calls: int) -> list[str]:
    outcomes: list[str] = []
    for _ in range(calls):
        try:
            injector.before_call(service, tool)
        except Throttled:
            outcomes.append("throttled")
        except TransientServerError:
            outcomes.append("server_error")
        else:
            outcomes.append("ok")
    return outcomes


def test_throttle_fires_on_a_seed_phased_call_index_and_bursts() -> None:
    outcomes = _drive(FaultInjector(BURST_CONFIG, seed=7), "linear", "list_issues", 9)
    assert outcomes.count("throttled") == 6
    assert outcomes == _drive(FaultInjector(BURST_CONFIG, seed=7), "linear", "list_issues", 9)


def test_two_seeds_throttle_on_different_call_indexes() -> None:
    config: dict[str, Any] = {
        "rules": [{"service": "linear", "tool": "list_issues", "throttle_every": 4}]
    }
    first = _drive(FaultInjector(config, seed=7), "linear", "list_issues", 8)
    second = _drive(FaultInjector(config, seed=41), "linear", "list_issues", 8)
    assert first.count("throttled") == 2
    assert second.count("throttled") == 2
    assert first != second


def test_counters_advance_even_when_no_rule_matches() -> None:
    injector = FaultInjector(None, 7)
    injector.before_call("linear", "get_issue")
    assert injector.stats() == {"linear:get_issue": 1}


def test_a_disabled_injector_counts_calls_but_injects_nothing() -> None:
    config: dict[str, Any] = {
        "enabled": False,
        "rules": [{"throttle_every": 1, "latency_seconds": 2.0, "max_page_size": 1}],
    }
    injector = FaultInjector(config, seed=7)
    assert not injector.enabled
    assert _drive(injector, "linear", "get_issue", 3) == ["ok", "ok", "ok"]
    assert injector.page_size("linear", "get_issue", 50) == 50
    assert injector.stats() == {"linear:get_issue": 3}


def test_a_server_error_rule_fires_on_its_own_cycle() -> None:
    config: dict[str, Any] = {"rules": [{"service": "linear", "server_error_every": 2}]}
    outcomes = _drive(FaultInjector(config, seed=7), "linear", "get_issue", 6)
    assert outcomes.count("server_error") == 3
    assert outcomes.count("ok") == 3


def test_the_page_size_cap_is_the_tightest_matching_rule() -> None:
    config: dict[str, Any] = {
        "rules": [
            {"service": "*", "tool": "*", "max_page_size": 20},
            {"service": "linear", "tool": "list_issues", "max_page_size": 5},
            {"service": "linear", "tool": "list_issues"},
        ]
    }
    injector = FaultInjector(config, seed=7)
    assert injector.page_size("linear", "list_issues", 50) == 5
    assert injector.page_size("linear", "list_issues", 3) == 3
    assert injector.page_size("linear", "list_teams", 50) == 20
    assert FaultInjector(None, 7).page_size("linear", "list_teams", 50) == 50


def test_a_non_positive_page_cap_does_not_shrink_a_page() -> None:
    config: dict[str, Any] = {
        "rules": [{"service": "linear", "tool": "list_issues", "max_page_size": -3}]
    }
    assert FaultInjector(config, seed=7).page_size("linear", "list_issues", 50) == 50


def test_latency_is_the_widest_matching_rule_and_is_returned_not_slept() -> None:
    config: dict[str, Any] = {
        "rules": [
            {"service": "linear", "latency_seconds": 0.25},
            {"service": "linear", "tool": "get_issue", "latency_seconds": 0.5},
        ]
    }
    injector = FaultInjector(config, seed=7)
    assert injector.before_call("linear", "get_issue") == 0.5
    assert injector.before_call("linear", "list_teams") == 0.25
    assert FaultInjector(None, 7).before_call("linear", "list_teams") == 0.0


def test_stats_are_keyed_by_service_and_tool_in_sorted_order() -> None:
    injector = FaultInjector(None, 7)
    injector.before_call("linear", "get_issue")
    injector.before_call("probe", "get_issue")
    injector.before_call("linear", "get_issue")
    assert list(injector.stats().items()) == [("linear:get_issue", 2), ("probe:get_issue", 1)]


def test_a_rule_defaults_to_every_service_and_tool_and_a_burst_of_one() -> None:
    rule = FaultRule()
    assert rule.matches("linear", "list_issues")
    assert rule.throttle_burst == 1
    scoped = FaultRule(service="linear", tool="list_issues")
    assert scoped.matches("linear", "list_issues")
    assert not scoped.matches("probe", "list_issues")
    assert not scoped.matches("linear", "get_issue")


def test_rules_are_read_from_the_scenario_configuration() -> None:
    assert rules_from(None) == []
    assert rules_from({}) == []
    rules = rules_from(
        {
            "rules": [
                {"service": "linear", "throttle_every": "4", "throttle_burst": 0},
                {"tool": "get_issue", "latency_seconds": 1, "max_page_size": "10"},
            ]
        }
    )
    assert rules[0] == FaultRule(service="linear", tool="*", throttle_every=4, throttle_burst=1)
    assert rules[1] == FaultRule(tool="get_issue", latency_seconds=1.0, max_page_size=10)
