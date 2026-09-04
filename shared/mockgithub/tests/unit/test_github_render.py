import json

from mockgithub.engine import Engine
from mockgithub.github.envelope import compact
from mockgithub.github.render_repo import mime_type
from mockgithub.github.render_users import user_ref
from mockgithub.github.state import GithubState
from mockgithub.registry import build_registries
from mockgithub.tests.calls import call
from mockgithub.tests.require import require


def test_compact_json_has_no_whitespace_and_keeps_key_order() -> None:
    result = compact({"b": [1, 2], "a": {"z": None, "y": "ü"}}, page={"page": 1})
    assert result.content[0]["text"] == '{"b":[1,2],"a":{"z":null,"y":"ü"}}'
    assert result.page == {"page": 1}
    assert not result.is_error
    assert json.loads(result.content[0]["text"])["a"]["y"] == "ü"


def test_a_user_reference_falls_back_to_a_bare_login(state: GithubState) -> None:
    known = user_ref(require(state.user("rhea-menon")), "rhea-menon")
    assert known["login"] == "rhea-menon"
    assert known["id"] == state.viewer.id
    ghost = user_ref(None, "ghost")
    assert ghost == {
        "login": "ghost",
        "id": 0,
        "html_url": "https://github.com/ghost",
        "avatar_url": "https://avatars.githubusercontent.com/u/0?v=4",
    }


def test_mime_types_come_from_a_fixed_table() -> None:
    assert mime_type("README.md") == "text/markdown"
    assert mime_type("a/b.JSON") == "application/json"
    assert mime_type("x.py") == "text/x-python"
    assert mime_type("Makefile") == "text/plain; charset=utf-8"
    assert mime_type("x.toml") == "application/toml"


def test_the_registry_exposes_the_sixteen_read_only_tools(engine: Engine) -> None:
    names = [tool["name"] for tool in engine.tools("github")]
    assert names == sorted(
        [
            "get_me",
            "issue_read",
            "list_issues",
            "search_issues",
            "get_label",
            "pull_request_read",
            "list_pull_requests",
            "search_pull_requests",
            "get_file_contents",
            "list_commits",
            "get_commit",
            "search_code",
            "list_branches",
            "list_tags",
            "list_releases",
            "search_users",
        ]
    )
    descriptors = build_registries()["github"].descriptors()
    for descriptor in descriptors:
        assert descriptor["description"]
        assert descriptor["inputSchema"]["type"] == "object"
        for name, spec in descriptor["inputSchema"]["properties"].items():
            assert spec["type"] in ("string", "integer", "array"), (descriptor["name"], name)


def test_every_tool_result_is_one_compact_text_block_or_a_resource(engine: Engine) -> None:
    ledger = {"owner": "ExampleCo", "repo": "membership-ledger"}
    for tool, args in (
        ("get_me", {}),
        ("list_issues", ledger),
        ("list_pull_requests", dict(ledger, state="all")),
        ("search_users", {"query": "a"}),
        ("list_branches", ledger),
    ):
        result = call(engine, tool, args)
        assert len(result.content) == 1
        assert result.content[0]["type"] == "text"
        assert "\n" not in result.content[0]["text"]
