from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult
from ...tool_spec import ToolSpec
from ...world import World
from ..envelope import list_schema, paged
from ..render_project import document_json

SCHEMA = list_schema(
    {
        "project": {"type": "string", "description": "Project id or name."},
        "issue": {"type": "string", "description": "Issue id or identifier."},
        "query": {"type": "string", "description": "Text to look for in the title or body."},
    }
)


def handler(world: World, arguments: dict[str, Any]) -> ToolResult:
    state = world.linear
    project = state.project(str(arguments["project"])) if arguments.get("project") else None
    issue = state.issue(str(arguments["issue"])) if arguments.get("issue") else None
    wanted = str(arguments["query"]).casefold() if arguments.get("query") else None
    documents = [
        document
        for document in state.documents
        if (project is None or document.project_key == project.key)
        and (issue is None or document.issue_identifier == issue.identifier)
        and (wanted is None or wanted in f"{document.title} {document.content}".casefold())
    ]
    documents.sort(key=lambda document: document.updated_at, reverse=True)
    return paged("documents", documents, arguments, lambda item: document_json(state, item))


SPEC = ToolSpec(
    name="list_documents",
    description="List documents, filtered by project, issue or free text, newest first.",
    input_schema=SCHEMA,
    handler=handler,
)
