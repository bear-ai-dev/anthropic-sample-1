from __future__ import annotations

from typing import Any

from ...tool_errors import NotFound
from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..format import email_text

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "messageId": {"type": "string", "description": "ID of the email message to retrieve"}
    },
    "required": ["messageId"],
}


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    message_id = str(arguments["messageId"])
    message = world.gmail.message(message_id)
    if message is None:
        raise NotFound("Message", message_id)
    return text_result(email_text(message))


SPEC = ToolSpec("read_email", "Retrieves the content of a specific email", SCHEMA, handler)
