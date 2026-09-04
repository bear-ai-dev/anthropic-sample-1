from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for, number_for
from mockgithub.tests.calls import call, call_error, call_json
from mockgithub.tests.conftest import SEED

LEDGER = {"owner": "ExampleCo", "repo": "membership-ledger"}
API = "https://api.github.com/repos/ExampleCo/membership-ledger"


def _sha(key: str) -> str:
    return hex_for(SEED, "github", "commit", f"ExampleCo/membership-ledger:{key}", 40)


def _blob(key: str, path: str) -> str:
    return hex_for(SEED, "github", "blob", f"ExampleCo/membership-ledger:{key}:{path}", 40)


def _contents(engine: Engine, **args: Any) -> Any:
    return call(engine, "get_file_contents", dict(LEDGER, **args))


def test_list_commits_walks_the_default_branch_newest_first(engine: Engine) -> None:
    commits = call_json(engine, "list_commits", LEDGER)
    assert [commit["sha"] for commit in commits] == [_sha(f"c{n}") for n in range(15, 0, -1)]
    latest = commits[0]
    assert list(latest) == ["sha", "commit", "author", "html_url", "parents"]
    assert latest["commit"] == {
        "message": latest["commit"]["message"],
        "author": {
            "name": "Ines Duarte",
            "email": "ines.duarte@ExampleCo.example",
            "date": "2026-02-10T11:15:00Z",
        },
    }
    assert latest["author"]["login"] == "ines-duarte"
    assert latest["author"]["id"] == number_for(SEED, "github", "user", "ines-duarte")
    assert latest["html_url"] == f"https://github.com/ExampleCo/membership-ledger/commit/{_sha('c15')}"
    assert latest["parents"] == [{"sha": _sha("c14")}]
    assert commits[-1]["parents"] == []


def test_list_commits_filters_by_ref_path_author_and_dates(engine: Engine) -> None:
    tagged = call_json(engine, "list_commits", dict(LEDGER, sha="v0.8.0"))
    assert [commit["sha"] for commit in tagged] == [_sha(f"c{n}") for n in range(8, 0, -1)]
    by_sha = call_json(engine, "list_commits", dict(LEDGER, sha=_sha("c2")[:10]))
    assert [commit["sha"] for commit in by_sha] == [_sha("c2"), _sha("c1")]
    readme = call_json(engine, "list_commits", dict(LEDGER, path="README.md"))
    assert [commit["sha"] for commit in readme] == [_sha("c13"), _sha("c1")]
    nadia = call_json(engine, "list_commits", dict(LEDGER, author="nadia-okafor"))
    assert [commit["sha"] for commit in nadia] == [_sha("c9"), _sha("c6"), _sha("c4")]
    window = call_json(
        engine,
        "list_commits",
        dict(LEDGER, since="2025-09-01T00:00:00Z", until="2025-10-31T00:00:00Z"),
    )
    assert [commit["sha"] for commit in window] == [_sha(f"c{n}") for n in (12, 11, 10, 9, 8)]
    page = call_json(engine, "list_commits", dict(LEDGER, perPage=4, page=2))
    assert [commit["sha"] for commit in page] == [_sha(f"c{n}") for n in (11, 10, 9, 8)]
    assert engine.journal.records()[-1]["page"] == {"page": 2, "perPage": 4, "hasNextPage": True}
    assert call_error(engine, "list_commits", dict(LEDGER, sha="nope")) == (
        f"failed to list commits: GET {API}/commits?sha=nope: 404 Not Found []"
    )
    assert call_error(engine, "list_commits", dict(LEDGER, since="never")) == (
        "not a timestamp: never"
    )


def test_get_commit_summary_diff_and_raw(engine: Engine) -> None:
    summary = call_json(engine, "get_commit", dict(LEDGER, sha=_sha("c13")))
    assert list(summary) == ["sha", "commit", "author", "html_url", "parents"]
    assert summary["sha"] == _sha("c13")
    detailed = call_json(engine, "get_commit", dict(LEDGER, sha=_sha("c13")[:8], detail="diff"))
    assert list(detailed) == ["sha", "commit", "author", "html_url", "parents", "stats", "files"]
    assert detailed["files"][0]["filename"] == "README.md"
    assert detailed["files"][0]["status"] == "modified"
    assert detailed["files"][0]["patch"].startswith("@@ ")
    assert detailed["stats"] == {
        "additions": detailed["files"][0]["additions"],
        "deletions": detailed["files"][0]["deletions"],
        "total": detailed["files"][0]["changes"],
    }
    tagged = call_json(engine, "get_commit", dict(LEDGER, sha="v0.8.0"))
    assert tagged["sha"] == _sha("c8")
    branch = call_json(engine, "get_commit", dict(LEDGER, sha="ap2-cutover-archive"))
    assert branch["sha"] == _sha("c10")
    raw = call(engine, "get_commit", dict(LEDGER, sha=_sha("c13"), detail="raw"))
    assert raw.content[0]["text"].startswith("diff --git a/README.md b/README.md\n")
    assert call_error(engine, "get_commit", dict(LEDGER, sha="0000")) == (
        f"failed to get commit: GET {API}/commits/0000: 404 Not Found []"
    )
    assert call_error(engine, "get_commit", LEDGER) == "missing required parameter: sha"
    assert call_error(engine, "get_commit", dict(LEDGER, sha=_sha("c13"), detail="full")) == (
        "parameter detail must be one of summary, diff, raw"
    )


def test_branches_tags_and_releases_are_rest_lists(engine: Engine) -> None:
    branches = call_json(engine, "list_branches", LEDGER)
    assert branches == [
        {
            "name": "main",
            "commit": {"sha": _sha("c15"), "url": f"{API}/commits/{_sha('c15')}"},
            "protected": True,
        },
        {
            "name": "ap2-cutover-archive",
            "commit": {"sha": _sha("c10"), "url": f"{API}/commits/{_sha('c10')}"},
            "protected": False,
        },
    ]
    tags = call_json(engine, "list_tags", LEDGER)
    assert tags == [
        {
            "name": "v0.8.0",
            "commit": {"sha": _sha("c8"), "url": f"{API}/commits/{_sha('c8')}"},
            "zipball_url": f"{API}/zipball/refs/tags/v0.8.0",
            "tarball_url": f"{API}/tarball/refs/tags/v0.8.0",
        }
    ]
    releases = call_json(engine, "list_releases", LEDGER)
    assert len(releases) == 1
    release = releases[0]
    assert release["id"] == number_for(SEED, "github", "release", "ExampleCo/membership-ledger:v0.8.0")
    assert release["tag_name"] == "v0.8.0"
    assert release["name"].startswith("0.8.0")
    assert release["body"].startswith("What is in this one")
    assert release["draft"] is False and release["prerelease"] is False
    assert release["created_at"] == release["published_at"] == "2025-09-03T16:20:00Z"
    assert release["html_url"] == "https://github.com/ExampleCo/membership-ledger/releases/tag/v0.8.0"
    assert call_json(engine, "list_branches", dict(LEDGER, page=2)) == []
    assert call_json(engine, "list_tags", dict(LEDGER, perPage=1, page=2)) == []
    assert call_json(engine, "list_releases", dict(LEDGER, page=3)) == []
    for tool, op in (
        ("list_branches", "list branches"),
        ("list_tags", "list tags"),
        ("list_releases", "list releases"),
    ):
        assert call_error(engine, tool, {"owner": "acme", "repo": "nope"}) == (
            f"failed to {op}: GET https://api.github.com/repos/acme/nope: 404 Not Found []"
        )
