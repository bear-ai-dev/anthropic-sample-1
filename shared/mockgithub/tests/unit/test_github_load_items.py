import copy
import re
from datetime import datetime
from typing import Any

import pytest

from mockgithub.clock import iso_seconds
from mockgithub.github.load import load
from mockgithub.github.models_repo import Repo
from mockgithub.github.state import GithubState
from mockgithub.ids import number_for
from mockgithub.scenario import ScenarioError
from mockgithub.tests.conftest import SEED
from mockgithub.tests.require import require

LEDGER = ("ExampleCo", "membership-ledger")


def _ledger(state: GithubState) -> Repo:
    return require(state.repo(*LEDGER))


def test_an_issue_carries_its_relations_and_derived_timestamps(state: GithubState) -> None:
    repo = _ledger(state)
    issue = require(repo.issue(38))
    assert issue.id == number_for(SEED, "github", "issue", "ExampleCo/membership-ledger#38")
    assert issue.state == "closed"
    assert issue.label_names == ("ci", "flaky")
    assert issue.assignee_logins == ("mbeaulieu",)
    assert issue.milestone_number is None
    assert issue.user_login == "rhea-menon"
    assert iso_seconds(issue.created_at) == "2025-06-20T09:30:00Z"
    assert iso_seconds(require(issue.closed_at)) == "2025-09-03T09:02:00Z"
    assert issue.updated_at == max(issue.created_at, require(issue.closed_at))
    assert issue.comments[0].key == "i38c1"
    assert issue.comments[0].user_login == "mbeaulieu"
    assert issue.comments[0].id == number_for(
        SEED, "github", "comment", "ExampleCo/membership-ledger:i38c1"
    )
    assert repo.issue(999) is None
    parent = require(repo.issue(48))
    assert parent.sub_issue_numbers == (49,)
    assert require(repo.issue(49)).parent_number == 48
    assert parent.milestone_number == 3
    assert parent.updated_at >= parent.created_at


def test_a_pull_carries_head_base_and_review_material(state: GithubState) -> None:
    repo = _ledger(state)
    pull = require(repo.pull(39))
    assert pull.id == number_for(SEED, "github", "pull", "ExampleCo/membership-ledger#39")
    assert pull.head_ref == "ledger-view"
    assert pull.head_key == "c3"
    assert pull.base_ref == "main"
    assert pull.user_login == "jiwon-park"
    assert pull.merged and not pull.draft and pull.state == "closed"
    assert iso_seconds(require(pull.merged_at)) == "2025-06-30T14:02:00Z"
    assert pull.closed_at == pull.merged_at
    assert pull.updated_at == pull.merged_at
    assert pull.reviews[0].state == "APPROVED"
    assert pull.reviews[0].user_login == "nadia-okafor"
    assert pull.reviews[0].id == number_for(
        SEED, "github", "review", "ExampleCo/membership-ledger#39:0"
    )
    assert pull.review_comments[0].path == "internal/ledger/legacyview.go"
    assert pull.review_comments[0].line == 23
    assert pull.review_comments[0].diff_hunk == ""
    assert pull.comments[0].key == "p39c1"
    assert pull.check_runs[0].name == "ci / build"
    assert pull.check_runs[0].conclusion == "success"
    assert pull.statuses == ()
    assert repo.pull(999) is None


