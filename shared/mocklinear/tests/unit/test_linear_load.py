from datetime import datetime
from typing import Any

import pytest

from mocklinear.clock import parse_ts
from mocklinear.ids import uuid_for
from mocklinear.linear.load import load
from mocklinear.linear.state import LinearState
from mocklinear.scenario import ScenarioError
from mocklinear.tests.require import require

SEED = 7


def test_every_entity_takes_its_id_from_the_seeded_key(state: LinearState) -> None:
    assert state.organization.id == uuid_for(SEED, "linear", "organization", "ExampleCo")
    assert state.viewer.id == uuid_for(SEED, "linear", "user", "u-dana")
    assert require(state.team("WEB")).id == uuid_for(SEED, "linear", "team", "WEB")
    assert require(state.issue("WEB-611")).id == uuid_for(SEED, "linear", "issue", "WEB-611")
    assert require(state.project("Door operations")).id == uuid_for(
        SEED, "linear", "project", "door-ops"
    )
    assert require(state.document("door-runbook")).id == uuid_for(
        SEED, "linear", "document", "door-runbook"
    )
    assert state.attachment(uuid_for(SEED, "linear", "attachment", "att-door-scan")) is not None


def test_a_second_seed_shares_no_identifier_with_the_first(
    scenario: dict[str, object], now: datetime
) -> None:
    other = load(scenario["linear"], 41, now)  # type: ignore[arg-type]
    first = load(scenario["linear"], SEED, now)  # type: ignore[arg-type]
    assert require(other.issue("WEB-611")).id != require(first.issue("WEB-611")).id
    assert other.viewer.id != first.viewer.id


def test_cycles_are_keyed_by_team_and_number(state: LinearState) -> None:
    web = require(state.team("WEB"))
    assert [cycle.number for cycle in web.cycles] == [41, 42, 43, 44]
    assert web.cycles[0].id == uuid_for(SEED, "linear", "cycle", "WEB:41")
    assert web.cycles[2].starts_at == parse_ts("2026-03-02T00:00:00Z")


def test_a_label_is_workspace_wide_unless_a_team_declares_it(state: LinearState) -> None:
    assert require(state.label("bug")).team_key is None
    regression = require(state.label("Regression"))
    assert regression is not None
    assert regression.team_key == "WEB"
    assert state.label("missing") is None


def test_a_project_carries_its_lead_teams_and_milestones(state: LinearState) -> None:
    project = require(state.project("Door operations"))
    assert project.key == "door-ops"
    assert project.lead_key == "u-dana"
    assert project.team_keys == ("WEB",)
    assert [milestone.key for milestone in project.milestones] == ["m-scan", "m-reporting"]
    assert require(state.milestone("Scanner reliability")).project_key == "door-ops"
    assert state.milestone("m-nope") is None
    assert state.project("no-such-project") is None


def test_an_issue_resolves_its_cross_references_and_defaults(state: LinearState) -> None:
    issue = require(state.issue("WEB-611"))
    assert state.issue(issue.id) is issue
    assert issue.team_key == "WEB"
    assert issue.state_key == "web-progress"
    assert issue.assignee_key == "u-dana"
    assert issue.label_keys == ("bug", "escalation", "web-regression")
    assert issue.cycle_key == "WEB:43"
    assert issue.milestone_key == "m-scan"
    assert issue.due_date == "2026-03-10"
    assert issue.estimate == 3
    assert issue.started_at == parse_ts("2026-02-20T11:00:00Z")
    assert issue.completed_at is None
    assert issue.canceled_at is None
    assert state.issue("WEB-999") is None


def test_an_unset_issue_field_becomes_none_and_the_parent_is_kept(state: LinearState) -> None:
    child = require(state.issue("WEB-615"))
    assert child.parent_identifier == "WEB-614"
    assert child.due_date is None
    assert require(state.issue("WEB-617")).assignee_key is None
    assert require(state.issue("WEB-618")).estimate is None
    assert require(state.issue("WEB-618")).priority == 0


def test_a_branch_name_is_derived_from_the_assignee_and_title_unless_authored(
    state: LinearState,
) -> None:
    assert require(state.issue("WEB-611")).branch_name == "dana/web-611-reentry-scan"
    assert (
        require(state.issue("WEB-612")).branch_name
        == "dana/web-612-door-list-export-drops-guests-added-afte"
    )
    assert (
        require(state.issue("WEB-617")).branch_name
        == "dana/web-617-remove-the-legacy-checkout-banner"
    )


def test_comments_keep_their_thread_and_their_issue(state: LinearState) -> None:
    comments = require(state.issue("WEB-611")).comments
    assert [comment.key for comment in comments] == ["c-611-1", "c-611-2", "c-611-3"]
    assert comments[2].parent_key == "c-611-2"
    assert comments[0].parent_key is None
    assert comments[0].issue_identifier == "WEB-611"
    assert comments[0].id == uuid_for(SEED, "linear", "comment", "c-611-1")


def test_attachments_are_reachable_by_id_and_know_their_issue(state: LinearState) -> None:
    attachment = require(state.issue("WEB-611")).attachments[0]
    assert attachment.title == "door-scan.mov"
    assert attachment.issue_identifier == "WEB-611"
    assert state.attachment(attachment.id) is attachment
    assert state.attachment("nope") is None


def test_an_empty_section_loads_an_empty_workspace(now: datetime) -> None:
    empty = load({}, SEED, now)
    assert empty.issues == ()
    assert empty.users == ()
    assert empty.organization.name == "Workspace"
    assert empty.viewer.key == ""
    assert empty.user("me") is empty.viewer


def test_an_issue_that_names_something_the_workspace_lacks_is_refused(
    scenario: dict[str, object], now: datetime
) -> None:
    section: dict[str, object] = scenario["linear"]  # type: ignore[assignment]
    cases = {
        "team": ("team", "QA"),
        "state": ("state", "Shipped"),
        "cycle": ("cycle", 99),
        "assignee": ("assignee", "ghost"),
    }
    for kind, (field, value) in cases.items():
        broken = dict(section)
        first = dict(broken["issues"][0])  # type: ignore[index]
        first[field] = value
        broken["issues"] = [first]
        with pytest.raises(ScenarioError, match=f"unknown {kind}: {value}"):
            load(broken, SEED, now)


def test_an_issue_that_names_a_milestone_the_workspace_lacks_is_refused(
    scenario: dict[str, Any], now: datetime
) -> None:
    section: dict[str, Any] = dict(scenario["linear"])
    first = dict(section["issues"][0])
    first["milestone"] = "m-ghost"
    section["issues"] = [first]
    with pytest.raises(ScenarioError, match="unknown milestone: m-ghost"):
        load(section, SEED, now)
