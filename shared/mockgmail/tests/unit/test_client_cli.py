import io
from typing import Any

import pytest

from mockgmail.client import cli


class Recorder:
    def __init__(self, answer: Any) -> None:
        self.answer = answer
        self.sent: list[dict[str, Any]] = []
        self.via: list[str] = []

    def __call__(self, message: dict[str, Any], via: str) -> Any:
        self.sent.append(message)
        self.via.append(via)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _result(text: str, is_error: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"content": [{"type": "text", "text": text}]}
    if is_error:
        payload["isError"] = True
    return {"jsonrpc": "2.0", "id": 1, "result": payload}


def _run(
    monkeypatch: pytest.MonkeyPatch, answer: Any, argv: list[str]
) -> tuple[int, str, str, Recorder]:
    recorder = Recorder(answer)
    monkeypatch.setattr(cli, "post_message", recorder)
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(argv, out, err)
    return code, out.getvalue(), err.getvalue(), recorder


def test_a_tool_call_prints_the_text_the_server_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err, recorder = _run(
        monkeypatch,
        _result("Thread ID: 5b1e2c3d4e5f6071"),
        ["read_email", "--messageId", "3f9c1a2b7d4e5f60"],
    )
    assert code == 0
    assert out == "Thread ID: 5b1e2c3d4e5f6071\n"
    assert err == ""
    assert recorder.via == ["cli"]
    assert recorder.sent[0]["method"] == "tools/call"
    assert recorder.sent[0]["params"] == {
        "name": "read_email",
        "arguments": {"messageId": "3f9c1a2b7d4e5f60"},
    }


def test_flag_values_are_typed_the_way_a_json_client_would_send_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["search_emails", "--maxResults", "20", "--query", "is:unread", "--verbose", "true"]
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "maxResults": 20,
        "query": "is:unread",
        "verbose": True,
    }


def test_a_json_argument_merges_over_the_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = [
        "search_emails",
        "--query",
        "label:billing",
        "--json",
        '{"query": "is:unread", "maxResults": 5}',
    ]
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "query": "is:unread",
        "maxResults": 5,
    }


def test_a_value_that_looks_like_a_flag_must_come_after_a_double_dash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err, recorder = _run(
        monkeypatch, _result("{}"), ["search_emails", "--query", "-in:sent"]
    )
    assert code == 2
    assert out == ""
    assert "value for --query looks like a flag; put it after --" in err
    assert recorder.sent == []
    code, _, _, recorder = _run(
        monkeypatch, _result("{}"), ["search_emails", "--query", "--", "-in:sent"]
    )
    assert code == 0
    assert recorder.sent[0]["params"]["arguments"] == {"query": "-in:sent"}


def test_a_flag_without_a_value_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_emails", "--maxResults"])
    assert code == 2
    assert "missing value for --maxResults" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_emails", "--maxResults", "--"])
    assert code == 2
    assert "missing value for --maxResults" in err


def test_a_bare_word_where_a_flag_belongs_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_emails", "3f9c1a2b7d4e5f60"])
    assert code == 2
    assert "expected --name value, got 3f9c1a2b7d4e5f60" in err


def test_json_that_will_not_parse_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_emails", "--json", "{oops"])
    assert code == 2
    assert "--json is not a JSON object" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_emails", "--json", "[1]"])
    assert code == 2
    assert "--json is not a JSON object" in err


def test_a_gmail_error_text_exits_one_even_without_the_error_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for text in (
        "Error: Rate Limit Exceeded",
        "Error: Backend Error",
        "Error: Requested entity was not found.",
        "Error: missing required parameter: query",
    ):
        code, out, err, _ = _run(monkeypatch, _result(text), ["search_emails", "--query", "x"])
        assert code == 1, text
        assert out == f"{text}\n"
        assert err == ""


def test_ordinary_answers_that_mention_an_error_still_exit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "Thread ID: 5b1e2c3d4e5f6071\nSubject: Error: build failed\n\nError: see attached"
    code, out, _, _ = _run(monkeypatch, _result(body), ["read_email", "--messageId", "x"])
    assert code == 0
    assert out == body + "\n"
    code, _, _, _ = _run(
        monkeypatch, _result("No emails found matching the query"), ["search_emails"]
    )
    assert code == 0