def test_optional_fields_take_their_documented_defaults(now: datetime) -> None:
    section = {
        "users": [{"login": "ann"}],
        "repos": [
            {
                "owner": "acme",
                "name": "widgets",
                "commits": [{"key": "c1", "message": "init", "author": "ann"}],
                "issues": [{"number": 1, "title": "first"}],
                "pulls": [
                    {
                        "number": 2,
                        "title": "open pr",
                        "head": {"ref": "topic", "sha": "c1"},
                        "user": "ann",
                        "statuses": [{"context": "ci", "state": "success"}],
                    }
                ],
            }
        ],
    }
    state = load(section, SEED, now)
    repo = require(state.repo("acme", "widgets"))
    assert repo.default_branch == "main"
    assert repo.description == ""
    assert repo.commits[0].date == now
    assert repo.commits[0].files == ()
    issue = require(repo.issue(1))
    assert issue.state == "open"
    assert issue.body == ""
    assert issue.created_at == now
    assert issue.closed_at is None
    assert issue.user_login == "ann"
    pull = require(repo.pull(2))
    assert pull.state == "open"
    assert pull.base_ref == "main"
    assert pull.merged is False
    assert pull.merged_at is None
    assert pull.closed_at is None
    assert pull.updated_at == now
    assert pull.statuses[0].context == "ci"
    assert pull.statuses[0].description == ""
    assert state.viewer.login == "ann"
    assert state.viewer.company == ""
    assert state.viewer.created_at == now


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda r: r["commits"][0].update(author="ghost"),
            "commit c1 names an unknown user: ghost",
        ),
        (lambda r: r["commits"][1].update(parents=["c0"]), "commit c2 names an unknown commit: c0"),
        (lambda r: r["branches"][0].update(head="c0"), "branch main names an unknown commit: c0"),
        (lambda r: r["tags"][0].update(commit="c0"), "tag v0.8.0 names an unknown commit: c0"),
        (
            lambda r: r["issues"][0].update(assignees=["ghost"]),
            "issue 38 names an unknown user: ghost",
        ),
        (lambda r: r["issues"][0].update(labels=["nope"]), "issue 38 names an unknown label: nope"),
        (lambda r: r["issues"][0].update(milestone=9), "issue 38 names an unknown milestone: 9"),
        (
            lambda r: r["issues"][0]["comments"][0].update(user="ghost"),
            "issue 38 names an unknown user: ghost",
        ),
        (lambda r: r["pulls"][0].update(user="ghost"), "pull 39 names an unknown user: ghost"),
        (lambda r: r["pulls"][0]["head"].update(sha="c0"), "pull 39 names an unknown commit: c0"),
        (lambda r: r["pulls"][0].update(labels=["nope"]), "pull 39 names an unknown label: nope"),
        (
            lambda r: r["pulls"][0]["reviews"][0].update(user="ghost"),
            "pull 39 names an unknown user: ghost",
        ),
    ],
)
def test_a_dangling_reference_is_refused_with_its_location(
    scenario: dict[str, Any], now: datetime, mutate: Any, message: str
) -> None:
    section = copy.deepcopy(scenario["github"])
    mutate(section["repos"][0])
    with pytest.raises(ScenarioError, match=re.escape(message)):
        load(section, SEED, now)


def test_the_id_map_names_every_opaque_identifier_by_its_human_key(state: GithubState) -> None:
    id_map = state.id_map()
    repo = _ledger(state)
    assert id_map["users"]["rhea-menon"] == state.viewer.id
    ledger = id_map["ExampleCo/membership-ledger"]
    assert ledger["commits"]["c1"] == repo.commits[0].sha
    assert ledger["issues"] == [38, 41, 43, 45, 48, 49, 50]
    assert ledger["pulls"] == [39, 40, 42, 44, 46, 47, 51]


def test_an_authored_updated_at_wins_over_the_derived_one(now: datetime) -> None:
    section = {
        "users": [{"login": "ann"}],
        "repos": [
            {
                "owner": "acme",
                "name": "widgets",
                "issues": [
                    {
                        "number": 1,
                        "title": "first",
                        "created_at": "2026-01-01T00:00:00Z",
                        "updated_at": "2026-01-02T00:00:00Z",
                        "closed_at": "2026-01-03T00:00:00Z",
                    }
                ],
            }
        ],
    }
    issue = require(require(load(section, SEED, now).repo("acme", "widgets")).issue(1))
    assert iso_seconds(issue.updated_at) == "2026-01-02T00:00:00Z"
