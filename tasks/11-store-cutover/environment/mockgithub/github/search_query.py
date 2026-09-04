from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_TOKEN = re.compile(r'(?P<neg>-)?(?:(?P<key>[A-Za-z]+):)?(?:"(?P<quoted>[^"]*)"|(?P<word>\S+))')
_TEXT_FIELDS = ("title", "body", "content")


@dataclass(frozen=True)
class Query:
    terms: tuple[tuple[str, bool], ...]
    qualifiers: tuple[tuple[str, str, bool], ...]
    fields: tuple[str, ...]


def parse(query: str) -> Query:
    terms: list[tuple[str, bool]] = []
    qualifiers: list[tuple[str, str, bool]] = []
    fields: list[str] = []
    for match in _TOKEN.finditer(query):
        negated = match["neg"] is not None
        value = match["quoted"] if match["quoted"] is not None else match["word"]
        key = match["key"]
        if key is None:
            terms.append((value.casefold(), negated))
        elif key.casefold() == "in":
            fields.extend(part.casefold() for part in value.split(",") if part)
        else:
            qualifiers.append((key.casefold(), value, negated))
    return Query(tuple(terms), tuple(qualifiers), tuple(fields))


def _flag(doc: dict[str, Any], value: str) -> bool:
    if value in ("issue", "pr"):
        return bool(doc.get("type") == value)
    if value in ("open", "closed"):
        return bool(doc.get("state") == value)
    if value == "merged":
        return bool(doc.get("merged"))
    if value == "unmerged":
        return not doc.get("merged")
    if value == "draft":
        return bool(doc.get("draft"))
    return True


def _owner(doc: dict[str, Any], value: str) -> bool:
    return str(doc.get("repo", "")).split("/")[0].casefold() == value.casefold()


def _same(field: str) -> Callable[[dict[str, Any], str], bool]:
    return lambda doc, value: str(doc.get(field, "")).casefold() == value.casefold()


def _within(field: str) -> Callable[[dict[str, Any], str], bool]:
    return lambda doc, value: (
        value.casefold() in [str(item).casefold() for item in doc.get(field, [])]
    )


_QUALIFIERS: dict[str, Callable[[dict[str, Any], str], bool]] = {
    "is": _flag,
    "type": _flag,
    "state": lambda doc, value: bool(doc.get("state") == value),
    "label": _within("labels"),
    "assignee": _within("assignees"),
    "author": _same("author"),
    "repo": _same("repo"),
    "filename": _same("filename"),
    "org": _owner,
    "user": _owner,
    "path": lambda doc, value: str(doc.get("path", "")).casefold().startswith(value.casefold()),
    "extension": lambda doc, value: (
        str(doc.get("path", "")).casefold().endswith("." + value.casefold())
    ),
}


def _haystack(query: Query, doc: dict[str, Any]) -> str:
    fields = query.fields or _TEXT_FIELDS
    return "\n".join(str(doc.get(field, "")) for field in fields).casefold()


def matches(query: Query, doc: dict[str, Any]) -> bool:
    haystack = _haystack(query, doc)
    for term, negated in query.terms:
        if (term in haystack) == negated:
            return False
    for key, value, negated in query.qualifiers:
        check = _QUALIFIERS.get(key)
        if check is not None and check(doc, value) == negated:
            return False
    return True
