from __future__ import annotations

import difflib

from .history import file_at, parent_of
from .models_repo import Commit, FileChange, Repo

DEV_NULL = "/dev/null"


def _lines(text: str | None) -> list[str]:
    return [] if text is None else text.splitlines(keepends=True)


def patch_for(old: str | None, new: str | None) -> str:
    lines = list(difflib.unified_diff(_lines(old), _lines(new), "a", "b", lineterm="\n"))
    return "".join(lines[2:]).rstrip("\n")


def counts(patch: str) -> tuple[int, int]:
    additions = deletions = 0
    for line in patch.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return additions, deletions


def file_diff(path: str, status: str, old: str | None, new: str | None) -> str:
    header = [f"diff --git a/{path} b/{path}"]
    if status == "added":
        header.append("new file mode 100644")
    elif status == "removed":
        header.append("deleted file mode 100644")
    header.append(f"--- {DEV_NULL if old is None else 'a/' + path}")
    header.append(f"+++ {DEV_NULL if new is None else 'b/' + path}")
    return "\n".join([*header, patch_for(old, new)])


def changed_files(repo: Repo, commit: Commit) -> list[tuple[FileChange, str | None]]:
    parent = parent_of(repo, commit)
    changes: list[tuple[FileChange, str | None]] = []
    for change in commit.files:
        before = None if parent is None else file_at(repo, parent, change.path)
        changes.append((change, None if before is None else before.content))
    return changes


def commit_diff(repo: Repo, commit: Commit) -> str:
    return "\n".join(
        file_diff(change.path, change.status, old, change.content)
        for change, old in changed_files(repo, commit)
    )
