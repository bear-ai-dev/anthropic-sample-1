from __future__ import annotations

from .address import address_of
from .state import GmailState


def human_keys(state: GmailState) -> dict[str, set[str]]:
    attachments = [item for message in state.messages for item in message.attachments]
    return {
        "thread key": {message.thread_key for message in state.messages},
        "message key": {message.key for message in state.messages},
        "message id": {message.message_id for message in state.messages if message.message_id},
        "subject": {message.subject for message in state.messages if message.subject},
        "sender address": {address_of(message.sender) for message in state.messages},
        "attachment key": {attachment.key for attachment in attachments},
        "attachment filename": {attachment.filename for attachment in attachments},
    }
