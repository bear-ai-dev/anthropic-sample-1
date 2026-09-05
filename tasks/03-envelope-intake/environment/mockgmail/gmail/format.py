from __future__ import annotations

from ..clock import rfc2822
from .models import Label, Message

NO_MATCHES = "No emails found matching the query"


def _kilobytes(size: int) -> int:
    return int(size / 1024 + 0.5)


def search_result(messages: list[Message]) -> str:
    if not messages:
        return NO_MATCHES
    return "\n".join(
        f"ID: {message.id}\nSubject: {message.subject}\nFrom: {message.sender}\n"
        f"Date: {rfc2822(message.date)}\n"
        for message in messages
    )


def _attachments(message: Message) -> str:
    if not message.attachments:
        return ""
    lines = [
        f"- {item.filename} ({item.mime_type}, {_kilobytes(item.size)} KB, ID: {item.id})"
        for item in message.attachments
    ]
    return f"\n\nAttachments ({len(message.attachments)}):\n" + "\n".join(lines)


def email_text(message: Message) -> str:
    body = message.body_text or message.body_html or ""
    return (
        f"Thread ID: {message.thread_id}\nSubject: {message.subject}\nFrom: {message.sender}\n"
        f"To: {', '.join(message.to)}\nDate: {rfc2822(message.date)}\n\n{body}"
        + _attachments(message)
    )


def _label_block(labels: list[Label]) -> str:
    return "\n".join(
        f"ID: {label.id}\nName: {label.name}\nType: {label.type}\n" for label in labels
    )


def labels_text(labels: list[Label]) -> str:
    system = [label for label in labels if label.type == "system"]
    user = [label for label in labels if label.type == "user"]
    return (
        f"Found {len(labels)} labels ({len(system)} system, {len(user)} user):\n\n"
        f"System Labels:\n{_label_block(system)}\nUser Labels:\n{_label_block(user)}"
    )


def confirmation(filename: str, size: int, path: str) -> str:
    return (
        f"Attachment downloaded successfully:\nFile: {filename}\nSize: {size} bytes\n"
        f"Saved to: {path}"
    )
