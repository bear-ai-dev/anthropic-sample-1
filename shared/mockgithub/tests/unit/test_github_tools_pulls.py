from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for
from mockgithub.tests.calls import call, call_json
from mockgithub.tests.conftest import SEED

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
NOT_FOUND = "failed to get pull request: GET https://api.github.com/repos/ExampleCo/membership-ledger/"


def _sha(key: str) -> str:
    return hex_for(SEED, "github", "commit", f"ExampleCo/membership-ledger:{key}", 40)


def _pull(engine: Engine, number: int, method: str = "get", **extra: Any) -> Any:
    return call_json(
        engine, "pull_request_read", dict(LEDGER, method=method, pullNumber=number, **extra)
    )


def test_pull_request_read_get_is_the_rest_pull(engine: Engine) -> None:
    pull = _pull(engine, 39)
    assert list(pull) == [
        "number",
        "title",
        "body",
        "state",
        "draft",
        "merged",
        "merged_at",
        "head",
        "base",
        "user",
        "labels",
        "html_url",
        "created_at",
        "updated_at",
        "mergeable_state",
    ]
    assert pull["number"] == 39
    assert pull["state"] == "closed"
    assert pull["draft"] is False
    assert pull["merged"] is True
    assert pull["merged_at"] == "2025-06-30T14:02:00Z"
    assert pull["head"] == {"ref": "ledger-view", "sha": _sha("c3")}
    assert pull["base"] == {"ref": "main"}
    assert pull["user"]["login"] == "jiwon-park"
    assert [label["name"] for label in pull["labels"]] == ["area/api"]
    assert pull["html_url"] == "https://github.com/ExampleCo/membership-ledger/pull/39"
    assert pull["created_at"] == "2025-06-27T10:40:00Z"
    assert pull["updated_at"] == "2025-06-30T14:02:00Z"
    assert pull["mergeable_state"] == "unknown"


def test_pull_request_read_get_diff_is_the_head_commits_unified_diff(engine: Engine) -> None:
    result = call(engine, "pull_request_read", dict(LEDGER, method="get_diff", pullNumber=51))
    assert not result.is_error
    text = result.content[0]["text"]
    assert text.startswith(
        "diff --git a/docs/migration-runbook.md b/docs/migration-runbook.md\n"
        "--- a/docs/migration-runbook.md\n+++ b/docs/migration-runbook.md\n@@ "
    )
    assert "\n+" in text


def test_pull_request_read_get_status_combines_the_statuses(engine: Engine) -> None:
    status = _pull(engine, 39, "get_status")
    assert status == {"state": "pending", "statuses": [], "sha": _sha("c3"), "total_count": 0}


def test_pull_request_read_get_files_lists_the_head_commits_changes(engine: Engine) -> None:
    files = _pull(engine, 39, "get_files")
    assert [entry["filename"] for entry in files] == [
        "internal/ledger/view.go",
        "internal/ledger/legacyview.go",
    ]
    first = files[0]
    assert list(first) == [
        "sha",
        "filename",
        "status",
        "additions",
        "deletions",
        "changes",
        "patch",
    ]
    assert first["status"] == "added"
    assert first["deletions"] == 0
    assert first["additions"] == first["changes"] > 0
    assert first["patch"].startswith("@@ -0,0 +1,")
    assert first["sha"] == hex_for(
        SEED, "github", "blob", "ExampleCo/membership-ledger:c3:internal/ledger/view.go", 40
    )
    paged = _pull(engine, 39, "get_files", page=2, perPage=1)
    assert [entry["filename"] for entry in paged] == ["internal/ledger/legacyview.go"]


def test_pull_request_read_get_commits_are_the_commits_not_on_the_base(engine: Engine) -> None:
    commits = _pull(engine, 51, "get_commits")
    assert [commit["sha"] for commit in commits] == [_sha("c15")]
    assert commits[0]["commit"]["message"].startswith("docs: runbook")
    assert commits[0]["author"]["login"] == "ines-duarte"
    assert commits[0]["parents"] == [{"sha": _sha("c14")}]
