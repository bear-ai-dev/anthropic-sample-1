from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: int
    login: str
    name: str
    email: str
    company: str
    location: str
    bio: str
    created_at: datetime


@dataclass(frozen=True)
class Label:
    id: int
    name: str
    color: str
    description: str


@dataclass(frozen=True)
class Milestone:
    id: int
    number: int
    title: str
    state: str
    due_on: datetime | None


@dataclass(frozen=True)
class Comment:
    id: int
    key: str
    user_login: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Issue:
    id: int
    number: int
    title: str
    body: str
    state: str
    user_login: str
    label_names: tuple[str, ...]
    assignee_logins: tuple[str, ...]
    milestone_number: int | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
    comments: tuple[Comment, ...]
    sub_issue_numbers: tuple[int, ...]
    parent_number: int | None
