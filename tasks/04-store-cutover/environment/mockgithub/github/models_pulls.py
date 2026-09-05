from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models_issues import Comment


@dataclass(frozen=True)
class Review:
    id: int
    user_login: str
    state: str
    body: str
    submitted_at: datetime


@dataclass(frozen=True)
class ReviewComment:
    id: int
    path: str
    line: int
    body: str
    user_login: str
    created_at: datetime
    diff_hunk: str


@dataclass(frozen=True)
class CheckRun:
    id: int
    name: str
    status: str
    conclusion: str | None


@dataclass(frozen=True)
class Status:
    context: str
    state: str
    description: str
    target_url: str | None


@dataclass(frozen=True)
class Pull:
    id: int
    number: int
    title: str
    body: str
    state: str
    merged: bool
    draft: bool
    head_ref: str
    head_key: str
    base_ref: str
    user_login: str
    label_names: tuple[str, ...]
    created_at: datetime
    updated_at: datetime
    merged_at: datetime | None
    closed_at: datetime | None
    reviews: tuple[Review, ...]
    review_comments: tuple[ReviewComment, ...]
    comments: tuple[Comment, ...]
    check_runs: tuple[CheckRun, ...]
    statuses: tuple[Status, ...]
