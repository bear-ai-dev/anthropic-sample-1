from __future__ import annotations

from typing import Any

from ..clock import iso_seconds
from .diff import changed_files, counts, patch_for
from .models_repo import Branch, Commit, FileChange, Release, Repo, Tag
from .render_issues import API
from .render_users import ref_for
from .state import GithubState

TEXT_PLAIN = "text/plain; charset=utf-8"
MIME_TYPES = {
    ".md": "text/markdown",
    ".json": "application/json",
    ".jsonl": "application/jsonl",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    ".sh": "application/x-sh",
    ".py": "text/x-python",
}


def mime_type(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    if "." not in name:
        return TEXT_PLAIN
    return MIME_TYPES.get(name[name.rfind(".") :], TEXT_PLAIN)


def commit(repo: Repo, item: Commit, state: GithubState) -> dict[str, Any]:
    author = state.user(item.author_login)
    return {
        "sha": item.sha,
        "commit": {
            "message": item.message,
            "author": {
                "name": item.author_login if author is None else author.name,
                "email": "" if author is None else author.email,
                "date": iso_seconds(item.date),
            },
        },
        "author": ref_for(state, item.author_login),
        "html_url": f"{repo.html_url}/commit/{item.sha}",
        "parents": [
            {"sha": parent.sha}
            for parent in (repo.commit_by_key(key) for key in item.parent_keys)
            if parent is not None
        ],
    }


def file_entry(change: FileChange, old: str | None) -> dict[str, Any]:
    patch = patch_for(old, change.content)
    additions, deletions = counts(patch)
    return {
        "sha": change.sha,
        "filename": change.path,
        "status": change.status,
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "patch": patch,
    }


def commit_with_files(repo: Repo, item: Commit, state: GithubState) -> dict[str, Any]:
    files = [file_entry(change, old) for change, old in changed_files(repo, item)]
    additions = sum(entry["additions"] for entry in files)
    deletions = sum(entry["deletions"] for entry in files)
    stats = {"additions": additions, "deletions": deletions, "total": additions + deletions}
    return dict(commit(repo, item, state), stats=stats, files=files)


def _commit_ref(repo: Repo, key: str) -> dict[str, Any]:
    found = repo.commit_by_key(key)
    sha = "" if found is None else found.sha
    return {"sha": sha, "url": f"{API}{repo.full_name}/commits/{sha}"}


def branch(repo: Repo, item: Branch) -> dict[str, Any]:
    return {
        "name": item.name,
        "commit": _commit_ref(repo, item.head_key),
        "protected": item.name == repo.default_branch,
    }


def tag(repo: Repo, item: Tag) -> dict[str, Any]:
    return {
        "name": item.name,
        "commit": _commit_ref(repo, item.commit_key),
        "zipball_url": f"{API}{repo.full_name}/zipball/refs/tags/{item.name}",
        "tarball_url": f"{API}{repo.full_name}/tarball/refs/tags/{item.name}",
    }


def release(repo: Repo, item: Release) -> dict[str, Any]:
    return {
        "id": item.id,
        "tag_name": item.tag,
        "name": item.name,
        "body": item.body,
        "draft": False,
        "prerelease": False,
        "created_at": iso_seconds(item.created_at),
        "published_at": iso_seconds(item.created_at),
        "html_url": f"{repo.html_url}/releases/tag/{item.tag}",
    }


def content_entry(change: FileChange) -> dict[str, Any]:
    return {
        "name": change.path.rsplit("/", 1)[-1],
        "path": change.path,
        "type": "file",
        "size": len((change.content or "").encode()),
        "sha": change.sha,
    }


def directory_entry(path: str) -> dict[str, Any]:
    return {"name": path.rsplit("/", 1)[-1], "path": path, "type": "dir", "size": 0, "sha": ""}


def code_item(repo: Repo, head: Commit, change: FileChange) -> dict[str, Any]:
    return {
        "name": change.path.rsplit("/", 1)[-1],
        "path": change.path,
        "sha": change.sha,
        "html_url": f"{repo.html_url}/blob/{head.sha}/{change.path}",
        "repository": {"id": repo.id, "full_name": repo.full_name, "html_url": repo.html_url},
    }
