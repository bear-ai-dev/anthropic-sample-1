from datetime import datetime

from mockgmail.gmail.format import confirmation, email_text, labels_text, search_result
from mockgmail.gmail.load import load
from mockgmail.gmail.models import Attachment, Label, Message
from mockgmail.gmail.state import GmailState
from mockgmail.tests.require import require


def _message(state: GmailState, key: str) -> Message:
    return require(next((item for item in state.messages if item.key == key), None))


def test_a_search_lists_id_subject_sender_and_date_per_message(state: GmailState) -> None:
    first = _message(state, "okonjo-1")
    second = _message(state, "pat-marden-1")
    assert search_result([first, second]) == (
        f"ID: {first.id}\n"
        "Subject: Copy of invoice 5120 for our records\n"
        "From: Hana Okonjo <hana.okonjo@stavely-works.example>\n"
        "Date: Fri, 20 Feb 2026 13:05:00 +0000\n"
        "\n"
        f"ID: {second.id}\n"
        "Subject: Seat block for the Marden Hall run\n"
        "From: Pat Ryan <pat.ryan@lowfield.example>\n"
        "Date: Mon, 02 Jun 2025 09:00:00 +0000\n"
    )


def test_a_search_with_no_matches_says_so() -> None:
    assert search_result([]) == "No emails found matching the query"


def test_an_email_renders_its_headers_and_body(state: GmailState) -> None:
    message = _message(state, "dana-4471-4")
    rendered = email_text(message)
    assert rendered.startswith(
        f"Thread ID: {message.thread_id}\n"
        "Subject: Re: Invoice 4471 - charged twice?\n"
        "From: Lowfield Desk <inbox@desk.internal>\n"
        f"To: {', '.join(message.to)}\n"
        "Date: Thu, 12 Jun 2025 16:52:00 +0000\n"
        "\n"
    )
    assert rendered.endswith(message.body_text)
    assert "Attachments" not in rendered


def test_an_email_with_attachments_lists_them_after_the_body(state: GmailState) -> None:
    message = _message(state, "okonjo-2")
    attachment = message.attachments[0]
    assert email_text(message).endswith(
        f"{message.body_text}\n\nAttachments (1):\n"
        f"- invoice-5120.pdf (application/pdf, 86 KB, ID: {attachment.id})"
    )


def test_attachment_sizes_round_half_up_to_whole_kilobytes(now: datetime) -> None:
    attachments = tuple(
        Attachment(
            id=f"a{index}",
            key=f"a{index}",
            filename=f"f{index}",
            mime_type="x",
            size=size,
            data_b64=None,
        )
        for index, size in enumerate((1536, 512, 511, 0))
    )
    message = Message(
        id="m",
        key="m",
        thread_id="t",
        thread_key="t",
        message_id="",
        sender="a",
        to=("b",),
        cc=(),
        subject="s",
        date=now,
        label_ids=(),
        body_text="body",
        body_html=None,
        in_reply_to=None,
        references=(),
        attachments=attachments,
    )
    assert email_text(message).endswith(
        "\n\nAttachments (4):\n"
        "- f0 (x, 2 KB, ID: a0)\n- f1 (x, 1 KB, ID: a1)\n"
        "- f2 (x, 0 KB, ID: a2)\n- f3 (x, 0 KB, ID: a3)"
    )


def test_an_email_without_a_text_body_falls_back_to_its_html(now: datetime) -> None:
    section = {"threads": [{"key": "t", "messages": [{"key": "m", "body_html": "<p>Hi</p>"}]}]}
    message = load(section, 7, now).messages[0]
    assert email_text(message).endswith("\n\n<p>Hi</p>")
    assert "To: \n" in email_text(message)


def test_labels_are_grouped_by_type_with_a_count_line(state: GmailState) -> None:
    rendered = labels_text(list(state.labels))
    assert rendered.startswith(
        "Found 11 labels (8 system, 3 user):\n\nSystem Labels:\n"
        "ID: INBOX\nName: INBOX\nType: system\n\nID: SENT\nName: SENT\nType: system\n\n"
    )
    assert rendered.endswith(
        "ID: DRAFT\nName: DRAFT\nType: system\n\nUser Labels:\n"
        "ID: Label_1\nName: Support\nType: user\n\n"
        "ID: Label_2\nName: Billing\nType: user\n\n"
        "ID: Label_3\nName: Newsletters\nType: user\n"
    )


def test_a_mailbox_without_user_labels_still_prints_the_user_heading() -> None:
    labels = [Label(id="INBOX", key="INBOX", name="INBOX", type="system")]
    assert labels_text(labels) == (
        "Found 1 labels (1 system, 0 user):\n\nSystem Labels:\n"
        "ID: INBOX\nName: INBOX\nType: system\n\nUser Labels:\n"
    )


def test_a_download_confirmation_names_the_file_its_size_and_its_path() -> None:
    assert confirmation("invoice-5120.pdf", 88214, "/tmp/downloads/invoice-5120.pdf") == (
        "Attachment downloaded successfully:\n"
        "File: invoice-5120.pdf\n"
        "Size: 88214 bytes\n"
        "Saved to: /tmp/downloads/invoice-5120.pdf"
    )
