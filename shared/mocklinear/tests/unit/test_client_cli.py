import io
from typing import Any

import pytest

from mocklinear.client import cli
from mocklinear.client.http_client import DaemonUnreachable, ServiceUnavailable


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
        monkeypatch, _result('{"identifier": "WEB-611"}'), ["get_issue", "--id", "WEB-611"]
    )
    assert code == 0
    assert out == '{"identifier": "WEB-611"}\n'
    assert err == ""
    assert recorder.via == ["cli"]
    assert recorder.sent[0]["method"] == "tools/call"
    assert recorder.sent[0]["params"] == {"name": "get_issue", "arguments": {"id": "WEB-611"}}


def test_flag_values_are_typed_the_way_a_json_client_would_send_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    argv = ["list_issues", "--limit", "20", "--assignee", "me", "--archived", "true"]
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "limit": 20,
        "assignee": "me",
        "archived": True,
    }


def test_a_json_argument_merges_over_the_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    argv = ["list_issues", "--team", "WEB", "--json", '{"state": "started", "limit": 5}']
    _, _, _, recorder = _run(monkeypatch, _result("{}"), argv)
    assert recorder.sent[0]["params"]["arguments"] == {
        "team": "WEB",
        "state": "started",
        "limit": 5,
    }


def test_a_value_that_looks_like_a_flag_must_come_after_a_double_dash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, out, err, recorder = _run(
        monkeypatch, _result("{}"), ["list_issues", "--updatedAt", "-P1W"]
    )
    assert code == 2
    assert out == ""
    assert "value for --updatedAt looks like a flag; put it after --" in err
    assert recorder.sent == []
    code, _, _, recorder = _run(
        monkeypatch, _result("{}"), ["list_issues", "--updatedAt", "--", "-P1W"]
    )
    assert code == 0
    assert recorder.sent[0]["params"]["arguments"] == {"updatedAt": "-P1W"}


def test_a_flag_without_a_value_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--limit"])
    assert code == 2
    assert "missing value for --limit" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--limit", "--"])
    assert code == 2
    assert "missing value for --limit" in err


def test_a_bare_word_where_a_flag_belongs_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "WEB-611"])
    assert code == 2
    assert "expected --name value, got WEB-611" in err


def test_json_that_will_not_parse_is_a_usage_error(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--json", "{oops"])
    assert code == 2
    assert "--json is not a JSON object" in err
    code, _, err, _ = _run(monkeypatch, _result("{}"), ["list_issues", "--json", "[1]"])
    assert code == 2
    assert "--json is not a JSON object" in err


def test_an_error_result_is_printed_and_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = _result("Entity not found: Issue - Could not find referenced Issue.", is_error=True)
    code, out, err, _ = _run(monkeypatch, answer, ["get_issue", "--id", "WEB-999"])
    assert code == 1
    assert out == "Entity not found: Issue - Could not find referenced Issue.\n"
    assert err == ""


def test_a_protocol_error_is_reported_on_standard_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer = {"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Unknown tool: nope"}}
    code, out, err, _ = _run(monkeypatch, answer, ["nope"])
    assert code == 2
    assert out == ""
    assert err == "Unknown tool: nope\n"


def test_the_tool_list_prints_a_name_a_description_and_a_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {
                    "name": "get_issue",
                    "description": "Get one issue.",
                    "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}},
                }
            ]
        },
    }
    code, out, err, recorder = _run(monkeypatch, listing, ["tools"])
    assert code == 0
    assert err == ""
    assert out.startswith("get_issue: Get one issue.\n")
    assert '  "type": "object"' in out
    assert recorder.sent[0]["method"] == "tools/list"


def test_a_daemon_that_is_not_running_is_reported_plainly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = DaemonUnreachable("mocklinear daemon not reachable at http://127.0.0.1:4570")
    code, out, err, _ = _run(monkeypatch, failure, ["list_issues"])
    assert code == 2
    assert out == ""
    assert err == "mocklinear daemon not reachable at http://127.0.0.1:4570\n"


def test_a_daemon_without_the_linear_service_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    code, _, err, _ = _run(monkeypatch, ServiceUnavailable("unknown service: linear"), ["tools"])
    assert code == 2
    assert err == "linear is not available here\n"


def test_an_empty_answer_is_reported_rather_than_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, _, err, _ = _run(monkeypatch, None, ["list_issues"])
    assert code == 2
    assert err == "the daemon answered nothing\n"


def test_every_content_block_is_printed_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
                {"type": "image", "data": "ignored"},
            ]
        },
    }
    code, out, _, _ = _run(monkeypatch, answer, ["list_issues"])
    assert code == 0
    assert out == "first\nsecond\n"
