from __future__ import annotations

import base64
from typing import Any

from ...payload import ATTACHMENT_KEY
from ...tool_errors import NotFound
from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..content import attachment_bytes

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "messageId": {
            "type": "string",
            "description": "ID of the email message containing the attachment",
        },
        "attachmentId": {"type": "string", "description": "ID of the attachment to download"},
        "savePath": {
            "type": "string",
            "description": "Directory path to save the attachment (defaults to current directory)",
        },
        "filename": {
            "type": "string",
            "description": "Filename to save the attachment as (defaults to original filename)",
        },
    },
    "required": ["messageId", "attachmentId"],
}


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    message_id = str(arguments["messageId"])
    attachment_id = str(arguments["attachmentId"])
    message = world.gmail.message(message_id)
    if message is None:
        raise NotFound("Message", message_id)
    attachment = world.gmail.attachment(message, attachment_id)
    if attachment is None:
        raise NotFound("Attachment", attachment_id)
    save_path = arguments.get("savePath")
    return json_result(
        {
            ATTACHMENT_KEY: {
                "filename": str(arguments.get("filename") or attachment.filename),
                "mimeType": attachment.mime_type,
                "size": attachment.size,
                "data_b64": base64.b64encode(attachment_bytes(attachment)).decode(),
                "savePath": None if save_path is None else str(save_path),
            }
        }
    )


SPEC = ToolSpec(
    "download_attachment",
    "Downloads an email attachment to a specified location",
    SCHEMA,
    handler,
)
