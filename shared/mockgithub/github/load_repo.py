from __future__ import annotations

from typing import Any

from ..ids import hex_for
from .load_common import SERVICE, Context, commit_key_of, fail, optional_timestamp, timestamp
from .models_issues import Label, Milestone
from .models_repo import Branch, Commit, FileChange, Release, Tag

SHA_LENGTH = 40


def labels_of(raw: list[dict[str, Any]], context: Context) -> tuple[Label, ...]:
    return tuple(
        Label(
            id=context.number("label", f"{context.full_name}:{item['name']}"),
            name=str(item["name"]),
            color=str(item.get("color", "ededed")),
            description=str(item.get("description", "")),
        )
        for item in raw
    )


def milestones_of(raw: list[dict[str, Any]], context: Context) -> tuple[Milestone, ...]:
    return tuple(
        Milestone(
            id=context.number("milestone", f"{context.full_name}:{item['number']}"),
            number=int(item["number"]),
            title=str(item.get("title", "")),
            state=str(item.get("state", "open")),
            due_on=optional_timestamp(item, "due_on"),
        )
        for item in raw
    )


def _files(raw: list[dict[str, Any]], key: str, context: Context) -> tuple[FileChange, ...]:
    return tuple(
        FileChange(
            path=str(item["path"]),
            status=str(
                item.get("status", "added" if item.get("content") is not None else "removed")
            ),
            content=None if item.get("content") is None else str(item["content"]),
            sha=hex_for(
                context.seed,
                SERVICE,
                "blob",
                f"{context.full_name}:{key}:{item['path']}",
                SHA_LENGTH,
            ),
        )
        for item in raw
    )


def commits_of(raw: list[dict[str, Any]], context: Context) -> tuple[Commit, ...]:
    commits: list[Commit] = []
    for item in raw:
        key = str(item["key"])
        where = f"commit {key}"
        author = str(item.get("author", ""))
        if author not in context.logins:
            fail(where, "user", author)
        commits.append(
            Commit(
                key=key,
                sha=hex_for(
                    context.seed, SERVICE, "commit", f"{context.full_name}:{key}", SHA_LENGTH
                ),
                message=str(item.get("message", "")),
                author_login=author,
                date=timestamp(item, "date", context.clock),
                parent_keys=tuple(
                    commit_key_of(parent, context, where) for parent in item.get("parents", [])
                ),
                files=_files(item.get("files", []), key, context),
            )
        )
    return tuple(commits)


def branches_of(raw: list[dict[str, Any]], context: Context) -> tuple[Branch, ...]:
    return tuple(
        Branch(
            name=str(item["name"]),
            head_key=commit_key_of(item["head"], context, f"branch {item['name']}"),
        )
        for item in raw
    )


def tags_of(raw: list[dict[str, Any]], context: Context) -> tuple[Tag, ...]:
    return tuple(
        Tag(
            name=str(item["name"]),
            commit_key=commit_key_of(item["commit"], context, f"tag {item['name']}"),
        )
        for item in raw
    )


def releases_of(raw: list[dict[str, Any]], context: Context) -> tuple[Release, ...]:
    return tuple(
        Release(
            id=context.number("release", f"{context.full_name}:{item['tag']}"),
            tag=str(item["tag"]),
            name=str(item.get("name", item["tag"])),
            body=str(item.get("body", "")),
            created_at=timestamp(item, "created_at", context.clock),
        )
        for item in raw
    )
