from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from .tool_errors import InvalidArguments

_ISO_DURATION = re.compile(
    r"(?P<sign>[-+])?P(?:(?P<years>\d+)Y)?(?:(?P<months>\d+)M)?"
    r"(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+)S)?)?"
)
_SHORT_DURATION = re.compile(r"(?P<sign>[-+])?(?P<amount>\d+)(?P<unit>[wdhms])")
_UNIT_SECONDS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
_MONTH_DAYS = 30
_YEAR_DAYS = 365


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_ts(value: str | int | float) -> datetime:
    if isinstance(value, str):
        try:
            return _utc(datetime.fromisoformat(value.strip()))
        except ValueError as error:
            raise InvalidArguments(f"not a timestamp: {value}") from error
    return datetime.fromtimestamp(float(value), tz=UTC)


def iso_ms(dt: datetime) -> str:
    moment = _utc(dt)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def iso_seconds(dt: datetime) -> str:
    return _utc(dt).strftime("%Y-%m-%dT%H:%M:%SZ")


def rfc2822(dt: datetime) -> str:
    return _utc(dt).strftime("%a, %d %b %Y %H:%M:%S +0000")


def epoch_ms(dt: datetime) -> int:
    moment = _utc(dt)
    return int(moment.replace(microsecond=0).timestamp()) * 1000 + moment.microsecond // 1000


def _duration(value: str) -> timedelta | None:
    iso = _ISO_DURATION.fullmatch(value)
    if iso is not None:
        delta = timedelta(
            weeks=int(iso["weeks"] or 0),
            days=int(iso["days"] or 0)
            + int(iso["months"] or 0) * _MONTH_DAYS
            + int(iso["years"] or 0) * _YEAR_DAYS,
            hours=int(iso["hours"] or 0),
            minutes=int(iso["minutes"] or 0),
            seconds=int(iso["seconds"] or 0),
        )
        return -delta if iso["sign"] == "-" else delta
    short = _SHORT_DURATION.fullmatch(value)
    if short is None:
        return None
    delta = timedelta(seconds=int(short["amount"]) * _UNIT_SECONDS[short["unit"]])
    return -delta if short["sign"] == "-" else delta


def resolve_relative(text: str, now: datetime) -> datetime:
    value = text.strip()
    delta = _duration(value)
    if delta is None:
        return parse_ts(value)
    return _utc(now) + delta
