import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mocklinear.tests.integration.conftest import Daemon

SHARED = str(Path(__file__).resolve().parents[3])


def _environment(url: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": SHARED,
        "PYTHONUNBUFFERED": "1",
        "MOCKLINEAR_URL": url,
    }


async def _drive(url: str) -> tuple[list[str], Any, Any]:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "mocklinear.client"], env=_environment(url)
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        issue = await session.call_tool("get_issue", {"id": "WEB-611"})
        missing = await session.call_tool("get_issue", {"id": "WEB-999"})
        return [tool.name for tool in listed.tools], issue, missing


def test_the_official_mcp_client_can_drive_the_shim(daemon: Daemon) -> None:
    names, issue, missing = asyncio.run(asyncio.wait_for(_drive(daemon.url), 60))
    assert len(names) == 20
    assert "list_issues" in names
    assert json.loads(issue.content[0].text)["identifier"] == "WEB-611"
    assert not issue.isError
    assert missing.isError
    assert missing.content[0].text == "Entity not found: Issue - Could not find referenced Issue."
    assert [record["via"] for record in daemon.engine.journal.records()] == ["mcp", "mcp"]
