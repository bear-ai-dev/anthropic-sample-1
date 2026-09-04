import os
import subprocess
import sys
from pathlib import Path

from mockgmail.tests.integration.conftest import Daemon
from mockgmail.tests.lookup import message_by_key

SHARED = Path(__file__).resolve().parents[3]
WRAPPER = SHARED / "mockgmail" / "bin" / "mockgmail"


def _run(url: str, *arguments: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SHARED),
        "MOCKGMAIL_URL": url,
    }
    return subprocess.run(
        [sys.executable, "-m", "mockgmail.client", *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
        cwd=cwd,
    )


def test_the_command_lists_the_tools_it_answers(daemon: Daemon) -> None:
    done = _run(daemon.url, "tools")
    assert done.returncode == 0
    assert done.stderr == ""
    assert done.stdout.count("inputSchema") == 0
    assert "search_emails: Searches for emails using Gmail search syntax" in done.stdout
    assert done.stdout.count('  "type": "object"') == 4


def test_a_tool_call_prints_what_the_mailbox_answered(daemon: Daemon) -> None:
    done = _run(daemon.url, "search_emails", "--query", "from:okonjo", "--maxResults", "5")
    assert done.returncode == 0
    ids = [
        line.removeprefix("ID: ") for line in done.stdout.splitlines() if line.startswith("ID: ")
    ]
    state = daemon.engine.world.gmail
    assert ids == [message_by_key(state, "okonjo-3").id, message_by_key(state, "okonjo-1").id]
    assert daemon.engine.journal.records()[0]["via"] == "cli"


def test_arguments_can_arrive_as_one_json_object(daemon: Daemon) -> None:
    done = _run(
        daemon.url, "search_emails", "--json", '{"query": "label:billing", "maxResults": 1}'
    )
    assert done.returncode == 0
    assert done.stdout.count("ID: ") == 1
    assert "Subject: Re: PO number on invoice 5133" in done.stdout


def test_a_value_that_starts_with_a_dash_travels_after_a_double_dash(daemon: Daemon) -> None:
    refused = _run(daemon.url, "search_emails", "--query", "-in:sent")
    assert refused.returncode == 2
    assert "put it after --" in refused.stderr
    accepted = _run(daemon.url, "search_emails", "--query", "--", "-in:sent")
    assert accepted.returncode == 0
    assert accepted.stdout.count("ID: ") == 10


def test_a_missing_entity_is_the_vendor_text_on_stdout_with_exit_one(daemon: Daemon) -> None:
    done = _run(daemon.url, "read_email", "--messageId", "0000000000000000")
    assert done.returncode == 1
    assert done.stdout == "Error: Requested entity was not found.\n"
    assert done.stderr == ""


def test_an_unknown_tool_exits_two(daemon: Daemon) -> None:
    done = _run(daemon.url, "send_email", "--to", "nope")
    assert done.returncode == 2
    assert done.stderr.strip() == "Unknown tool: send_email"


def test_a_daemon_that_is_not_listening_is_reported_without_a_traceback() -> None:
    done = _run("http://127.0.0.1:4", "list_email_labels")
    assert done.returncode == 2
    assert done.stderr.strip() == "mockgmail daemon not reachable at http://127.0.0.1:4"
    assert "Traceback" not in done.stderr


def test_the_shell_wrapper_reaches_the_same_tools(daemon: Daemon) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "MOCKGMAIL_PYTHONPATH": str(SHARED),
        "MOCKGMAIL_URL": daemon.url,
    }
    done = subprocess.run(
        [str(WRAPPER), "list_email_labels"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("Found 11 labels (8 system, 3 user):")


def test_stdin_that_never_speaks_gets_the_usage_and_exits_zero(daemon: Daemon) -> None:
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(SHARED),
        "MOCKGMAIL_URL": daemon.url,
        "MOCKGMAIL_STDIO_IDLE_SEC": "0.2",
    }
    done = subprocess.run(
        [sys.executable, "-m", "mockgmail.client"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    assert done.returncode == 0
    assert "gmail tools" in done.stdout


def test_the_same_tool_through_both_transports_differs_only_in_how_it_arrived(
    daemon: Daemon,
) -> None:
    _run(daemon.url, "list_email_labels")
    daemon.post(
        "/mcp/gmail",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_email_labels", "arguments": {}},
        },
        {"x-mockgmail-via": "mcp"},
    )
    records = daemon.engine.journal.records()
    assert [record["via"] for record in records] == ["cli", "mcp"]
    assert records[0]["args"] == records[1]["args"]
    assert records[0]["result_chars"] == records[1]["result_chars"]


def test_a_download_is_written_where_the_command_runs(daemon: Daemon, tmp_path: Path) -> None:
    message = message_by_key(daemon.engine.world.gmail, "okonjo-2")
    attachment = message.attachments[0]
    done = _run(
        daemon.url,
        "download_attachment",
        "--messageId",
        message.id,
        "--attachmentId",
        attachment.id,
        cwd=tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == (
        "Attachment downloaded successfully:\nFile: invoice-5120.pdf\n"
        f"Size: 88214 bytes\nSaved to: {tmp_path / 'invoice-5120.pdf'}\n"
    )
    assert (tmp_path / "invoice-5120.pdf").stat().st_size == 88214
    nested = _run(
        daemon.url,
        "download_attachment",
        "--json",
        f'{{"messageId": "{message.id}", "attachmentId": "{attachment.id}", '
        '"savePath": "mail/out", "filename": "copy.pdf"}',
        cwd=tmp_path,
    )
    assert nested.returncode == 0, nested.stderr
    assert (tmp_path / "mail" / "out" / "copy.pdf").stat().st_size == 88214


def test_a_download_that_escapes_its_save_path_is_refused(daemon: Daemon, tmp_path: Path) -> None:
    message = message_by_key(daemon.engine.world.gmail, "okonjo-2")
    inner = tmp_path / "inner"
    inner.mkdir()
    done = _run(
        daemon.url,
        "download_attachment",
        "--messageId",
        message.id,
        "--attachmentId",
        message.attachments[0].id,
        "--filename",
        "../escape.pdf",
        cwd=inner,
    )
    assert done.returncode == 1
    assert done.stdout == "Error: filename escapes savePath\n"
    assert not (tmp_path / "escape.pdf").exists()
