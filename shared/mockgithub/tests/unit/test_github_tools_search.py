from mockgithub.engine import Engine
from mockgithub.ids import hex_for, number_for
from mockgithub.tests.calls import call_error, call_json
from mockgithub.tests.conftest import SEED

LEDGER = "ExampleCo/membership-ledger"


def _sha(key: str) -> str:
    return hex_for(SEED, "github", "commit", f"{LEDGER}:{key}", 40)


def test_search_issues_only_returns_issues_in_the_rest_shape(engine: Engine) -> None:
    found = call_json(engine, "search_issues", {"query": "is:open"})
    assert list(found) == ["total_count", "incomplete_results", "items"]
    assert found["total_count"] == 3
    assert found["incomplete_results"] is False
    assert [item["number"] for item in found["items"]] == [50, 49, 48]
    assert all("pull_request" not in item for item in found["items"])
    assert found["items"][0]["html_url"] == f"https://github.com/{LEDGER}/issues/50"
    assert found["items"][0]["repository_url"] == f"https://api.github.com/repos/{LEDGER}"


def test_search_issues_understands_qualifiers_words_and_repo_scoping(engine: Engine) -> None:
    by_label = call_json(engine, "search_issues", {"query": "label:ap-2 is:closed"})
    assert [item["number"] for item in by_label["items"]] == [45]
    by_word = call_json(engine, "search_issues", {"query": "sqlite in:body"})
    assert [item["number"] for item in by_word["items"]] == [38]
    by_assignee = call_json(engine, "search_issues", {"query": "assignee:jiwon-park"})
    assert [item["number"] for item in by_assignee["items"]] == [43]
    scoped = call_json(
        engine,
        "search_issues",
        {"query": "is:open", "owner": "ExampleCo", "repo": "membership-ledger"},
    )
    assert scoped["total_count"] == 3
    elsewhere = call_json(
        engine, "search_issues", {"query": "is:open", "owner": "acme", "repo": "x"}
    )
    assert elsewhere == {"total_count": 0, "incomplete_results": False, "items": []}
    assert call_json(engine, "search_issues", {"query": "repo:acme/x"})["total_count"] == 0
    assert call_json(engine, "search_issues", {"query": "is:pr"})["total_count"] == 0


def test_search_issues_sorts_and_pages(engine: Engine) -> None:
    oldest = call_json(engine, "search_issues", {"query": "", "sort": "created", "order": "asc"})
    assert [item["number"] for item in oldest["items"]] == [38, 41, 43, 45, 48, 49, 50]
    busiest = call_json(engine, "search_issues", {"query": "", "sort": "comments"})
    assert busiest["items"][0]["number"] == 45
    updated = call_json(engine, "search_issues", {"query": "", "sort": "updated"})
    assert updated["items"][0]["number"] == 50
    page = call_json(engine, "search_issues", {"query": "", "perPage": 2, "page": 2})
    assert [item["number"] for item in page["items"]] == [48, 45]
    assert page["total_count"] == 7
    assert engine.journal.records()[-1]["page"] == {"page": 2, "perPage": 2, "hasNextPage": True}
    assert call_error(engine, "search_issues", {}) == "missing required parameter: query"
    assert call_error(engine, "search_issues", {"query": "", "order": "up"}) == (
        "parameter order must be one of asc, desc"
    )


def test_search_pull_requests_carries_the_pull_request_key(engine: Engine) -> None:
    merged = call_json(engine, "search_pull_requests", {"query": "is:merged author:jiwon-park"})
    assert [item["number"] for item in merged["items"]] == [44, 39]
    item = merged["items"][1]
    assert item["state"] == "closed"
    assert item["user"]["login"] == "jiwon-park"
    assert [label["name"] for label in item["labels"]] == ["area/api"]
    assert item["comments"] == 1
    assert item["closed_at"] == "2025-06-30T14:02:00Z"
    assert item["html_url"] == f"https://github.com/{LEDGER}/pull/39"
    assert item["pull_request"] == {
        "url": f"https://api.github.com/repos/{LEDGER}/pulls/39",
        "html_url": f"https://github.com/{LEDGER}/pull/39",
        "diff_url": f"https://github.com/{LEDGER}/pull/39.diff",
        "patch_url": f"https://github.com/{LEDGER}/pull/39.patch",
        "merged_at": "2025-06-30T14:02:00Z",
    }
    assert call_json(engine, "search_pull_requests", {"query": "is:issue"})["total_count"] == 0
    docs = call_json(engine, "search_pull_requests", {"query": "label:docs runbook in:title"})
    assert [item["number"] for item in docs["items"]] == [51]


