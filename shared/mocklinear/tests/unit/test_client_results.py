import io
from pathlib import Path
from typing import Any

import pytest

from mocklinear.client import cli
from mocklinear.client.attachment import rewrite


class Recorder:
    def __init__(self, answer: Any) -> None:
        self.answer = answer

    def __call__(self, message: dict[str, Any], via: str) -> Any:
        return self.answer


def _run(monkeypatch: pytest.MonkeyPatch, answer: Any, argv: list[str]) -> tuple[int, str]:
    monkeypatch.setattr(cli, "post_message", Recorder(answer))
    out = io.StringIO()
    code = cli.main(argv, out, io.StringIO())
    return code, out.getvalue()


def _answer(content: list[dict[str, Any]]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": content}}


def test_a_lone_vendor_error_text_exits_one_even_without_the_error_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = _answer([{"type": "text", "text": "Error: Requested entity was not found."}])
    code, out = _run(monkeypatch, answer, ["get_issue"])
    assert code == 1
    assert out == "Error: Requested entity was not found.\n"


def test_an_ordinary_answer_that_merely_mentions_an_error_still_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "The alert said Error: disk full, and the runbook is stale."
    code, out = _run(monkeypatch, _answer([{"type": "text", "text": body}]), ["get_issue"])
    assert code == 0
    assert out == body + "\n"
    two = [{"type": "text", "text": "Error: one"}, {"type": "text", "text": "Error: two"}]
    code, _ = _run(monkeypatch, _answer(two), ["get_issue"])
    assert code == 0


def test_an_embedded_resource_block_is_printed_after_its_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "downloaded README.md"},
        {"type": "resource", "resource": {"uri": "x://README.md", "text": "# hi"}},
        {"type": "resource"},
        {"type": "image", "data": "ignored"},
    ]
    code, out = _run(monkeypatch, _answer(content), ["get_issue"])
    assert code == 0
    assert out == "downloaded README.md\n# hi\n\n"


def test_the_client_hands_an_answer_back_unchanged_when_nothing_needs_a_file() -> None:
    answer = _answer([{"type": "text", "text": "plain"}])
    assert rewrite(answer, Path.cwd()) is answer
    assert rewrite(None, Path.cwd()) is None
