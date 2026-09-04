import io
import runpy
import sys
from typing import Any

import pytest

from mockgmail import client
from mockgmail.client import cli, stdio


def test_no_arguments_speaks_the_protocol_over_stdio(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stdio, "post_message", lambda message, via: None)
    out = io.StringIO()
    assert client.dispatch([], io.StringIO(""), out, io.StringIO()) == 0
    assert "gmail tools" in out.getvalue()


def test_a_leading_service_name_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def send(message: dict[str, Any], via: str) -> Any:
        seen.append(message)
        return {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}

    monkeypatch.setattr(cli, "post_message", send)
    assert (
        client.dispatch(["gmail", "list_email_labels"], io.StringIO(), io.StringIO(), io.StringIO())
        == 0
    )
    assert seen[0]["params"]["name"] == "list_email_labels"


def test_the_client_entry_point_exits_with_the_dispatch_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["gmail", "list_email_labels"])
    monkeypatch.setattr(client, "dispatch", lambda argv, stdin, stdout, stderr: 7)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("mockgmail.client", run_name="__main__")
    assert exit_info.value.code == 7
