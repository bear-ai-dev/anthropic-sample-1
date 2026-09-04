from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Attachment, Label, Message


@dataclass(frozen=True)
class GmailState:
    email_address: str
    labels: tuple[Label, ...]
    messages: tuple[Message, ...]

    def message(self, message_id: str) -> Message | None:
        for message in self.messages:
            if message.id == message_id:
                return message
        return None

    def attachment(self, message: Message, attachment_id: str) -> Attachment | None:
        for attachment in message.attachments:
            if attachment.id == attachment_id:
                return attachment
        return None

    def label(self, key: str) -> Label | None:
        wanted = key.strip().casefold()
        for label in self.labels:
            if wanted in (label.id.casefold(), label.key.casefold(), label.name.casefold()):
                return label
        return None

    def id_map(self) -> dict[str, Any]:
        return {
            "messages": {
                message.key: {"id": message.id, "threadId": message.thread_id}
                for message in self.messages
            },
            "attachments": {
                attachment.key: attachment.id
                for message in self.messages
                for attachment in message.attachments
            },
            "labels": {label.key: label.id for label in self.labels},
        }
