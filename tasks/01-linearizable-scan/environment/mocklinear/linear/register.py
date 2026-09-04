from __future__ import annotations

from ..tool_spec import ToolSpec
from .tools import (
    get_attachment,
    get_document,
    get_issue,
    get_issue_status,
    get_milestone,
    get_project,
    get_team,
    get_user,
    list_comments,
    list_cycles,
    list_documents,
    list_issue_labels,
    list_issue_statuses,
    list_issues,
    list_milestones,
    list_project_labels,
    list_projects,
    list_teams,
    list_users,
    search_documentation,
)

MODULES = (
    get_attachment,
    get_document,
    get_issue,
    get_issue_status,
    get_milestone,
    get_project,
    get_team,
    get_user,
    list_comments,
    list_cycles,
    list_documents,
    list_issue_labels,
    list_issue_statuses,
    list_issues,
    list_milestones,
    list_project_labels,
    list_projects,
    list_teams,
    list_users,
    search_documentation,
)


def specs() -> list[ToolSpec]:
    return [module.SPEC for module in MODULES]
