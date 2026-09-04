from __future__ import annotations

from typing import Any

from .load_common import (
    Context,
    comments_of,
    commit_key_of,
    labels_of,
    login_of,
    optional_timestamp,
    timestamp,
)
from .load_issues import updated_at
from .models_pulls import CheckRun, Pull, Review, ReviewComment, Status


def _reviews(
    raw: list[dict[str, Any]], context: Context, where: str, key: str
) -> tuple[Review, ...]:
    return tuple(
        Review(
            id=context.number("review", f"{key}:{index}"),
            user_login=login_of(item, "user", context, where) or "",
            state=str(item.get("state", "COMMENTED")),
            body=str(item.get("body", "")),
            submitted_at=timestamp(item, "submitted_at", context.clock),
        )
        for index, item in enumerate(raw)
    )


def _review_comments(
    raw: list[dict[str, Any]], context: Context, where: str, key: str
) -> tuple[ReviewComment, ...]:
    return tuple(
        ReviewComment(
            id=context.number("review_comment", f"{key}:{index}"),
            path=str(item.get("path", "")),
            line=int(item.get("line", 1)),
            body=str(item.get("body", "")),
            user_login=login_of(item, "user", context, where) or "",
            created_at=timestamp(item, "created_at", context.clock),
            diff_hunk=str(item.get("diff_hunk", "")),
        )
        for index, item in enumerate(raw)
    )


def _check_runs(raw: list[dict[str, Any]], context: Context, key: str) -> tuple[CheckRun, ...]:
    return tuple(
        CheckRun(
            id=context.number("check_run", f"{key}:{item.get('name', index)}"),
            name=str(item.get("name", "")),
            status=str(item.get("status", "completed")),
            conclusion=None if item.get("conclusion") is None else str(item["conclusion"]),
        )
        for index, item in enumerate(raw)
    )


def _statuses(raw: list[dict[str, Any]]) -> tuple[Status, ...]:
    return tuple(
        Status(
            context=str(item.get("context", "default")),
            state=str(item.get("state", "pending")),
            description=str(item.get("description", "")),
            target_url=None if item.get("target_url") is None else str(item["target_url"]),
        )
        for item in raw
    )


def pulls_of(raw: list[dict[str, Any]], context: Context, default_branch: str) -> tuple[Pull, ...]:
    pulls: list[Pull] = []
    for item in raw:
        number = int(item["number"])
        where = f"pull {number}"
        key = f"{context.full_name}#{number}"
        head = item.get("head", {})
        created = timestamp(item, "created_at", context.clock)
        merged_at = optional_timestamp(item, "merged_at")
        closed_at = optional_timestamp(item, "closed_at") or merged_at
        comments = comments_of(item.get("comments", []), context, where)
        reviews = _reviews(item.get("reviews", []), context, where, key)
        pulls.append(
            Pull(
                id=context.number("pull", key),
                number=number,
                title=str(item.get("title", "")),
                body=str(item.get("body", "")),
                state=str(item.get("state", "open")),
                merged=bool(item.get("merged", False)),
                draft=bool(item.get("draft", False)),
                head_ref=str(head.get("ref", "")),
                head_key=commit_key_of(head.get("sha", ""), context, where),
                base_ref=str(item.get("base", {}).get("ref", default_branch)),
                user_login=login_of(item, "user", context, where) or "",
                label_names=labels_of(item.get("labels", []), context, where),
                created_at=created,
                updated_at=updated_at(
                    item,
                    created,
                    comments,
                    merged_at,
                    closed_at,
                    *(r.submitted_at for r in reviews),
                ),
                merged_at=merged_at,
                closed_at=closed_at,
                reviews=reviews,
                review_comments=_review_comments(
                    item.get("review_comments", []), context, where, key
                ),
                comments=comments,
                check_runs=_check_runs(item.get("check_runs", []), context, key),
                statuses=_statuses(item.get("statuses", [])),
            )
        )
    return tuple(pulls)
