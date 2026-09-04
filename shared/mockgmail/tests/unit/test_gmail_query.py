from datetime import datetime

import pytest

from mockgmail.gmail.models import Message
from mockgmail.gmail.query import matcher
from mockgmail.gmail.state import GmailState


def _keys(state: GmailState, query: str, now: datetime) -> list[str]:
    match = matcher(query, now, state.labels)
    return [message.key for message in state.messages if match(message)]


def _message(state: GmailState, key: str) -> Message:
    return next(message for message in state.messages if message.key == key)


def test_an_empty_query_matches_everything(state: GmailState, now: datetime) -> None:
    assert len(_keys(state, "", now)) == 40
    assert len(_keys(state, "   ", now)) == 40


def test_a_bare_word_is_searched_over_subject_body_and_addresses(
    state: GmailState, now: datetime
) -> None:
    assert _keys(state, "scaffolding", now) == ["alcaraz-2", "alcaraz-1"]
    assert "okonjo-3" in _keys(state, "STAVELY-WORKS", now)
    assert _keys(state, "sightline", now) == ["pat-marden-2"]


def test_a_quoted_phrase_must_appear_verbatim(state: GmailState, now: datetime) -> None:
    assert _keys(state, '"restricted view"', now) == ["pat-marden-3", "pat-marden-2"]
    assert _keys(state, '"view restricted"', now) == []


def test_from_matches_the_sender_header_case_insensitively(
    state: GmailState, now: datetime
) -> None:
    assert _keys(state, "from:okonjo", now) == ["okonjo-3", "okonjo-1"]
    assert _keys(state, "from:Hana.Okonjo@stavely-works.example", now) == ["okonjo-3", "okonjo-1"]


def test_to_and_cc_match_recipient_lists(state: GmailState, now: datetime) -> None:
    assert _keys(state, "to:pat.ryan@lowfield.example", now) == [
        "pat-bay-3",
        "pat-marden-4",
        "pat-marden-2",
    ]
    cc = _message(state, "dana-4471-4").cc[0]
    assert "dana-4471-4" in _keys(state, f"cc:{cc}", now)
    assert "dana-4471-3" not in _keys(state, f"cc:{cc}", now)


def test_subject_matches_only_the_subject(state: GmailState, now: datetime) -> None:
    assert _keys(state, "subject:sightline", now) == []
    assert _keys(state, 'subject:"lost property"', now) == ["drake-2", "drake-1"]
    assert _keys(state, "subject:CT-2209", now) == ["venkatesan-3", "venkatesan-2", "venkatesan-1"]


def test_has_attachment_and_filename_look_at_attachments(state: GmailState, now: datetime) -> None:
    assert len(_keys(state, "has:attachment", now)) == 8
    assert _keys(state, "filename:pdf from:okonjo", now) == []
    assert _keys(state, "filename:invoice-5120.pdf", now) == ["okonjo-2"]
    assert _keys(state, "filename:csv", now) == ["archive-1"]


def test_label_accepts_ids_keys_and_names(state: GmailState, now: datetime) -> None:
    billing = _keys(state, "label:billing", now)
    assert len(billing) == 12
    assert _keys(state, "label:Label_2", now) == billing
    assert _keys(state, "label:Billing", now) == billing
    assert _keys(state, "label:important", now) == ["dana-4471-5", "renn-1"]
    assert _keys(state, "label:nothing", now) == []


def test_in_selects_a_mailbox_or_everything(state: GmailState, now: datetime) -> None:
    assert len(_keys(state, "in:inbox", now)) == 27
    assert len(_keys(state, "in:sent", now)) == 13
    assert len(_keys(state, "in:anywhere", now)) == 40
    assert _keys(state, "in:trash", now) == []


