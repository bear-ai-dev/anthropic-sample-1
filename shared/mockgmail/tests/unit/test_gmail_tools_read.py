import base64
import hashlib
import json
from typing import Any

import pytest

from mockgmail.engine import Engine
from mockgmail.gmail.format import email_text, labels_text
from mockgmail.gmail.models import Message
from mockgmail.gmail.state import GmailState
from mockgmail.journal import Journal
from mockgmail.scenario import validate_scenario
from mockgmail.tests.require import require


def _engine(scenario: dict[str, Any]) -> Engine:
    return Engine(validate_scenario(scenario), 7, Journal(None))


def _text(engine: Engine, tool: str, arguments: dict[str, Any]) -> str:
    result = engine.call("gmail", tool, arguments, "cli")
    assert not result.is_error
    assert len(result.content) == 1
    return str(result.content[0]["text"])


def _message(state: GmailState, key: str) -> Message:
    return require(next((item for item in state.messages if item.key == key), None))


def test_read_email_renders_the_message_by_its_opaque_id(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    message = _message(engine.world.gmail, "okonjo-2")
    assert _text(engine, "read_email", {"messageId": message.id}) == email_text(message)


@pytest.mark.parametrize("message_id", ["0000000000000000", "okonjo-2", ""])
def test_read_email_answers_the_same_not_found_for_any_unknown_id(
    scenario: dict[str, Any], message_id: str
) -> None:
    assert _text(_engine(scenario), "read_email", {"messageId": message_id}) == (
        "Error: Requested entity was not found."
    )


def test_read_email_requires_a_message_id(scenario: dict[str, Any]) -> None:
    assert _text(_engine(scenario), "read_email", {}) == (
        "Error: missing required parameter: messageId"
    )


def test_list_email_labels_renders_every_label(scenario: dict[str, Any]) -> None:
    engine = _engine(scenario)
    assert _text(engine, "list_email_labels", {}) == labels_text(list(engine.world.gmail.labels))
    assert _text(engine, "list_email_labels", {"anything": 1}).startswith("Found 11 labels")


def test_download_attachment_answers_a_marked_payload_for_the_client(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    message = _message(engine.world.gmail, "okonjo-2")
    attachment = message.attachments[0]
    text = _text(
        engine,
        "download_attachment",
        {"messageId": message.id, "attachmentId": attachment.id},
    )
    payload = json.loads(text)["mockgmail_attachment"]
    assert payload["filename"] == "invoice-5120.pdf"
    assert payload["mimeType"] == "application/pdf"
    assert payload["size"] == 88214
    assert payload["savePath"] is None
    data = base64.b64decode(payload["data_b64"])
    assert len(data) == 88214
    assert data[:32] == hashlib.sha256(b"att-invoice-5120").digest()


def test_download_attachment_carries_the_requested_path_and_name(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    message = _message(engine.world.gmail, "halloran-2")
    text = _text(
        engine,
        "download_attachment",
        {
            "messageId": message.id,
            "attachmentId": message.attachments[0].id,
            "savePath": "/tmp/downloads",
            "filename": "plan.pdf",
        },
    )
    payload = json.loads(text)["mockgmail_attachment"]
    assert payload["savePath"] == "/tmp/downloads"
    assert payload["filename"] == "plan.pdf"


def test_download_attachment_is_not_found_for_a_wrong_message_or_attachment(
    scenario: dict[str, Any],
) -> None:
    engine = _engine(scenario)
    message = _message(engine.world.gmail, "halloran-2")
    other = _message(engine.world.gmail, "okonjo-2")
    missing = "Error: Requested entity was not found."
    assert (
        _text(
            engine,
            "download_attachment",
            {"messageId": "0000000000000000", "attachmentId": message.attachments[0].id},
        )
        == missing
    )
    assert (
        _text(
            engine,
            "download_attachment",
            {"messageId": message.id, "attachmentId": other.attachments[0].id},
        )
        == missing
    )
    assert _text(engine, "download_attachment", {"messageId": message.id}) == (
        "Error: missing required parameter: attachmentId"
    )


def test_a_throttle_fault_reads_as_a_gmail_rate_limit(scenario: dict[str, Any]) -> None:
    scenario["faults"] = {"rules": [{"service": "gmail", "throttle_every": 1}]}
    result = _engine(scenario).call("gmail", "list_email_labels", {}, "cli")
    assert not result.is_error
    assert result.content[0]["text"] == "Error: Rate Limit Exceeded"
