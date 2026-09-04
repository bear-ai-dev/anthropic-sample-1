from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta

from ..clock import parse_ts
from ..tool_errors import InvalidArguments
from .models import Label, Message

Predicate = Callable[[Message], bool]
_AGE = re.compile(r"(\d+)([hdwmy])")
_AGE_SECONDS = {"h": 3600, "d": 86400, "w": 604800, "m": 2592000, "y": 31536000}
_MAILBOXES = {"inbox": "INBOX", "sent": "SENT", "trash": "TRASH", "spam": "SPAM", "draft": "DRAFT"}
_FLAGS = {"unread": "UNREAD", "starred": "STARRED", "important": "IMPORTANT"}
_OPERATORS = frozenset(
    (
        "from",
        "to",
        "cc",
        "subject",
        "has",
        "filename",
        "label",
        "in",
        "is",
        "after",
        "before",
        "newer",
        "older",
        "newer_than",
        "older_than",
    )
)


def _nothing(message: Message) -> bool:
    return False


def _haystack(message: Message) -> str:
    parts = (message.subject, message.body_text, message.sender, *message.to, *message.cc)
    return "\n".join(parts).casefold()


def text(value: str) -> Predicate:
    wanted = value.casefold()
    return lambda message: wanted in _haystack(message)


def _day(value: str) -> datetime | None:
    try:
        return parse_ts(value.replace("/", "-"))
    except InvalidArguments:
        return None


def _age(value: str, now: datetime) -> datetime | None:
    found = _AGE.fullmatch(value)
    if found is None:
        return None
    return now - timedelta(seconds=int(found[1]) * _AGE_SECONDS[found[2]])


def _since(moment: datetime | None) -> Predicate:
    if moment is None:
        return _nothing
    return lambda message: message.date >= moment


def _until(moment: datetime | None) -> Predicate:
    if moment is None:
        return _nothing
    return lambda message: message.date < moment


def _label_id(value: str, labels: tuple[Label, ...]) -> str | None:
    wanted = value.casefold()
    for label in labels:
        if wanted in (label.id.casefold(), label.key.casefold(), label.name.casefold()):
            return label.id
    return None


def _has_label(label_id: str | None) -> Predicate:
    if label_id is None:
        return _nothing
    return lambda message: label_id in message.label_ids


def _mailbox(value: str, labels: tuple[Label, ...]) -> Predicate:
    if value == "anywhere":
        return lambda message: True
    return _has_label(_label_id(_MAILBOXES.get(value, value), labels))


def _flag(value: str) -> Predicate:
    if value == "read":
        return lambda message: "UNREAD" not in message.label_ids
    return _has_label(_FLAGS.get(value))


def operator(name: str, value: str, now: datetime, labels: tuple[Label, ...]) -> Predicate | None:
    wanted = value.casefold()
    if not wanted:
        return _nothing if name in _OPERATORS else None
    if name == "from":
        return lambda message: wanted in message.sender.casefold()
    if name == "to":
        return lambda message: any(wanted in address.casefold() for address in message.to)
    if name == "cc":
        return lambda message: any(wanted in address.casefold() for address in message.cc)
    if name == "subject":
        return lambda message: wanted in message.subject.casefold()
    if name == "has":
        return (lambda message: bool(message.attachments)) if wanted == "attachment" else _nothing
    if name == "filename":
        return lambda message: any(
            wanted in item.filename.casefold() for item in message.attachments
        )
    if name == "label":
        return _has_label(_label_id(wanted, labels))
    if name == "in":
        return _mailbox(wanted, labels)
    if name == "is":
        return _flag(wanted)
    if name in ("after", "newer"):
        return _since(_day(wanted))
    if name in ("before", "older"):
        return _until(_day(wanted))
    if name == "newer_than":
        return _since(_age(wanted, now))
    if name == "older_than":
        return _until(_age(wanted, now))
    return None
