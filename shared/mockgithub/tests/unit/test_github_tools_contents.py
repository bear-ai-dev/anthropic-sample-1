from typing import Any

from mockgithub.engine import Engine
from mockgithub.ids import hex_for
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


def test_get_file_contents_returns_a_file_as_an_embedded_resource(engine: Engine) -> None:
    result = _contents(engine, path="README.md")
    assert not result.is_error
    text, resource = result.content
    assert text == {
        "type": "text",
        "text": f"successfully downloaded text file (SHA: {_blob('c13', 'README.md')})",
    }
    assert resource["type"] == "resource"
    assert resource["resource"]["uri"] == (
        "repo://ExampleCo/membership-ledger/refs/heads/main/contents/README.md"
    )
    assert resource["resource"]["mimeType"] == "text/markdown"
    assert resource["resource"]["text"].startswith("# membership-ledger\n")
    assert result.page is None


def test_get_file_contents_honours_a_branch_a_tag_and_a_sha(engine: Engine) -> None:
    at_tag = _contents(engine, path="README.md", ref="v0.8.0")
    assert at_tag.content[0]["text"].endswith(f"(SHA: {_blob('c1', 'README.md')})")
    assert at_tag.content[1]["resource"]["uri"] == (
        "repo://ExampleCo/membership-ledger/refs/tags/v0.8.0/contents/README.md"
    )
    at_branch = _contents(engine, path="docs/prior-cutover/MANIFEST.md", ref="ap2-cutover-archive")
    assert at_branch.content[0]["text"].endswith(
        f"(SHA: {_blob('c10', 'docs/prior-cutover/MANIFEST.md')})"
    )
    assert at_branch.content[1]["resource"]["uri"] == (
        "repo://ExampleCo/membership-ledger/refs/heads/ap2-cutover-archive"
        "/contents/docs/prior-cutover/MANIFEST.md"
    )
    at_sha = _contents(engine, path="README.md", sha=_sha("c2"))
    assert at_sha.content[0]["text"].endswith(f"(SHA: {_blob('c1', 'README.md')})")
    assert at_sha.content[1]["resource"]["uri"] == (
        f"repo://ExampleCo/membership-ledger/sha/{_sha('c2')}/contents/README.md"
    )
    assert (
        _contents(engine, path="/README.md")
        .content[1]["resource"]["uri"]
        .endswith("/contents/README.md")
    )


def test_get_file_contents_labels_the_resource_uri_by_ref_kind(engine: Engine) -> None:
    def uri(**args: Any) -> str:
        result = _contents(engine, path="README.md", **args)
        assert not result.is_error
        return str(result.content[1]["resource"]["uri"])

    base = "repo://ExampleCo/membership-ledger/"
    assert uri(ref="refs/heads/main") == base + "refs/heads/main/contents/README.md"
    assert uri(ref="refs/tags/v0.8.0") == base + "refs/tags/v0.8.0/contents/README.md"
    assert uri(ref="v0.8.0") == base + "refs/tags/v0.8.0/contents/README.md"
    assert uri(ref=" main ") == base + "refs/heads/main/contents/README.md"
    assert uri(ref=_sha("c2")[:12]) == base + f"sha/{_sha('c2')}/contents/README.md"
    assert uri(ref=_sha("c2")) == base + f"sha/{_sha('c2')}/contents/README.md"


def test_get_file_contents_lists_a_directory_as_compact_json(engine: Engine) -> None:
    root = call_json(engine, "get_file_contents", LEDGER)
    assert [entry["name"] for entry in root] == [
        ".github",
        "README.md",
        "config",
        "docs",
        "internal",
        "scripts",
    ]
    assert root[0] == {"name": ".github", "path": ".github", "type": "dir", "size": 0, "sha": ""}
    readme = root[1]
    assert readme["type"] == "file"
    assert readme["path"] == "README.md"
    assert readme["size"] > 0
    assert readme["sha"] == _blob("c13", "README.md")
    docs = call_json(engine, "get_file_contents", dict(LEDGER, path="docs/"))
    assert [entry["path"] for entry in docs] == ["docs/migration-runbook.md", "docs/prior-cutover"]
    assert call_error(engine, "get_file_contents", dict(LEDGER, path="docs", ref="v0.8.0")) == (
        f"failed to get file contents: GET {API}/contents/docs?ref=v0.8.0: 404 Not Found []"
    )
    slash = call_json(engine, "get_file_contents", dict(LEDGER, path="/"))
    assert slash == root
    assert call_json(engine, "get_file_contents", dict(LEDGER, path="docs")) == docs


def test_get_file_contents_mime_types_follow_the_extension(engine: Engine) -> None:
    yaml = _contents(engine, path="config/migration.yaml")
    assert yaml.content[1]["resource"]["mimeType"] == "application/yaml"
    go = _contents(engine, path="internal/ledger/view.go")
    assert go.content[1]["resource"]["mimeType"] == "text/plain; charset=utf-8"
    shell = _contents(engine, path="scripts/smoke.sh")
    assert shell.content[1]["resource"]["mimeType"] == "application/x-sh"
    manifest = _contents(engine, path="docs/prior-cutover/member-book.json")
    assert manifest.content[1]["resource"]["mimeType"] == "application/json"
    lines = _contents(engine, path="docs/prior-cutover/ledger-export.jsonl")
    assert lines.content[1]["resource"]["mimeType"] == "application/jsonl"
    workflow = _contents(engine, path=".github/workflows/ci.yml")
    assert workflow.content[1]["resource"]["mimeType"] == "application/yaml"


def test_get_file_contents_not_found_names_the_path_that_was_asked_for(engine: Engine) -> None:
    prefix = "failed to get file contents: GET " + API
    assert call_error(engine, "get_file_contents", dict(LEDGER, path="nope.txt")) == (
        prefix + "/contents/nope.txt: 404 Not Found []"
    )
    assert call_error(engine, "get_file_contents", dict(LEDGER, path="README.md", ref="v9")) == (
        prefix + "/contents/README.md?ref=v9: 404 Not Found []"
    )
    assert call_error(engine, "get_file_contents", dict(LEDGER, path="README.md", sha="abcd")) == (
        prefix + "/contents/README.md?ref=abcd: 404 Not Found []"
    )
    assert call_error(engine, "get_file_contents", {"owner": "acme", "repo": "nope"}) == (
        "failed to get file contents: GET https://api.github.com/repos/acme/nope: 404 Not Found []"
    )
    assert call_error(
        engine, "get_file_contents", dict(LEDGER, path="scripts/smoke.sh", ref="v0.8.0")
    ) == (prefix + "/contents/scripts/smoke.sh?ref=v0.8.0: 404 Not Found []")
