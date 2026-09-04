import base64
import hashlib
import re
from datetime import datetime

import pytest

from mockgmail.clock import parse_ts
from mockgmail.gmail.content import attachment_bytes
from mockgmail.gmail.load import load
from mockgmail.gmail.models import Message
from mockgmail.gmail.state import GmailState
from mockgmail.ids import hex_for
from mockgmail.scenario import ScenarioError
from mockgmail.tests.require import require

SYSTEM = ["INBOX", "SENT", "UNREAD", "STARRED", "IMPORTANT", "TRASH", "SPAM", "DRAFT"]


def _find(state: GmailState, key: str) -> Message:
    return require(next((item for item in state.messages if item.key == key), None))


def test_the_profile_address_is_carried_by_the_state(state: GmailState) -> None:
    assert state.email_address == "inbox@desk.internal"


def test_message_and_thread_ids_are_sixteen_hex_from_the_seeded_key(state: GmailState) -> None:
    message = _find(state, "pat-marden-1")
    assert message.id == hex_for(7, "gmail", "message", "pat-marden-1", 16)
    assert message.thread_id == hex_for(7, "gmail", "thread", "t-pat-marden-seat-block", 16)
    assert re.fullmatch(r"[0-9a-f]{16}", message.id)
    assert _find(state, "pat-marden-3").thread_id == message.thread_id
    assert message.thread_key == "t-pat-marden-seat-block"


def test_an_attachment_id_is_the_base64url_of_forty_eight_hex(state: GmailState) -> None:
    attachment = _find(state, "okonjo-2").attachments[0]
    expected = base64.urlsafe_b64encode(
        hex_for(7, "gmail", "attachment", "att-invoice-5120", 48).encode()
    ).decode()
    assert attachment.id == expected
    assert attachment.key == "att-invoice-5120"
    assert attachment.filename == "invoice-5120.pdf"
    assert attachment.mime_type == "application/pdf"
    assert attachment.size == 88214
    assert attachment.data_b64 is None


def test_system_labels_always_exist_and_user_labels_are_numbered_in_scenario_order(
    state: GmailState,
) -> None:
    assert [label.id for label in state.labels if label.type == "system"] == SYSTEM
    user = [(label.id, label.key, label.name) for label in state.labels if label.type == "user"]
    assert user == [
        ("Label_1", "support", "Support"),
        ("Label_2", "billing", "Billing"),
        ("Label_3", "newsletters", "Newsletters"),
    ]
    assert [label.name for label in state.labels if label.type == "system"] == SYSTEM


def test_a_message_carries_its_headers_labels_and_thread_fields(state: GmailState) -> None:
    message = _find(state, "pat-marden-3")
    assert message.sender == "Pat Ryan <pat.ryan@lowfield.example>"
    assert message.to == ("inbox@desk.internal",)
    assert message.cc == ()
    assert message.subject == "Re: Seat block for the Marden Hall run"
    assert message.date == parse_ts("2025-06-02T16:20:00Z")
    assert message.label_ids == ("INBOX", "Label_1")
    assert message.body_text.startswith("> One thing worth knowing")
    assert message.body_html is None
    assert message.message_id == "<pr-20250602-3@lowfield.example>"
    assert message.in_reply_to == "<h-old-a2@desk.internal>"
    assert message.references == ("<h-old-a1@lowfield.example>", "<h-old-a2@desk.internal>")
    assert _find(state, "dana-4471-4").cc != ()
    assert _find(state, "ops-weekly-1").body_html is not None


def test_messages_are_sorted_newest_first(state: GmailState) -> None:
    dates = [message.date for message in state.messages]
    assert dates == sorted(dates, reverse=True)
    assert state.messages[0].key == "alcaraz-2"
    assert len(state.messages) == 40


def test_messages_and_attachments_are_found_by_their_opaque_ids(state: GmailState) -> None:
    message = _find(state, "okonjo-2")
    assert state.message(message.id) is message
    assert state.message("0000000000000000") is None
    attachment = message.attachments[0]
    assert state.attachment(message, attachment.id) is attachment
    assert state.attachment(message, "nope") is None
    assert require(state.message(message.id)).attachments == (attachment,)


def test_labels_are_found_by_id_name_or_key(state: GmailState) -> None:
    assert require(state.label("Label_1")).name == "Support"
    assert require(state.label("support")).id == "Label_1"
    assert require(state.label("Billing")).id == "Label_2"
    assert require(state.label("inbox")).id == "INBOX"
    assert state.label("nothing") is None


def test_the_id_map_covers_messages_attachments_and_labels(state: GmailState) -> None:
    id_map = state.id_map()
    message = _find(state, "okonjo-2")
    assert id_map["messages"]["okonjo-2"] == {"id": message.id, "threadId": message.thread_id}
    assert id_map["attachments"]["att-invoice-5120"] == message.attachments[0].id
    assert id_map["labels"]["support"] == "Label_1"
    assert id_map["labels"]["INBOX"] == "INBOX"
    assert len(id_map["messages"]) == 40


def test_an_empty_section_still_has_the_system_labels(now: datetime) -> None:
    state = load({}, 7, now)
    assert state.email_address == ""
    assert state.messages == ()
    assert [label.id for label in state.labels] == SYSTEM


def test_a_message_that_names_an_unknown_label_is_refused(now: datetime) -> None:
    section = {"threads": [{"key": "t", "messages": [{"key": "m", "labels": ["INBOX", "nope"]}]}]}
    with pytest.raises(ScenarioError, match="message m names an unknown label: nope"):
        load(section, 7, now)


def test_a_message_without_optional_fields_gets_defaults(now: datetime) -> None:
    section = {"threads": [{"key": "t", "messages": [{"key": "m"}]}]}
    message = load(section, 7, now).messages[0]
    assert message.sender == ""
    assert message.to == ()
    assert message.subject == ""
    assert message.date == now
    assert message.label_ids == ()
    assert message.body_text == ""
    assert message.in_reply_to is None
    assert message.references == ()
    assert message.message_id == ""
    assert message.attachments == ()


def test_inline_attachment_data_is_kept_and_sized(now: datetime) -> None:
    data = base64.b64encode(b"hello world").decode()
    section = {
        "threads": [
            {
                "key": "t",
                "messages": [
                    {
                        "key": "m",
                        "attachments": [{"key": "a", "filename": "hi.txt", "data_b64": data}],
                    }
                ],
            }
        ]
    }
    attachment = load(section, 7, now).messages[0].attachments[0]
    assert attachment.data_b64 == data
    assert attachment.size == 11
    assert attachment.mime_type == "application/octet-stream"
    assert attachment_bytes(attachment) == b"hello world"


def test_size_only_attachments_yield_deterministic_filler_of_the_declared_size(
    state: GmailState,
) -> None:
    attachment = _find(state, "okonjo-2").attachments[0]
    filler = attachment_bytes(attachment)
    assert len(filler) == 88214
    assert filler[:32] == hashlib.sha256(b"att-invoice-5120").digest()
    assert filler[32:64] == filler[:32]
    assert filler == attachment_bytes(attachment)
