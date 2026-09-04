import re
from datetime import datetime

from mockgithub.clock import iso_seconds
from mockgithub.github.load import load
from mockgithub.github.models_repo import Repo
from mockgithub.github.state import GithubState
from mockgithub.ids import hex_for, number_for
from mockgithub.tests.conftest import SEED
from mockgithub.tests.require import require

LEDGER = ("ExampleCo", "membership-ledger")


def _ledger(state: GithubState) -> Repo:
    return require(state.repo(*LEDGER))


def test_the_viewer_is_one_of_the_users_with_a_seeded_numeric_id(state: GithubState) -> None:
    assert state.viewer.login == "rhea-menon"
    assert state.viewer.name == "Rhea Menon"
    assert state.viewer.email == "rhea.menon@ExampleCo.example"
    assert state.viewer.id == number_for(SEED, "github", "user", "rhea-menon")
    assert state.user("RHEA-MENON") is state.viewer
    assert state.user("nobody") is None
    assert len(state.users) == 9


def test_a_scenario_without_a_viewer_still_has_one(now: datetime) -> None:
    state = load({}, SEED, now)
    assert state.viewer.login == ""
    assert state.repos == ()
    assert state.id_map() == {"users": {}}


def test_a_repository_is_found_by_owner_and_name_case_insensitively(state: GithubState) -> None:
    repo = _ledger(state)
    assert state.repo("ExampleCo", "Membership-Ledger") is repo
    assert state.repo("ExampleCo", "other") is None
    assert repo.full_name == "ExampleCo/membership-ledger"
    assert repo.html_url == "https://github.com/ExampleCo/membership-ledger"
    assert repo.default_branch == "main"
    assert repo.description.startswith("The membership ledger")
    assert repo.id == number_for(SEED, "github", "repository", "ExampleCo/membership-ledger")


def test_commit_shas_are_forty_hex_characters_derived_from_the_key(state: GithubState) -> None:
    repo = _ledger(state)
    first = repo.commits[0]
    assert first.key == "c1"
    assert first.sha == hex_for(SEED, "github", "commit", "ExampleCo/membership-ledger:c1", 40)
    assert re.fullmatch(r"[0-9a-f]{40}", first.sha)
    assert first.author_login == "tlindqvist"
    assert iso_seconds(first.date) == "2025-06-09T09:12:00Z"
    assert first.parent_keys == ()
    assert repo.commits[1].parent_keys == ("c1",)
    assert first.files[0].path == "README.md"
    assert first.files[0].status == "added"
    assert first.files[0].sha == hex_for(
        SEED, "github", "blob", "ExampleCo/membership-ledger:c1:README.md", 40
    )
    assert repo.commit(first.sha) is first
    assert repo.commit(first.sha[:7]) is first
    assert repo.commit("c1") is None
    assert repo.commit(first.sha[:3]) is None


def test_branches_tags_and_releases_point_at_commit_keys(state: GithubState) -> None:
    repo = _ledger(state)
    assert require(repo.branch("main")).head_key == "c15"
    assert repo.branch("nope") is None
    assert require(repo.tag("v0.8.0")).commit_key == "c8"
    assert repo.tag("v9") is None
    release = repo.releases[0]
    assert release.tag == "v0.8.0"
    assert release.name.startswith("0.8.0")
    assert release.id == number_for(SEED, "github", "release", "ExampleCo/membership-ledger:v0.8.0")
    assert iso_seconds(release.created_at) == "2025-09-03T16:20:00Z"


def test_labels_and_milestones_are_looked_up_by_name_and_number(state: GithubState) -> None:
    repo = _ledger(state)
    label = require(repo.label("area/migration"))
    assert label.color == "1d76db"
    assert label.description == "The migration orchestrator and its phases"
    assert label.id == number_for(
        SEED, "github", "label", "ExampleCo/membership-ledger:area/migration"
    )
    assert repo.label("nope") is None
    milestone = require(repo.milestone(2))
    assert milestone.title == "ap-2 archive"
    assert milestone.state == "closed"
    assert milestone.due_on is not None
    assert iso_seconds(milestone.due_on) == "2025-10-10T00:00:00Z"
    assert repo.milestone(9) is None
