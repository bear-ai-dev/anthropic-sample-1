from __future__ import annotations

from datetime import datetime
from typing import Any

from ..ids import number_for
from .load_common import SERVICE, Context, users_of
from .load_issues import issues_of
from .load_pulls import pulls_of
from .load_repo import branches_of, commits_of, labels_of, milestones_of, releases_of, tags_of
from .models_issues import User
from .models_repo import Repo
from .state import GithubState

DEFAULT_BRANCH = "main"


def _context(raw: dict[str, Any], seed: int, clock: datetime, logins: frozenset[str]) -> Context:
    return Context(
        seed=seed,
        clock=clock,
        full_name=f"{raw['owner']}/{raw['name']}",
        logins=logins,
        label_names=frozenset(str(item["name"]) for item in raw.get("labels", [])),
        milestone_numbers=frozenset(int(item["number"]) for item in raw.get("milestones", [])),
        commit_keys=frozenset(str(item["key"]) for item in raw.get("commits", [])),
    )


def _repo(raw: dict[str, Any], context: Context, viewer: str) -> Repo:
    default_branch = str(raw.get("default_branch", DEFAULT_BRANCH))
    return Repo(
        id=context.number("repository", context.full_name),
        owner=str(raw["owner"]),
        name=str(raw["name"]),
        default_branch=default_branch,
        description=str(raw.get("description", "")),
        labels=labels_of(raw.get("labels", []), context),
        milestones=milestones_of(raw.get("milestones", []), context),
        commits=commits_of(raw.get("commits", []), context),
        branches=branches_of(raw.get("branches", []), context),
        tags=tags_of(raw.get("tags", []), context),
        releases=releases_of(raw.get("releases", []), context),
        issues=issues_of(raw.get("issues", []), context, viewer),
        pulls=pulls_of(raw.get("pulls", []), context, default_branch),
    )


def _viewer(users: tuple[User, ...], login: str, seed: int, clock: datetime) -> User:
    return next(
        (user for user in users if user.login == login),
        User(
            id=number_for(seed, SERVICE, "user", login),
            login=login,
            name="",
            email="",
            company="",
            location="",
            bio="",
            created_at=clock,
        ),
    )


def load(section: dict[str, Any], seed: int, clock: datetime) -> GithubState:
    users = users_of(section.get("users", []), seed, clock)
    first = users[0].login if users else ""
    viewer = _viewer(users, str(section.get("viewer", first)), seed, clock)
    logins = frozenset(user.login for user in users)
    repos = tuple(
        _repo(raw, _context(raw, seed, clock, logins), viewer.login)
        for raw in section.get("repos", [])
    )
    return GithubState(viewer=viewer, users=users, repos=repos)
