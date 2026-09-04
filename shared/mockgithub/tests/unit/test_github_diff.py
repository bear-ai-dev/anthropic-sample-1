from datetime import datetime

from mockgithub.github.diff import changed_files, commit_diff, counts, file_diff, patch_for
from mockgithub.github.load import load
from mockgithub.github.state import GithubState
from mockgithub.tests.conftest import SEED
from mockgithub.tests.require import require


def test_a_patch_is_the_hunks_of_a_unified_diff_without_file_headers() -> None:
    patch = patch_for("a\nb\nc\n", "a\nB\nc\nd\n")
    assert patch == "@@ -1,3 +1,4 @@\n a\n-b\n+B\n c\n+d"
    assert counts(patch) == (2, 1)


def test_a_new_or_removed_file_diffs_against_nothing() -> None:
    assert patch_for(None, "x\ny\n") == "@@ -0,0 +1,2 @@\n+x\n+y"
    assert patch_for("x\n", None) == "@@ -1 +0,0 @@\n-x"
    assert patch_for(None, None) == ""
    assert patch_for("same\n", "same\n") == ""
    assert counts("") == (0, 0)


def test_a_file_diff_carries_git_style_headers() -> None:
    added = file_diff("docs/a.md", "added", None, "hi\n")
    assert added == (
        "diff --git a/docs/a.md b/docs/a.md\nnew file mode 100644\n--- /dev/null\n+++ b/docs/a.md\n"
        "@@ -0,0 +1 @@\n+hi"
    )
    removed = file_diff("docs/a.md", "removed", "hi\n", None)
    assert removed.startswith("diff --git a/docs/a.md b/docs/a.md\ndeleted file mode 100644\n")
    assert "--- a/docs/a.md\n+++ /dev/null\n" in removed
    modified = file_diff("docs/a.md", "modified", "hi\n", "ho\n")
    assert modified == (
        "diff --git a/docs/a.md b/docs/a.md\n--- a/docs/a.md\n+++ b/docs/a.md\n"
        "@@ -1 +1 @@\n-hi\n+ho"
    )


def test_a_commit_diffs_its_files_against_the_first_parent(
    state: GithubState, now: datetime
) -> None:
    repo = require(state.repo("ExampleCo", "membership-ledger"))
    readme_rewrite = require(repo.commit_by_key("c13"))
    changes = changed_files(repo, readme_rewrite)
    assert [change.path for change, _ in changes] == ["README.md"]
    assert changes[0][1] == repo.commits[0].files[0].content
    text = commit_diff(repo, readme_rewrite)
    assert text.startswith("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n")
    assert "\n-" in text and "\n+" in text
    root = repo.commits[0]
    assert changed_files(repo, root)[0][1] is None
    assert commit_diff(repo, root).startswith("diff --git a/README.md b/README.md\nnew file mode")
    section = {
        "users": [{"login": "ann"}],
        "repos": [
            {
                "owner": "acme",
                "name": "widgets",
                "commits": [{"key": "a", "message": "empty", "author": "ann"}],
            }
        ],
    }
    empty = require(load(section, SEED, now).repo("acme", "widgets"))
    assert commit_diff(empty, empty.commits[0]) == ""