def test_is_reads_the_read_starred_and_important_flags(state: GmailState, now: datetime) -> None:
    unread = _keys(state, "is:unread", now)
    assert unread == [
        "alcaraz-2",
        "alcaraz-1",
        "bounce-1",
        "ops-weekly-1",
        "maintenance-1",
        "drake-2",
    ]
    assert len(_keys(state, "is:read", now)) == 34
    assert _keys(state, "is:starred", now) == ["alcaraz-1"]
    assert _keys(state, "is:important", now) == ["dana-4471-5", "renn-1"]


def test_after_and_before_take_slash_dates_at_utc_midnight(
    state: GmailState, now: datetime
) -> None:
    assert _keys(state, "after:2026/03/02 before:2026/03/03", now) == [
        "alcaraz-1",
        "bounce-1",
        "bergstrom-2",
        "ops-weekly-1",
    ]
    assert _keys(state, "after:2026-03-03", now) == ["alcaraz-2", "archive-1"]
    assert _keys(state, "older:2025/06/03", now) == ["pat-marden-3", "pat-marden-2", "pat-marden-1"]
    assert _keys(state, "newer:2026/03/03", now) == ["alcaraz-2", "archive-1"]
    assert _keys(state, "after:someday", now) == []
    assert _keys(state, "before:never", now) == []
    assert _keys(state, "before:2026/02/30", now) == []


def test_newer_than_and_older_than_resolve_against_the_scenario_clock(
    state: GmailState, now: datetime
) -> None:
    assert _keys(state, "newer_than:2d", now) == ["alcaraz-2", "archive-1", "alcaraz-1"]
    assert _keys(state, "newer_than:48h", now) == _keys(state, "newer_than:2d", now)
    assert len(_keys(state, "older_than:1w", now)) == 27
    assert len(_keys(state, "older_than:1m", now)) == 9
    assert _keys(state, "older_than:1y", now) == []
    assert _keys(state, "newer_than:soon", now) == []
    assert _keys(state, "older_than:3x", now) == []


def test_a_leading_dash_negates_a_term(state: GmailState, now: datetime) -> None:
    assert len(_keys(state, "-in:sent", now)) == 27
    assert len(_keys(state, "in:inbox -label:support -label:billing -label:newsletters", now)) == 1
    assert _keys(state, '-"restricted view" from:pat.ryan subject:Marden', now) == ["pat-marden-1"]


def test_or_joins_neighbouring_terms_before_the_implicit_and(
    state: GmailState, now: datetime
) -> None:
    assert _keys(state, "from:drake OR from:alcaraz is:unread", now) == [
        "alcaraz-2",
        "alcaraz-1",
        "drake-2",
    ]
    assert _keys(state, "is:starred OR is:important", now) == ["alcaraz-1", "dana-4471-5", "renn-1"]
    assert _keys(state, "{is:starred is:important}", now) == ["alcaraz-1", "dana-4471-5", "renn-1"]
    assert _keys(state, "(from:drake OR from:alcaraz) is:starred", now) == ["alcaraz-1"]
    assert _keys(state, "-(from:drake OR from:alcaraz) is:unread", now) == [
        "bounce-1",
        "ops-weekly-1",
        "maintenance-1",
    ]


def test_an_unknown_operator_is_searched_as_plain_text(state: GmailState, now: datetime) -> None:
    assert _keys(state, "booking:QB-3041", now) == []
    assert _keys(state, "QB-3041", now) != []


def test_unbalanced_groups_and_dangling_or_are_tolerated(state: GmailState, now: datetime) -> None:
    assert _keys(state, "(is:starred", now) == ["alcaraz-1"]
    assert _keys(state, "is:starred)", now) == ["alcaraz-1"]
    assert _keys(state, "OR is:starred OR", now) == ["alcaraz-1"]
    assert _keys(state, '"unterminated', now) == []
    assert _keys(state, "-", now) == _keys(state, "", now)


@pytest.mark.parametrize("query", ["from:", "subject:", "label:", "in:", "is:", "has:"])
def test_an_operator_without_a_value_matches_nothing(
    state: GmailState, now: datetime, query: str
) -> None:
    assert _keys(state, query, now) == []
