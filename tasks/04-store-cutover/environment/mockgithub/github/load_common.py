from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, NoReturn

from ..clock import parse_ts
from ..ids import number_for
from ..scenario import ScenarioError
from .models_issues import Comment, User

SERVICE = "github"


@dataclass(frozen=True)
class Context:
    seed: int
    clock: datetime
    full_name: str
    logins: frozenset[str]
    label_names: frozenset[str]
    milestone_numbers: frozenset[int]
    commit_keys: frozenset[str]

    def number(self, kind: str, key: str) -> int:
        return number_for(self.seed, SERVICE, kind, key)


def fail(where: str, kind: str, value: Any) -> NoReturn:
    raise ScenarioError(f"{where} names an unknown {kind}: {value}")


def timestamp(raw: dict[str, Any], key: str, default: datetime) -> datetime:
    value = raw.get(key)
    return default if value is None else parse_ts(str(value))


def optional_timestamp(raw: dict[str, Any], key: str) -> datetime | None:
    value = raw.get(key)
    return None if value is None else parse_ts(str(value))


def login_of(raw: dict[str, Any], key: str, context: Context, where: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    login = str(value)
    if login not in context.logins:
        fail(where, "user", login)
    return login


def logins_of(raw: list[Any], context: Context, where: str) -> tuple[str, ...]:
    logins = tuple(str(item) for item in raw)
    for login in logins:
        if login not in context.logins:
            fail(where, "user", login)
    return logins


def labels_of(raw: list[Any], context: Context, where: str) -> tuple[str, ...]:
    names = tuple(str(item) for item in raw)
    for name in names:
        if name not in context.label_names:
            fail(where, "label", name)
    return names


def commit_key_of(value: Any, context: Context, where: str) -> str:
    key = str(value)
    if key not in context.commit_keys:
        fail(where, "commit", key)
    return key


def comments_of(raw: list[dict[str, Any]], context: Context, where: str) -> tuple[Comment, ...]:
    return tuple(
        Comment(
            id=context.number("comment", f"{context.full_name}:{item['key']}"),
            key=str(item["key"]),
            user_login=login_of(item, "user", context, where) or "",
            body=str(item.get("body", "")),
            created_at=timestamp(item, "created_at", context.clock),
        )
        for item in raw
    )


def users_of(raw: list[dict[str, Any]], seed: int, clock: datetime) -> tuple[User, ...]:
    return tuple(
        User(
            id=number_for(seed, SERVICE, "user", str(item["login"])),
            login=str(item["login"]),
            name=str(item.get("name", "")),
            email=str(item.get("email", "")),
            company=str(item.get("company", "")),
            location=str(item.get("location", "")),
            bio=str(item.get("bio", "")),
            created_at=timestamp(item, "created_at", clock),
        )
        for item in raw
    )
