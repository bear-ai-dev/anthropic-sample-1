import base64
import io
import json
import os
from pathlib import Path
from typing import Any

import pytest

from mockgmail.client import cli, stdio
from mockgmail.client.attachment import rewrite, write_attachment
from mockgmail.payload import ATTACHMENT_KEY
from mockgmail.tool_errors import InvalidArguments

DATA = b"%PDF-1.4 fake"


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "filename": "invoice.pdf",
        "mimeType": "application/pdf",
        "size": len(DATA),
        "data_b64": base64.b64encode(DATA).decode(),
        "savePath": None,
    }
    payload.update(overrides)
    return payload


def _answer(payload: dict[str, Any]) -> dict[str, Any]:
    text = json.dumps({ATTACHMENT_KEY: payload}, indent=2)
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


def test_an_attachment_lands_in_the_working_directory_by_default(tmp_path: Path) -> None:
    target, size = write_attachment(_payload(), tmp_path)
    assert target == tmp_path / "invoice.pdf"
    assert size == len(DATA)
    assert target.read_bytes() == DATA


def test_a_relative_save_path_is_created_under_the_working_directory(tmp_path: Path) -> None:
    target, _ = write_attachment(_payload(savePath="downloads/mail"), tmp_path)
    assert target == tmp_path / "downloads" / "mail" / "invoice.pdf"
    assert target.read_bytes() == DATA


def test_an_absolute_save_path_is_used_as_is(tmp_path: Path) -> None:
    target, _ = write_attachment(_payload(savePath=str(tmp_path / "abs")), Path("/nowhere"))
    assert target == tmp_path / "abs" / "invoice.pdf"
    assert target.exists()


def test_a_filename_that_escapes_the_save_path_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InvalidArguments, match="filename escapes savePath"):
        write_attachment(_payload(filename="../escape.pdf"), tmp_path / "inner")
    with pytest.raises(InvalidArguments, match="filename escapes savePath"):
        write_attachment(_payload(filename="/etc/passwd"), tmp_path)
    with pytest.raises(InvalidArguments, match="filename escapes savePath"):
        write_attachment(_payload(filename=""), tmp_path)
    assert not (tmp_path / "escape.pdf").exists()


def test_a_nested_filename_inside_the_save_path_is_allowed(tmp_path: Path) -> None:
    target, _ = write_attachment(_payload(filename="sub/dir/invoice.pdf"), tmp_path)
    assert target == tmp_path / "sub" / "dir" / "invoice.pdf"
    assert target.exists()


def test_rewriting_a_download_answer_stores_the_file_and_confirms(tmp_path: Path) -> None:
    rewritten = rewrite(_answer(_payload()), tmp_path)
    assert rewritten["result"]["content"] == [
        {
            "type": "text",
            "text": (
                "Attachment downloaded successfully:\nFile: invoice.pdf\n"
                f"Size: {len(DATA)} bytes\nSaved to: {tmp_path / 'invoice.pdf'}"
            ),
        }
    ]
    assert (tmp_path / "invoice.pdf").read_bytes() == DATA


def test_rewriting_a_refused_download_answers_the_gmail_error_text(tmp_path: Path) -> None:
    rewritten = rewrite(_answer(_payload(filename="../x")), tmp_path / "inner")
    assert rewritten["result"]["content"][0]["text"] == "Error: filename escapes savePath"
    assert "isError" not in rewritten["result"]


def test_answers_that_are_not_downloads_pass_through_untouched(tmp_path: Path) -> None:
    plain = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hi"}]}}
    assert rewrite(plain, tmp_path) == plain
    listing = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
    assert rewrite(listing, tmp_path) == listing
    error = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "x"}}
    assert rewrite(error, tmp_path) == error
    assert rewrite(None, tmp_path) is None
    other_json = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": '{"other": 1}'}, {"type": "image"}]},
    }
    assert rewrite(other_json, tmp_path) == other_json
    assert list(tmp_path.iterdir()) == []


def test_the_command_line_stores_a_download_and_prints_the_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "post_message", lambda message, via: _answer(_payload()))
    out = io.StringIO()
    code = cli.main(
        ["download_attachment", "--messageId", "m", "--attachmentId", "a"], out, io.StringIO()
    )
    assert code == 0
    assert out.getvalue().startswith("Attachment downloaded successfully:\nFile: invoice.pdf\n")
    assert (tmp_path / "invoice.pdf").read_bytes() == DATA


def test_the_stdio_shim_stores_a_download_before_answering(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(stdio, "post_message", lambda message, via: _answer(_payload()))
    out = io.StringIO()
    line = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}})
    assert stdio.run(io.StringIO(line + "\n"), out, io.StringIO()) == 0
    answer = json.loads(out.getvalue())
    assert answer["result"]["content"][0]["text"].startswith("Attachment downloaded successfully")
    assert (tmp_path / "invoice.pdf").read_bytes() == DATA


def test_a_save_path_that_is_a_file_answers_the_error_text(tmp_path: Path) -> None:
    (tmp_path / "taken").write_bytes(b"x")
    rewritten = rewrite(_answer(_payload(savePath="taken")), tmp_path)
    text = rewritten["result"]["content"][0]["text"]
    assert text.startswith("Error: ")
    assert "taken" in text
    assert (tmp_path / "taken").read_bytes() == b"x"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_save_path_answers_the_error_text(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        rewritten = rewrite(_answer(_payload(savePath="locked")), tmp_path)
    finally:
        locked.chmod(0o700)
    text = rewritten["result"]["content"][0]["text"]
    assert text.startswith("Error: ")
    assert "Permission denied" in text
    assert list(locked.iterdir()) == []


def test_the_stdio_shim_keeps_serving_after_a_download_that_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "taken").write_bytes(b"x")
    monkeypatch.setattr(
        stdio,
        "post_message",
        lambda message, via: {**_answer(_payload(savePath="taken")), "id": message["id"]},
    )
    out = io.StringIO()
    call = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {}}
    lines = json.dumps(call) + "\n" + json.dumps({**call, "id": 2}) + "\n"
    assert stdio.run(io.StringIO(lines), out, io.StringIO()) == 0
    answers = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [answer["id"] for answer in answers] == [1, 2]
    assert all(a["result"]["content"][0]["text"].startswith("Error: ") for a in answers)


def test_the_command_line_exits_one_when_a_download_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "taken").write_bytes(b"x")
    monkeypatch.setattr(
        cli, "post_message", lambda message, via: _answer(_payload(savePath="taken"))
    )
    out = io.StringIO()
    argv = ["download_attachment", "--messageId", "m", "--attachmentId", "a", "--savePath", "taken"]
    assert cli.main(argv, out, io.StringIO()) == 1
    assert out.getvalue().startswith("Error: ")
