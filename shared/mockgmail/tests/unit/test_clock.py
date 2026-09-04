from datetime import UTC, datetime

import pytest

from mockgmail.clock import epoch_ms, iso_ms, iso_seconds, parse_ts, resolve_relative, rfc2822
from mockgmail.tool_errors import InvalidArguments


def test_relative_minus_one_week_resolves_against_the_scenario_clock(now: datetime) -> None:
    assert resolve_relative("-P1W", now) == parse_ts("2026-02-25T10:00:00Z")
    assert resolve_relative("7d", now) == parse_ts("2026-03-11T10:00:00Z")


def test_relative_day_hour_and_minute_forms_shift_in_both_directions(now: datetime) -> None:
    assert resolve_relative("P2D", now) == parse_ts("2026-03-06T10:00:00Z")
    assert resolve_relative("-PT12H", now) == parse_ts("2026-03-03T22:00:00Z")
    assert resolve_relative("PT1H30M15S", now) == parse_ts("2026-03-04T11:30:15Z")
    assert resolve_relative("2h", now) == parse_ts("2026-03-04T12:00:00Z")
    assert resolve_relative("-30m", now) == parse_ts("2026-03-04T09:30:00Z")
    assert resolve_relative("-1w", now) == parse_ts("2026-02-25T10:00:00Z")
    assert resolve_relative("45s", now) == parse_ts("2026-03-04T10:00:45Z")


def test_a_text_that_is_not_a_duration_is_parsed_as_an_absolute_timestamp(now: datetime) -> None:
    assert resolve_relative("2026-01-01", now) == parse_ts("2026-01-01T00:00:00Z")
    assert resolve_relative(" 2026-01-02T03:04:05Z ", now) == parse_ts("2026-01-02T03:04:05Z")


def test_parse_ts_normalises_offsets_dates_and_epoch_seconds_to_utc() -> None:
    assert parse_ts("2026-03-04T12:00:00+02:00") == parse_ts("2026-03-04T10:00:00Z")
    assert parse_ts("2026-03-04") == parse_ts("2026-03-04T00:00:00Z")
    assert parse_ts("2026-03-04T10:00:00") == parse_ts("2026-03-04T10:00:00Z")
    assert parse_ts(1772618400) == parse_ts("2026-03-04T10:00:00Z")
    assert parse_ts(1772618400.5) == parse_ts("2026-03-04T10:00:00.500Z")
    assert parse_ts("2026-03-04T10:00:00Z").tzinfo == UTC


def test_a_value_that_is_not_a_timestamp_names_itself_in_the_error() -> None:
    with pytest.raises(InvalidArguments, match="not a timestamp: last tuesday"):
        parse_ts("last tuesday")


def test_each_timestamp_format_is_rendered_from_one_instant(now: datetime) -> None:
    assert iso_ms(now) == "2026-03-04T10:00:00.000Z"
    assert iso_ms(parse_ts("2026-03-04T10:00:00.123456Z")) == "2026-03-04T10:00:00.123Z"
    assert iso_seconds(now) == "2026-03-04T10:00:00Z"


def test_epoch_milliseconds_are_exact_for_a_sub_second_instant() -> None:
    assert epoch_ms(parse_ts("2004-01-11T00:00:00.501Z")) == 1073779200501
    assert epoch_ms(parse_ts("1970-01-01T00:00:01.500Z")) == 1500


def test_a_naive_datetime_is_read_as_utc_by_every_formatter() -> None:
    naive = datetime(2026, 3, 4, 10, 0, 0)
    assert iso_seconds(naive) == "2026-03-04T10:00:00Z"
    assert iso_ms(naive) == "2026-03-04T10:00:00.000Z"
    assert epoch_ms(naive) == 1772618400000


def test_the_gmail_date_header_is_rendered_in_rfc_2822_form(now: datetime) -> None:
    assert rfc2822(now) == "Wed, 04 Mar 2026 10:00:00 +0000"
    assert rfc2822(parse_ts("2025-06-02T09:00:00+02:00")) == "Mon, 02 Jun 2025 07:00:00 +0000"
    assert rfc2822(datetime(2026, 3, 4, 10, 0, 0)) == "Wed, 04 Mar 2026 10:00:00 +0000"


def test_months_and_years_are_accepted_as_thirty_and_three_hundred_sixty_five_days(
    now: datetime,
) -> None:
    assert resolve_relative("-P1M", now) == parse_ts("2026-02-02T10:00:00Z")
    assert resolve_relative("P1M", now) == parse_ts("2026-04-03T10:00:00Z")
    assert resolve_relative("-P2Y", now) == parse_ts("2024-03-04T10:00:00Z")


def test_a_duration_may_combine_years_months_weeks_days_and_time(now: datetime) -> None:
    assert resolve_relative("-P1Y2M1W1DT2H", now) == parse_ts("2024-12-26T08:00:00Z")
    assert resolve_relative("P1MT30M", now) == parse_ts("2026-04-03T10:30:00Z")
