from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Organization:
    id: str
    name: str
    url_key: str


@dataclass(frozen=True)
class User:
    id: str
    key: str
    name: str
    display_name: str
    email: str
    active: bool


@dataclass(frozen=True)
class Label:
    id: str
    key: str
    name: str
    color: str
    team_key: str | None


@dataclass(frozen=True)
class WorkflowState:
    id: str
    key: str
    name: str
    type: str
    position: int
    color: str
    team_key: str


@dataclass(frozen=True)
class Cycle:
    id: str
    key: str
    number: int
    name: str
    starts_at: datetime
    ends_at: datetime
    team_key: str


@dataclass(frozen=True)
class Team:
    id: str
    key: str
    name: str
    description: str
    member_keys: tuple[str, ...]
    states: tuple[WorkflowState, ...]
    cycles: tuple[Cycle, ...]


@dataclass(frozen=True)
class Milestone:
    id: str
    key: str
    name: str
    target_date: str | None
    project_key: str


@dataclass(frozen=True)
class Project:
    id: str
    key: str
    name: str
    description: str
    state: str
    lead_key: str | None
    team_keys: tuple[str, ...]
    start_date: str | None
    target_date: str | None
    created_at: datetime
    updated_at: datetime
    label_keys: tuple[str, ...]
    milestones: tuple[Milestone, ...]


@dataclass(frozen=True)
class Document:
    id: str
    key: str
    title: str
    content: str
    project_key: str | None
    issue_identifier: str | None
    creator_key: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Attachment:
    id: str
    key: str
    title: str
    subtitle: str
    url: str
    issue_identifier: str


@dataclass(frozen=True)
class Comment:
    id: str
    key: str
    body: str
    user_key: str
    created_at: datetime
    parent_key: str | None
    issue_identifier: str


@dataclass(frozen=True)
class Issue:
    id: str
    identifier: str
    title: str
    description: str
    team_key: str
    state_key: str
    assignee_key: str | None
    creator_key: str
    priority: int
    estimate: int | None
    label_keys: tuple[str, ...]
    project_key: str | None
    milestone_key: str | None
    cycle_key: str | None
    parent_identifier: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    canceled_at: datetime | None
    due_date: str | None
    branch_name: str
    attachments: tuple[Attachment, ...]
    comments: tuple[Comment, ...]
