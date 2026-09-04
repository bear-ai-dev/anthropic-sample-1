from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import (
    Attachment,
    Cycle,
    Document,
    Issue,
    Label,
    Milestone,
    Organization,
    Project,
    Team,
    User,
    WorkflowState,
)


def _same(value: str, *candidates: str | None) -> bool:
    folded = value.strip().casefold()
    return any(candidate is not None and candidate.casefold() == folded for candidate in candidates)


@dataclass(frozen=True)
class LinearState:
    organization: Organization
    viewer: User
    users: tuple[User, ...]
    teams: tuple[Team, ...]
    labels: tuple[Label, ...]
    projects: tuple[Project, ...]
    documents: tuple[Document, ...]
    issues: tuple[Issue, ...]

    def user(self, key: str) -> User | None:
        if key.strip().casefold() == "me":
            return self.viewer
        for user in self.users:
            if _same(key, user.id, user.email, user.name, user.display_name):
                return user
        return None

    def team(self, key: str) -> Team | None:
        for team in self.teams:
            if _same(key, team.id, team.key, team.name):
                return team
        return None

    def workflow_state(self, key: str, team: Team | None) -> WorkflowState | None:
        for candidate in self.workflow_states():
            if team is not None and candidate.team_key != team.key:
                continue
            if _same(key, candidate.id, candidate.name):
                return candidate
        return None

    def workflow_states(self) -> tuple[WorkflowState, ...]:
        return tuple(item for team in self.teams for item in team.states)

    def cycles(self) -> tuple[Cycle, ...]:
        return tuple(cycle for team in self.teams for cycle in team.cycles)

    def label(self, key: str) -> Label | None:
        for label in self.labels:
            if _same(key, label.id, label.name):
                return label
        return None

    def project(self, key: str) -> Project | None:
        for project in self.projects:
            if _same(key, project.id, project.name):
                return project
        return None

    def milestones(self) -> tuple[Milestone, ...]:
        return tuple(item for project in self.projects for item in project.milestones)

    def milestone(self, key: str) -> Milestone | None:
        for milestone in self.milestones():
            if _same(key, milestone.id, milestone.name):
                return milestone
        return None

    def document(self, key: str) -> Document | None:
        for document in self.documents:
            if _same(key, document.id, document.key, document.title):
                return document
        return None

    def issue(self, key: str) -> Issue | None:
        for issue in self.issues:
            if _same(key, issue.id, issue.identifier):
                return issue
        return None

    def attachment(self, key: str) -> Attachment | None:
        for issue in self.issues:
            for attachment in issue.attachments:
                if _same(key, attachment.id):
                    return attachment
        return None

    def id_map(self) -> dict[str, Any]:
        return {
            "issues": {issue.identifier: issue.id for issue in self.issues},
            "users": {user.key: user.id for user in self.users},
            "teams": {team.key: team.id for team in self.teams},
            "projects": {project.key: project.id for project in self.projects},
            "milestones": {item.key: item.id for item in self.milestones()},
            "documents": {document.key: document.id for document in self.documents},
            "attachments": {
                attachment.key: attachment.id
                for issue in self.issues
                for attachment in issue.attachments
            },
        }
