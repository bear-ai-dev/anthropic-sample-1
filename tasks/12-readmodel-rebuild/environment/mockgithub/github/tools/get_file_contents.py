from __future__ import annotations

from typing import Any

from ...tool_errors import NotFound
from ...tool_result import ToolResult, resource_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import compact
from ..history import file_at, resolve_ref, tree_at
from ..lookup import REPO_SCHEMA, repo_of
from ..models_repo import Commit, Repo
from ..render_repo import content_entry, directory_entry, mime_type

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        **REPO_SCHEMA,
        "path": {
            "type": "string",
            "description": "Path to file/directory (directories must end with a slash '/')",
            "default": "/",
        },
        "ref": {
            "type": "string",
            "description": "Accepts optional git refs such as a branch or tag",
        },
        "sha": {"type": "string", "description": "Accepts optional commit SHA"},
    },
    "required": ["owner", "repo"],
}


def _missing(repo: Repo, arguments: dict[str, Any], path: str) -> NotFound:
    wanted = arguments.get("sha", arguments.get("ref"))
    suffix = "" if wanted is None else f"?ref={wanted}"
    return NotFound("contents", f"{repo.full_name}/contents/{path}{suffix}")


def _commit(repo: Repo, arguments: dict[str, Any], path: str) -> tuple[Commit, str]:
    sha, ref = arguments.get("sha"), arguments.get("ref")
    if sha is not None:
        commit = repo.commit(str(sha))
        if commit is None:
            raise _missing(repo, arguments, path)
        return commit, f"repo://{repo.full_name}/sha/{commit.sha}/contents/{path}"
    wanted = repo.default_branch if ref is None else str(ref)
    commit = resolve_ref(repo, wanted)
    if commit is None:
        raise _missing(repo, arguments, path)
    return commit, f"repo://{repo.full_name}/{_ref_label(repo, wanted, commit)}/contents/{path}"


def _ref_label(repo: Repo, wanted: str, commit: Commit) -> str:
    name = wanted.strip()
    if name.startswith("refs/"):
        return name
    if repo.branch(name) is not None:
        return f"refs/heads/{name}"
    if repo.tag(name) is not None:
        return f"refs/tags/{name}"
    return f"sha/{commit.sha}"


def _directory(repo: Repo, commit: Commit, path: str) -> ToolResult:
    prefix = "" if not path else path.rstrip("/") + "/"
    entries: dict[str, dict[str, Any]] = {}
    for change in tree_at(repo, commit):
        if not change.path.startswith(prefix):
            continue
        rest = change.path[len(prefix) :]
        if "/" in rest:
            child = prefix + rest.split("/", 1)[0]
            entries.setdefault(child, directory_entry(child))
        else:
            entries[change.path] = content_entry(change)
    return compact([entries[name] for name in sorted(entries)])


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    raw = str(arguments.get("path", "/"))
    path = raw.strip("/")
    commit, uri = _commit(repo, arguments, path)
    if raw.endswith("/") or raw == "":
        return _directory(repo, commit, path)
    change = file_at(repo, commit, path)
    if change is None:
        if any(item.path.startswith(path + "/") for item in tree_at(repo, commit)):
            return _directory(repo, commit, path)
        raise _missing(repo, arguments, path)
    return resource_result(
        f"successfully downloaded text file (SHA: {change.sha})",
        uri,
        mime_type(path),
        change.content or "",
    )


SPEC = ToolSpec(
    "get_file_contents",
    "Get the contents of a file or directory from a GitHub repository.",
    SCHEMA,
    handle,
)
