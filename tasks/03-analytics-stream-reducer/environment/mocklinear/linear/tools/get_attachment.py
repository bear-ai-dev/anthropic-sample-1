from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render_issue import attachment_json

SCHEMA = object_schema({"id": {"type": "string", "description": "Attachment id."}}, ["id"])


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    attachment = found(state.attachment(key), "Attachment", key)
    return json_result(attachment_json(state, attachment))


SPEC = ToolSpec(
    name="get_attachment",
    description="Get one issue attachment by id.",
    input_schema=SCHEMA,
    handler=handler,
)
