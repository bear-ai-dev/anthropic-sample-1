import re
import uuid

from mocklinear.ids import hex_for, number_for, stable_digest, uuid_for


def test_uuid_for_is_stable_across_calls_and_differs_across_seeds() -> None:
    a = uuid_for(7, "linear", "issue", "ENG-1")
    b = uuid_for(7, "linear", "issue", "ENG-1")
    assert a == b
    assert a != uuid_for(41, "linear", "issue", "ENG-1")
    assert re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", a)


def test_the_digest_is_forty_lowercase_hex_characters_of_the_seeded_key() -> None:
    digest = stable_digest(7, "linear", "issue", "ENG-1")
    assert re.fullmatch(r"[0-9a-f]{40}", digest)
    assert digest != stable_digest(7, "linear", "issue", "ENG-2")
    assert digest != stable_digest(7, "linear", "comment", "ENG-1")
    assert digest != stable_digest(7, "github", "issue", "ENG-1")


def test_two_kinds_of_the_same_key_never_share_an_identifier() -> None:
    assert uuid_for(7, "linear", "team", "WEB") != uuid_for(7, "linear", "project", "WEB")


def test_an_identifier_is_a_valid_version_four_uuid() -> None:
    for key in ("ENG-1", "WEB-611", "dana", "door-ops"):
        value = uuid_for(7, "linear", "issue", key)
        assert uuid.UUID(value).version == 4
        assert value[14] == "4"
        assert value[19] in "89ab"
        assert str(uuid.UUID(value)) == value


def test_hex_for_cuts_or_repeats_the_digest_to_the_requested_length() -> None:
    digest = stable_digest(7, "linear", "attachment", "a-spec")
    assert hex_for(7, "linear", "attachment", "a-spec", 16) == digest[:16]
    assert hex_for(7, "linear", "attachment", "a-spec", 40) == digest
    assert hex_for(7, "linear", "attachment", "a-spec", 48) == (digest + digest)[:48]
    assert hex_for(41, "linear", "attachment", "a-spec", 16) != digest[:16]


def test_number_for_is_a_positive_integer_with_the_requested_digits() -> None:
    number = number_for(7, "linear", "user", "u-dana")
    assert number == number_for(7, "linear", "user", "u-dana")
    assert 100_000_000 <= number < 1_000_000_000
    assert number != number_for(41, "linear", "user", "u-dana")
    assert 1000 <= number_for(7, "linear", "user", "u-dana", digits=4) < 10000
