from datetime import datetime

from mockgithub.github.history import ancestry, file_at, parent_of, resolve_ref, tree_at
from mockgithub.github.load import load
from mockgithub.github.state import GithubState
from mockgithub.tests.conftest import SEED
from mockgithub.tests.require import require


def test_a_ref_resolves_through_branches_tags_and_sha_prefixes(state: GithubState) -> None:
    repo = require(state.repo("ExampleCo", "membership-ledger"))
    assert require(resolve_ref(repo, "main")).key == "c15"
    assert require(resolve_ref(repo, "refs/heads/main")).key == "c15"
    assert require(resolve_ref(repo, "ap2-cutover-archive")).key == "c10"
    assert require(resolve_ref(repo, "v0.8.0")).key == "c8"
    assert require(resolve_ref(repo, "refs/tags/v0.8.0")).key == "c8"
    sha = repo.commits[2].sha
    assert require(resolve_ref(repo, sha)).key == "c3"
    assert require(resolve_ref(repo, sha[:8])).key == "c3"
    assert resolve_ref(repo, "nope") is None
    assert resolve_ref(repo, "") is None


def test_ancestry_walks_parents_newest_first(state: GithubState) -> None:
    repo = require(state.repo("ExampleCo", "membership-ledger"))
    head = require(resolve_ref(repo, "v0.8.0"))
    assert [commit.key for commit in ancestry(repo, head)] == [
        "c8",
        "c7",
        "c6",
        "c5",
        "c4",
        "c3",
        "c2",
        "c1",
    ]
    assert require(parent_of(repo, head)).key == "c7"
    assert parent_of(repo, repo.commits[0]) is None


def test_a_merge_commit_reaches_both_parents_once(now: datetime) -> None:
    section = {
        "users": [{"login": "ann"}],
        "repos": [
            {
                "owner": "acme",
                "name": "widgets",
                "commits": [
                    {"key": "a", "message": "root", "author": "ann"},
                    {"key": "b", "message": "left", "author": "ann", "parents": ["a"]},
                    {"key": "c", "message": "right", "author": "ann", "parents": ["a"]},
                    {"key": "m", "message": "merge", "author": "ann", "parents": ["b", "c"]},
                ],
            }
        ],
    }
    repo = require(load(section, SEED, now).repo("acme", "widgets"))
    merge = require(repo.commit_by_key("m"))
    assert [commit.key for commit in ancestry(repo, merge)] == ["m", "b", "c", "a"]


def test_a_file_at_a_ref_is_its_newest_version_on_that_line_of_history(
    state: GithubState,
) -> None:
    repo = require(state.repo("ExampleCo", "membership-ledger"))
    at_head = require(file_at(repo, require(resolve_ref(repo, "main")), "README.md"))
    at_tag = require(file_at(repo, require(resolve_ref(repo, "v0.8.0")), "README.md"))
    assert at_head.content != at_tag.content
    assert at_head.sha != at_tag.sha
    assert at_tag.sha == repo.commits[0].files[0].sha
    assert file_at(repo, require(resolve_ref(repo, "v0.8.0")), "scripts/smoke.sh") is None
    assert file_at(repo, require(resolve_ref(repo, "main")), "nope.txt") is None


def test_a_removed_file_is_absent_afterwards_but_present_before(now: datetime) -> None:
    section = {
        "users": [{"login": "ann"}],
        "repos": [
            {
                "owner": "acme",
                "name": "widgets",
                "commits": [
                    {
                        "key": "a",
                        "message": "add",
                        "author": "ann",
                        "files": [
                            {"path": "keep.txt", "content": "k"},
                            {"path": "gone.txt", "content": "g"},
                            {"path": "docs/one.md", "content": "1"},
                        ],
                    },
                    {
                        "key": "b",
                        "message": "drop",
                        "author": "ann",
                        "parents": ["a"],
                        "files": [{"path": "gone.txt", "content": None}],
                    },
                ],
            }
        ],
    }
    repo = require(load(section, SEED, now).repo("acme", "widgets"))
    first, second = repo.commits
    assert require(file_at(repo, first, "gone.txt")).content == "g"
    assert file_at(repo, second, "gone.txt") is None
    assert second.files[0].status == "removed"
    assert [change.path for change in tree_at(repo, second)] == ["docs/one.md", "keep.txt"]
    assert [change.path for change in tree_at(repo, first)] == [
        "docs/one.md",
        "gone.txt",
        "keep.txt",
    ]
