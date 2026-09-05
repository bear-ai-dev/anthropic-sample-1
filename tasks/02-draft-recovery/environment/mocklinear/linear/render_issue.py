from __future__ import annotations

from typing import Any

from .models import Attachment, Comment, Issue
from .render import (
    _ts,
    _url,
    issue_id,
    issue_ref,
    labels_json,
    status_by_key,
    status_ref,
    team_ref,
    user_ref,
)
from .render_project import cycle_ref, milestone_ref, project_ref
from .state import LinearState

PRIORITY_LABELS = ("No priority", "Urgent", "High", "Medium", "Low")


def priority_label(priority: int) -> str:
    return PRIORITY_LABELS[priority] if 0 <= priority < len(PRIORITY_LABELS) else "No priority"


def attachment_ref(attachment: Attachment) -> dict[str, Any]:
    return {
        "id": attachment.id,
        "title": attachment.title,
        "subtitle": attachment.subtitle,
        "url": attachment.url,
    }


def attachment_json(state: LinearState, attachment: Attachment) -> dict[str, Any]:
    payload = attachment_ref(attachment)
    payload["issue"] = issue_ref(state, attachment.issue_identifier)
    return payload


def comment_json(state: LinearState, comment: Comment) -> dict[str, Any]:
    parent = next(
        (
            item
            for issue in state.issues
            for item in issue.comments
            if item.key == comment.parent_key
        ),
        None,
    )
    return {
        "id": comment.id,
        "body": comment.body,
        "user": user_ref(state, comment.user_key),
        "createdAt": _ts(comment.created_at),
        "parentId": None if parent is None else parent.id,
        "issueId": issue_id(state, comment.issue_identifier),
    }


def issue_json(state: LinearState, issue: Issue, *, detail: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": issue.id,
        "identifier": issue.identifier,
        "title": issue.title,
        "description": issue.description,
        "priority": issue.priority,
        "priorityLabel": priority_label(issue.priority),
        "estimate": issue.estimate,
        "url": _url(state, "issue", issue.identifier),
        "state": status_ref(status_by_key(state, issue.state_key)),
        "team": team_ref(state.team(issue.team_key)),
        "assignee": user_ref(state, issue.assignee_key),
        "creator": user_ref(state, issue.creator_key),
        "labels": labels_json(state, issue.label_keys),
        "project": project_ref(state, issue.project_key),
        "projectMilestone": milestone_ref(state, issue.milestone_key),
        "cycle": cycle_ref(state, issue.cycle_key),
        "parent": issue_ref(state, issue.parent_identifier),
        "createdAt": _ts(issue.created_at),
        "updatedAt": _ts(issue.updated_at),
        "startedAt": _ts(issue.started_at),
        "completedAt": _ts(issue.completed_at),
        "canceledAt": _ts(issue.canceled_at),
        "dueDate": issue.due_date,
        "branchName": issue.branch_name,
        "commentCount": len(issue.comments),
    }
    if detail:
        payload["attachments"] = [attachment_ref(item) for item in issue.attachments]
    return payload
