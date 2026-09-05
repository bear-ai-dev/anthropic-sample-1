from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render import label_json

SCHEMA = list_schema({})


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    keys = {key for project in state.projects for key in project.label_keys}
    labels = [label for label in state.labels if label.key in keys]
    return paged(
        "labels",
        sorted(labels, key=lambda label: label.name),
        arguments,
        lambda label: label_json(state, label),
    )


SPEC = ToolSpec(
    name="list_project_labels",
    description="List the labels projects carry in this workspace.",
    input_schema=SCHEMA,
    handler=handler,
)
