from __future__ import annotations

from typing import Any

from ..clock import iso_seconds
from .models_issues import User
from .state import GithubState


def avatar_url(user_id: int) -> str:
    return f"https://avatars.githubusercontent.com/u/{user_id}?v=4"


def user_ref(user: User | None, login: str) -> dict[str, Any]:
    user_id = 0 if user is None else user.id
    return {
        "login": login,
        "id": user_id,
        "html_url": f"https://github.com/{login}",
        "avatar_url": avatar_url(user_id),
    }


def ref_for(state: GithubState, login: str) -> dict[str, Any]:
    return user_ref(state.user(login), login)


def minimal_user(state: GithubState, user: User) -> dict[str, Any]:
    return {
        "login": user.login,
        "id": user.id,
        "profile_url": f"https://github.com/{user.login}",
        "avatar_url": avatar_url(user.id),
        "details": {
            "name": user.name,
            "email": user.email,
            "company": user.company,
            "location": user.location,
            "bio": user.bio,
            "public_repos": sum(1 for repo in state.repos if repo.owner == user.login),
            "followers": 0,
            "following": 0,
            "created_at": iso_seconds(user.created_at),
        },
    }


def search_user(user: User) -> dict[str, Any]:
    return dict(user_ref(user, user.login), type="User", score=1.0)