def test_search_code_looks_through_the_default_branch_head(engine: Engine) -> None:
    found = call_json(engine, "search_code", {"query": "CUTOVER"})
    assert list(found) == ["total_count", "incomplete_results", "items"]
    assert found["total_count"] >= 1
    paths = [item["path"] for item in found["items"]]
    assert "internal/migration/phases.go" in paths
    first = found["items"][0]
    assert list(first) == ["name", "path", "sha", "html_url", "repository"]
    assert first["name"] == first["path"].rsplit("/", 1)[-1]
    assert first["html_url"] == f"https://github.com/{LEDGER}/blob/{_sha('c15')}/{first['path']}"
    assert first["repository"] == {
        "id": number_for(SEED, "github", "repository", LEDGER),
        "full_name": LEDGER,
        "html_url": f"https://github.com/{LEDGER}",
    }
    scoped = call_json(engine, "search_code", {"query": "path:docs/prior-cutover extension:json"})
    assert all(item["path"].startswith("docs/prior-cutover") for item in scoped["items"])
    assert all(item["path"].endswith(".json") for item in scoped["items"])
    named = call_json(engine, "search_code", {"query": "filename:smoke.sh repo:" + LEDGER})
    assert [item["path"] for item in named["items"]] == ["scripts/smoke.sh"]
    assert call_json(engine, "search_code", {"query": "repo:acme/x"})["total_count"] == 0
    page = call_json(engine, "search_code", {"query": "", "perPage": 5, "page": 2})
    assert len(page["items"]) == 5
    assert engine.journal.records()[-1]["page"] == {"page": 2, "perPage": 5, "hasNextPage": True}
    assert call_error(engine, "search_code", {}) == "missing required parameter: query"


def test_search_users_matches_login_name_and_email(engine: Engine) -> None:
    found = call_json(engine, "search_users", {"query": "rhea"})
    assert found["total_count"] == 1
    user_id = number_for(SEED, "github", "user", "rhea-menon")
    assert found["items"] == [
        {
            "login": "rhea-menon",
            "id": user_id,
            "html_url": "https://github.com/rhea-menon",
            "avatar_url": f"https://avatars.githubusercontent.com/u/{user_id}?v=4",
            "type": "User",
            "score": 1.0,
        }
    ]
    by_name = call_json(engine, "search_users", {"query": "Lindqvist"})
    assert [item["login"] for item in by_name["items"]] == ["tlindqvist"]
    by_email = call_json(engine, "search_users", {"query": "marc.beaulieu@ExampleCo.example"})
    assert [item["login"] for item in by_email["items"]] == ["mbeaulieu"]
    everyone = call_json(engine, "search_users", {"query": "type:user", "perPage": 4, "page": 3})
    assert [item["login"] for item in everyone["items"]] == ["ines-duarte"]
    assert everyone["total_count"] == 9
    assert call_json(engine, "search_users", {"query": "nobody"})["items"] == []
    assert call_error(engine, "search_users", {}) == "missing required parameter: query"


def test_search_code_skips_a_repository_without_a_resolvable_default_branch(
    engine: Engine,
) -> None:
    engine.reseed(
        {
            "version": 1,
            "clock": "2026-03-04T10:00:00Z",
            "github": {
                "users": [{"login": "ann"}],
                "repos": [{"owner": "acme", "name": "empty"}],
            },
        },
        None,
    )
    assert call_json(engine, "search_code", {"query": "anything"}) == {
        "total_count": 0,
        "incomplete_results": False,
        "items": [],
    }
