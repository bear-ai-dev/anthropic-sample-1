from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from ..clock import parse_ts
from ..ids import hex_for
from ..scenario import ScenarioError
from .models import Attachment, Label, Message
from .state import GmailState

SERVICE = "gmail"
SYSTEM_LABELS = ("INBOX", "SENT", "UNREAD", "STARRED", "IMPORTANT", "TRASH", "SPAM", "DRAFT")


def _labels(raw: list[dict[str, Any]]) -> tuple[Label, ...]:
    system = [Label(id=name, key=name, name=name, type="system") for name in SYSTEM_LABELS]
    user = [
        Label(
            id=f"Label_{index}",
            key=str(item["key"]),
            name=str(item.get("name", item["key"])),
            type="user",
        )
        for index, item in enumerate(raw, start=1)
    ]
    return tuple(system + user)


def _label_ids(raw: list[Any], labels: tuple[Label, ...], key: str) -> tuple[str, ...]:
    resolved: list[str] = []
    for name in raw:
        wanted = str(name).casefold()
        match = next(
            (
                label
                for label in labels
                if wanted in (label.id.casefold(), label.key.casefold(), label.name.casefold())
            ),
            None,
        )
        if match is None:
            raise ScenarioError(f"message {key} names an unknown label: {name}")
        resolved.append(match.id)
    return tuple(resolved)


def _attachment(item: dict[str, Any], seed: int) -> Attachment:
    key = str(item["key"])
    data = item.get("data_b64")
    size = item.get("size")
    if size is None:
        size = 0 if data is None else len(base64.b64decode(str(data)))
    return Attachment(
        id=base64.urlsafe_b64encode(
            hex_for(seed, SERVICE, "attachment", key, 48).encode()
        ).decode(),
        key=key,
        filename=str(item.get("filename", key)),
        mime_type=str(item.get("mime_type", "application/octet-stream")),
        size=int(size),
        data_b64=None if data is None else str(data),
    )


def _message(
    item: dict[str, Any],
    thread_key: str,
    labels: tuple[Label, ...],
    seed: int,
    clock: datetime,
) -> Message:
    key = str(item["key"])
    return Message(
        id=hex_for(seed, SERVICE, "message", key, 16),
        key=key,
        thread_id=hex_for(seed, SERVICE, "thread", thread_key, 16),
        thread_key=thread_key,
        message_id=str(item.get("message_id", "")),
        sender=str(item.get("from", "")),
        to=tuple(str(address) for address in item.get("to", [])),
        cc=tuple(str(address) for address in item.get("cc", [])),
        subject=str(item.get("subject", "")),
        date=parse_ts(str(item["date"])) if "date" in item else clock,
        label_ids=_label_ids(item.get("labels", []), labels, key),
        body_text=str(item.get("body_text", "")),
        body_html=None if item.get("body_html") is None else str(item["body_html"]),
        in_reply_to=None if item.get("in_reply_to") is None else str(item["in_reply_to"]),
        references=tuple(str(reference) for reference in item.get("references", [])),
        attachments=tuple(_attachment(raw, seed) for raw in item.get("attachments", [])),
    )


def load(section: dict[str, Any], seed: int, clock: datetime) -> GmailState:
    labels = _labels(section.get("labels", []))
    messages = [
        _message(item, str(thread["key"]), labels, seed, clock)
        for thread in section.get("threads", [])
        for item in thread.get("messages", [])
    ]
    messages.sort(key=lambda message: message.date, reverse=True)
    return GmailState(
        email_address=str(section.get("profile", {}).get("emailAddress", "")),
        labels=labels,
        messages=tuple(messages),
    )
