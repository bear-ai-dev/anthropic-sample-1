from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Label:
    id: str
    key: str
    name: str
    type: str


@dataclass(frozen=True)
class Attachment:
    id: str
    key: str
    filename: str
    mime_type: str
    size: int
    data_b64: str | None


@dataclass(frozen=True)
class Message:
    id: str
    key: str
    thread_id: str
    thread_key: str
    message_id: str
    sender: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    subject: str
    date: datetime
    label_ids: tuple[str, ...]
    body_text: str
    body_html: str | None
    in_reply_to: str | None
    references: tuple[str, ...]
    attachments: tuple[Attachment, ...]
