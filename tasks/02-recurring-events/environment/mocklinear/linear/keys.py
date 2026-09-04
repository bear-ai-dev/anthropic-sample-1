from __future__ import annotations

from .state import LinearState


def human_keys(state: LinearState) -> dict[str, set[str]]:
    return {
        "issue identifier": {issue.identifier for issue in state.issues},
        "user key": {user.key for user in state.users},
        "user email": {user.email for user in state.users if user.email},
        "user name": {user.name for user in state.users if user.name},
        "team key": {team.key for team in state.teams},
        "project key": {project.key for project in state.projects},
        "document key": {document.key for document in state.documents},
        "issue branch name": {issue.branch_name for issue in state.issues},
        "attachment key": {
            attachment.key for issue in state.issues for attachment in issue.attachments
        },
    }
