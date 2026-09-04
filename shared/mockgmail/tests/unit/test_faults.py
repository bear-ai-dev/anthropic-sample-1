from typing import Any

from mockgmail.fault_rule import FaultRule, rules_from
from mockgmail.faults import FaultInjector
from mockgmail.tool_errors import Throttled, TransientServerError

BURST_CONFIG: dict[str, Any] = {
    "rules": [
        {"service": "gmail", "tool": "search_emails", "throttle_every": 3, "throttle_burst": 2}
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
    outcomes = _drive(FaultInjector(BURST_CONFIG, seed=7), "gmail", "search_emails", 9)
    assert outcomes.count("throttled") == 6
    assert outcomes == _drive(FaultInjector(BURST_CONFIG, seed=7), "gmail", "search_emails", 9)


def test_two_seeds_throttle_on_different_call_indexes() -> None:
    config: dict[str, Any] = {
        "rules": [{"service": "gmail", "tool": "search_emails", "throttle_every": 4}]
    }
    first = _drive(FaultInjector(config, seed=7), "gmail", "search_emails", 8)
    second = _drive(FaultInjector(config, seed=41), "gmail", "search_emails", 8)
    assert first.count("throttled") == 2
    assert second.count("throttled") == 2
    assert first != second


def test_counters_advance_even_when_no_rule_matches() -> None:
    injector = FaultInjector(None, 7)
    injector.before_call("gmail", "read_email")
    assert injector.stats() == {"gmail:read_email": 1}


def test_a_disabled_injector_counts_calls_but_injects_nothing() -> None:
    config: dict[str, Any] = {
        "enabled": False,
        "rules": [{"throttle_every": 1, "latency_seconds": 2.0, "max_page_size": 1}],
    }
    injector = FaultInjector(config, seed=7)
    assert not injector.enabled
    assert _drive(injector, "gmail", "read_email", 3) == ["ok", "ok", "ok"]
    assert injector.page_size("gmail", "read_email", 50) == 50
    assert injector.stats() == {"gmail:read_email": 3}


def test_a_server_error_rule_fires_on_its_own_cycle() -> None:
    config: dict[str, Any] = {"rules": [{"service": "gmail", "server_error_every": 2}]}
    outcomes = _drive(FaultInjector(config, seed=7), "gmail", "read_email", 6)
    assert outcomes.count("server_error") == 3
    assert outcomes.count("ok") == 3


def test_the_page_size_cap_is_the_tightest_matching_rule() -> None:
    config: dict[str, Any] = {
        "rules": [
            {"service": "*", "tool": "*", "max_page_size": 20},
            {"service": "gmail", "tool": "search_emails", "max_page_size": 5},
            {"service": "gmail", "tool": "search_emails"},
        ]
    }
    injector = FaultInjector(config, seed=7)
    assert injector.page_size("gmail", "search_emails", 50) == 5
    assert injector.page_size("gmail", "search_emails", 3) == 3
    assert injector.page_size("gmail", "list_email_labels", 50) == 20
    assert FaultInjector(None, 7).page_size("gmail", "list_email_labels", 50) == 50


def test_a_non_positive_page_cap_does_not_shrink_a_page() -> None:
    config: dict[str, Any] = {
        "rules": [{"service": "gmail", "tool": "search_emails", "max_page_size": -3}]
    }
    assert FaultInjector(config, seed=7).page_size("gmail", "search_emails", 50) == 50


def test_latency_is_the_widest_matching_rule_and_is_returned_not_slept() -> None:
    config: dict[str, Any] = {
        "rules": [
            {"service": "gmail", "latency_seconds": 0.25},
            {"service": "gmail", "tool": "read_email", "latency_seconds": 0.5},
        ]
    }
    injector = FaultInjector(config, seed=7)
    assert injector.before_call("gmail", "read_email") == 0.5
    assert injector.before_call("gmail", "list_email_labels") == 0.25
    assert FaultInjector(None, 7).before_call("gmail", "list_email_labels") == 0.0


def test_stats_are_keyed_by_service_and_tool_in_sorted_order() -> None:
    injector = FaultInjector(None, 7)
    injector.before_call("gmail", "read_email")
    injector.before_call("probe", "read_email")
    injector.before_call("gmail", "read_email")
    assert list(injector.stats().items()) == [("gmail:read_email", 2), ("probe:read_email", 1)]


def test_a_rule_defaults_to_every_service_and_tool_and_a_burst_of_one() -> None:
    rule = FaultRule()
    assert rule.matches("gmail", "search_emails")
    assert rule.throttle_burst == 1
    scoped = FaultRule(service="gmail", tool="search_emails")
    assert scoped.matches("gmail", "search_emails")
    assert not scoped.matches("probe", "search_emails")
    assert not scoped.matches("gmail", "read_email")


def test_rules_are_read_from_the_scenario_configuration() -> None:
    assert rules_from(None) == []
    assert rules_from({}) == []
    rules = rules_from(
        {
            "rules": [
                {"service": "gmail", "throttle_every": "4", "throttle_burst": 0},
                {"tool": "read_email", "latency_seconds": 1, "max_page_size": "10"},
            ]
        }
    )
    assert rules[0] == FaultRule(service="gmail", tool="*", throttle_every=4, throttle_burst=1)
    assert rules[1] == FaultRule(tool="read_email", latency_seconds=1.0, max_page_size=10)
