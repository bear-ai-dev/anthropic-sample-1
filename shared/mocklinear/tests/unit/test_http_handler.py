from typing import Any

import pytest

from mocklinear.engine import Engine
from mocklinear.http_handler import make_handler
from mocklinear.journal import Journal
from mocklinear.scenario import validate_scenario


def _handler(scenario: dict[str, Any]) -> Any:
    engine = Engine(validate_scenario(scenario), 7, Journal(None))
    handler_class = make_handler(engine, None)
    handler = handler_class.__new__(handler_class)
    handler.client_address = ("127.0.0.1", 4570)
    return handler


def test_the_daemon_logs_nothing_unless_the_environment_asks_for_it(
    scenario: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    handler = _handler(scenario)
    handler.log_message("%s", "quiet")
    assert capsys.readouterr().err == ""
    monkeypatch.setenv("MOCKLINEAR_VERBOSE", "1")
    handler.log_message("%s", "noisy")
    assert "noisy" in capsys.readouterr().err
