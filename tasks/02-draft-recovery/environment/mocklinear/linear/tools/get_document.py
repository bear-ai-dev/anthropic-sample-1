from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, json_result
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import object_schema
from ..lookup import found
from ..render_project import document_json

SCHEMA = object_schema(
    {"id": {"type": "string", "description": "Document id, slug or title."}}, ["id"]
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    key = str(arguments["id"])
    document = found(state.document(key), "Document", key)
    return json_result(document_json(state, document))


SPEC = ToolSpec(
    name="get_document",
    description="Get one document by id, slug or title, with its full content.",
    input_schema=SCHEMA,
    handler=handler,
)
