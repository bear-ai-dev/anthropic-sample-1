from __future__ import annotations

from .models_repo import Commit, FileChange, Repo

HEADS = "refs/heads/"
TAGS = "refs/tags/"


def resolve_ref(repo: Repo, ref: str) -> Commit | None:
    name = ref.strip()
    if name.startswith(HEADS):
        name = name[len(HEADS) :]
    elif name.startswith(TAGS):
        name = name[len(TAGS) :]
    if not name:
        return None
    branch = repo.branch(name)
    if branch is not None:
        return repo.commit_by_key(branch.head_key)
    tag = repo.tag(name)
    if tag is not None:
        return repo.commit_by_key(tag.commit_key)
    return repo.commit(name)


def parent_of(repo: Repo, commit: Commit) -> Commit | None:
    if not commit.parent_keys:
        return None
    return repo.commit_by_key(commit.parent_keys[0])


def ancestry(repo: Repo, commit: Commit) -> list[Commit]:
    ordered: list[Commit] = []
    seen: set[str] = set()
    pending = [commit]
    while pending:
        current = pending.pop(0)
        if current.key in seen:
            continue
        seen.add(current.key)
        ordered.append(current)
        parents = [repo.commit_by_key(key) for key in current.parent_keys]
        pending.extend(parent for parent in parents if parent is not None)
    return ordered


def file_at(repo: Repo, commit: Commit, path: str) -> FileChange | None:
    for ancestor in ancestry(repo, commit):
        for change in ancestor.files:
            if change.path == path:
                return None if change.content is None else change
    return None


def tree_at(repo: Repo, commit: Commit) -> list[FileChange]:
    newest: dict[str, FileChange] = {}
    for ancestor in ancestry(repo, commit):
        for change in ancestor.files:
            newest.setdefault(change.path, change)
    return [newest[path] for path in sorted(newest) if newest[path].content is not None]
