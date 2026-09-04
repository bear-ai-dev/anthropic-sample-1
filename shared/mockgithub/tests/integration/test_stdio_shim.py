import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mockgithub.tests.integration.conftest import Daemon

PACKAGE_ROOT = Path(__file__).resolve().parents[3]


def _parameters(daemon: Daemon) -> StdioServerParameters:
    env = {
        **os.environ,
        "MOCKGITHUB_URL": daemon.url,
        "PYTHONPATH": str(PACKAGE_ROOT),
        "PYTHONUNBUFFERED": "1",
    }
    return StdioServerParameters(command=sys.executable, args=["-m", "mockgithub.client"], env=env)


async def _drive(daemon: Daemon) -> tuple[Any, list[str], Any, Any]:
    async with (
        stdio_client(_parameters(daemon)) as (read, write),
        ClientSession(read, write) as session,
    ):
        handshake = await session.initialize()
        tools = await session.list_tools()
        me = await session.call_tool("get_me", {})
        missing = await session.call_tool(
            "issue_read",
            {"owner": "ExampleCo", "repo": "membership-ledger", "method": "get", "issue_number": 999},
        )
        return handshake, [tool.name for tool in tools.tools], me, missing


def test_the_official_mcp_client_can_drive_the_shim(daemon: Daemon) -> None:
    handshake, names, me, missing = asyncio.run(_drive(daemon))
    assert handshake.serverInfo.name == "github"
    assert "issue_read" in names and "get_file_contents" in names
    assert len(names) == 16
    assert not me.isError
    assert json.loads(me.content[0].text)["login"] == "rhea-menon"
    assert missing.isError
    assert missing.content[0].text.startswith("failed to get issue: GET https://api.github.com/")
    assert [record["via"] for record in daemon.engine.journal.records()] == ["mcp", "mcp"]
