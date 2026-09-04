from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..format import search_result
from ..query import matcher

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Gmail search query (e.g., 'from:example@gmail.com')",
        },
        "maxResults": {
            "type": "number",
            "description": "Maximum number of results to return",
            "default": 10,
        },
    },
    "required": ["query"],
}


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    limit = max(0, int(arguments["maxResults"]))
    match = matcher(str(arguments["query"]), world.clock, world.gmail.labels)
    matched = [message for message in world.gmail.messages if match(message)]
    window = matched[:limit]
    return text_result(
        search_result(window),
        page={"maxResults": limit, "matched": len(matched), "returned": len(window)},
    )


SPEC = ToolSpec("search_emails", "Searches for emails using Gmail search syntax", SCHEMA, handler)
