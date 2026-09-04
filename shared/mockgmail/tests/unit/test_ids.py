import re
import uuid

from mockgmail.ids import hex_for, number_for, stable_digest, uuid_for


def test_uuid_for_is_stable_across_calls_and_differs_across_seeds() -> None:
    a = uuid_for(7, "gmail", "issue", "ENG-1")
    b = uuid_for(7, "gmail", "issue", "ENG-1")
    assert a == b
    assert a != uuid_for(41, "gmail", "issue", "ENG-1")
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", a)


def test_the_digest_is_forty_lowercase_hex_characters_of_the_seeded_key() -> None:
    digest = stable_digest(7, "gmail", "issue", "ENG-1")
    assert re.fullmatch(r"[0-9a-f]{40}", digest)
    assert digest != stable_digest(7, "gmail", "issue", "ENG-2")
    assert digest != stable_digest(7, "gmail", "comment", "ENG-1")
    assert digest != stable_digest(7, "github", "issue", "ENG-1")


def test_two_kinds_of_the_same_key_never_share_an_identifier() -> None:
    assert uuid_for(7, "gmail", "team", "WEB") != uuid_for(7, "gmail", "project", "WEB")


def test_hex_for_is_a_prefix_of_the_digest_at_the_requested_length() -> None:
    short = hex_for(7, "gmail", "message", "pat-marden-1", 16)
    assert re.fullmatch(r"[0-9a-f]{16}", short)
    assert short == stable_digest(7, "gmail", "message", "pat-marden-1")[:16]
    assert (
        hex_for(7, "gmail", "message", "pat-marden-1", 48)
        == (
            stable_digest(7, "gmail", "message", "pat-marden-1")
            + stable_digest(7, "gmail", "message", "pat-marden-1")
        )[:48]
    )
    assert hex_for(41, "gmail", "message", "pat-marden-1", 16) != short


def test_an_identifier_is_a_valid_version_four_uuid() -> None:
    for key in ("pat-marden-1", "INBOX", "thread-1", "a-invoice"):
        value = uuid_for(7, "gmail", "message", key)
        assert uuid.UUID(value).version == 4
        assert value[14] == "4"
        assert value[19] in "89ab"
        assert str(uuid.UUID(value)) == value


def test_number_for_is_a_positive_integer_with_the_requested_digits() -> None:
    number = number_for(7, "gmail", "message", "pat-marden-1")
    assert number == number_for(7, "gmail", "message", "pat-marden-1")
    assert 100_000_000 <= number < 1_000_000_000
    assert number != number_for(41, "gmail", "message", "pat-marden-1")
    assert 1000 <= number_for(7, "gmail", "message", "pat-marden-1", digits=4) < 10000
