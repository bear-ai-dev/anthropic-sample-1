from __future__ import annotations

from datetime import datetime
from typing import Any

from .load_common import (
    Context,
    comments_of,
    fail,
    labels_of,
    login_of,
    logins_of,
    optional_timestamp,
    timestamp,
)
from .models_issues import Comment, Issue


def _milestone_number(raw: dict[str, Any], context: Context, where: str) -> int | None:
    value = raw.get("milestone")
    if value is None:
        return None
    number = int(value)
    if number not in context.milestone_numbers:
        fail(where, "milestone", number)
    return number


def latest(*moments: datetime | None) -> datetime:
    known = [moment for moment in moments if moment is not None]
    return max(known)


def updated_at(
    raw: dict[str, Any], created: datetime, comments: tuple[Comment, ...], *extra: datetime | None
) -> datetime:
    authored = optional_timestamp(raw, "updated_at")
    if authored is not None:
        return authored
    return latest(created, *extra, *(comment.created_at for comment in comments))


def issues_of(raw: list[dict[str, Any]], context: Context, viewer: str) -> tuple[Issue, ...]:
    issues: list[Issue] = []
    for item in raw:
        number = int(item["number"])
        where = f"issue {number}"
        created = timestamp(item, "created_at", context.clock)
        closed = optional_timestamp(item, "closed_at")
        comments = comments_of(item.get("comments", []), context, where)
        issues.append(
            Issue(
                id=context.number("issue", f"{context.full_name}#{number}"),
                number=number,
                title=str(item.get("title", "")),
                body=str(item.get("body", "")),
                state=str(item.get("state", "open")),
                user_login=login_of(item, "user", context, where) or viewer,
                label_names=labels_of(item.get("labels", []), context, where),
                assignee_logins=logins_of(item.get("assignees", []), context, where),
                milestone_number=_milestone_number(item, context, where),
                created_at=created,
                updated_at=updated_at(item, created, comments, closed),
                closed_at=closed,
                comments=comments,
                sub_issue_numbers=tuple(int(child) for child in item.get("sub_issues", [])),
                parent_number=None if item.get("parent") is None else int(item["parent"]),
            )
        )
    return tuple(issues)
