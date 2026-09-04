from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..format import labels_text

SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    return text_result(labels_text(list(world.gmail.labels)))


SPEC = ToolSpec("list_email_labels", "Retrieves all available Gmail labels", SCHEMA, handler)
