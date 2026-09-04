import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mockgmail.tests.integration.conftest import Daemon
from mockgmail.tests.lookup import message_by_key

SHARED = str(Path(__file__).resolve().parents[3])


def _environment(url: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": SHARED,
        "PYTHONUNBUFFERED": "1",
        "MOCKGMAIL_URL": url,
    }


async def _drive(url: str, cwd: Path, message_id: str, attachment_id: str) -> dict[str, Any]:
    parameters = StdioServerParameters(
        command=sys.executable, args=["-m", "mockgmail.client"], env=_environment(url), cwd=cwd
    )
    async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        return {
            "names": [tool.name for tool in listed.tools],
            "email": await session.call_tool("read_email", {"messageId": message_id}),
            "missing": await session.call_tool("read_email", {"messageId": "0000000000000000"}),
            "download": await session.call_tool(
                "download_attachment", {"messageId": message_id, "attachmentId": attachment_id}
            ),
        }


def test_the_official_mcp_client_can_drive_the_shim(daemon: Daemon, tmp_path: Path) -> None:
    message = message_by_key(daemon.engine.world.gmail, "halloran-2")
    attachment = message.attachments[0]
    driven = asyncio.run(
        asyncio.wait_for(_drive(daemon.url, tmp_path, message.id, attachment.id), 60)
    )
    assert driven["names"] == [
        "download_attachment",
        "list_email_labels",
        "read_email",
        "search_emails",
    ]
    assert driven["email"].content[0].text.startswith(f"Thread ID: {message.thread_id}\n")
    assert not driven["email"].isError
    assert not driven["missing"].isError
    assert driven["missing"].content[0].text == "Error: Requested entity was not found."
    assert driven["download"].content[0].text == (
        "Attachment downloaded successfully:\nFile: fenwick-cabaret-60.pdf\n"
        f"Size: 143220 bytes\nSaved to: {tmp_path / 'fenwick-cabaret-60.pdf'}"
    )
    assert (tmp_path / "fenwick-cabaret-60.pdf").stat().st_size == 143220
    assert [record["via"] for record in daemon.engine.journal.records()] == ["mcp", "mcp", "mcp"]
