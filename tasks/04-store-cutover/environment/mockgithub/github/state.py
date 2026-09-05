from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models_issues import User
from .models_repo import Repo


@dataclass(frozen=True)
class GithubState:
    viewer: User
    users: tuple[User, ...]
    repos: tuple[Repo, ...]

    def user(self, login: str) -> User | None:
        wanted = login.strip().casefold()
        return next((user for user in self.users if user.login.casefold() == wanted), None)

    def repo(self, owner: str, name: str) -> Repo | None:
        wanted = f"{owner}/{name}".strip().casefold()
        return next((repo for repo in self.repos if repo.full_name.casefold() == wanted), None)

    def id_map(self) -> dict[str, Any]:
        mapping: dict[str, Any] = {"users": {user.login: user.id for user in self.users}}
        for repo in self.repos:
            mapping[repo.full_name] = {
                "commits": {commit.key: commit.sha for commit in repo.commits},
                "issues": [issue.number for issue in repo.issues],
                "pulls": [pull.number for pull in repo.pulls],
            }
        return mapping
