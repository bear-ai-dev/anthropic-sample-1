from __future__ import annotations

from ..tool_spec import ToolSpec
from .tools import download_attachment, list_email_labels, read_email, search_emails


def specs() -> list[ToolSpec]:
    return [
        search_emails.SPEC,
        read_email.SPEC,
        list_email_labels.SPEC,
        download_attachment.SPEC,
    ]
