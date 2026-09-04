import io
from typing import Any

import pytest

from mockgithub.client import cli


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


def test_a_tool_call_prints_the_text_the_server_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    code, out, err, recorder = _run(monkeypatch, _result('{"login":"rhea-menon"}'), ["get_me"])
    assert code == 0
    assert out == '{"login":"rhea-menon"}\n'
    assert err == ""
    assert recorder.via == ["cli"]
    assert recorder.sent[0]["method"] == "tools/call"
    assert recorder.sent[0]["params"] == {"name": "get_me", "arguments": {}}


def test_flag_values_are_typed_the_way_a_json_client_would_send_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["list_issues", "--owner", "ExampleCo", "--perPage", "20", "--draft", "true"]
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "owner": "ExampleCo",
        "perPage": 20,
        "draft": True,
    }


def test_a_json_argument_merges_over_the_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = ["list_issues", "--owner", "ExampleCo", "--json", '{"state": "OPEN", "perPage": 5}']
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "owner": "ExampleCo",
        "state": "OPEN",
        "perPage": 5,
    }


def test_a_value_that_looks_like_a_flag_must_come_after_a_double_dash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err, recorder = _run(
        monkeypatch, _result("{}"), ["search_issues", "--query", "-bug"]
    )
    assert code == 2
    assert out == ""
    assert "value for --query looks like a flag; put it after --" in err
    assert recorder.sent == []
    code, _, _, recorder = _run(
        monkeypatch, _result("{}"), ["search_issues", "--query", "--", "-bug"]
    )
    assert code == 0
    assert recorder.sent[0]["params"]["arguments"] == {"query": "-bug"}


def test_a_flag_without_a_value_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--perPage"])
    assert code == 2
    assert "missing value for --perPage" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["search_issues", "--query", "--"])
    assert code == 2
    assert "missing value for --query" in err


def test_a_bare_word_where_a_flag_belongs_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "ExampleCo"])
    assert code == 2
    assert "expected --name value, got ExampleCo" in err


def test_json_that_will_not_parse_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--json", "{oops"])
    assert code == 2
    assert "--json is not a JSON object" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--json", "[1]"])
    assert code == 2
    assert "--json is not a JSON object" in err


def test_an_error_result_is_printed_and_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _result("failed to get issue: 404 Not Found []", is_error=True)
    code, out, err, _ = _run(monkeypatch, answer, ["issue_read", "--issue_number", "999"])
    assert code == 1
    assert out == "failed to get issue: 404 Not Found []\n"
    assert err == ""


def test_a_protocol_error_is_reported_on_standard_error(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Unknown tool: nope"}}
    code, out, err, _ = _run(monkeypatch, answer, ["nope"])
    assert code == 2
    assert out == ""
    assert err == "Unknown tool: nope\n"
