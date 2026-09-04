from __future__ import annotations

import hashlib
import json
from typing import Any

from .clock import parse_ts
from .tool_errors import InvalidArguments

SCENARIO_VERSION = 1
SERVICE = "linear"
_TOP_LEVEL = ("version", "clock", "faults", SERVICE)


class ScenarioError(ValueError):
    pass


def validate_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    for key in raw:
        if key not in _TOP_LEVEL:
            raise ScenarioError(f"unknown top-level key: {key}")
    for key in ("version", "clock"):
        if key not in raw:
            raise ScenarioError(f"missing top-level key: {key}")
    if raw["version"] != SCENARIO_VERSION:
        raise ScenarioError(f"unsupported scenario version: {raw['version']}")
    try:
        parse_ts(raw["clock"])
    except InvalidArguments as error:
        raise ScenarioError(f"clock is not a timestamp: {raw['clock']}") from error
    validated = dict(raw)
    validated.setdefault("faults", {})
    validated.setdefault(SERVICE, {})
    return validated


def load_scenario(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ScenarioError(f"scenario is not an object: {path}")
    return validate_scenario(raw)


def scenario_sha256(raw: dict[str, Any]) -> str:
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
