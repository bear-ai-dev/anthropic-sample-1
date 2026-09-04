from __future__ import annotations

import argparse
import json

from .gmail.address import address_of
from .gmail.state import GmailState
from .scenario import ScenarioError, load_scenario
from .world import World


def _keys(state: GmailState) -> dict[str, set[str]]:
    attachments = [item for message in state.messages for item in message.attachments]
    return {
        "thread key": {message.thread_key for message in state.messages},
        "message key": {message.key for message in state.messages},
        "message id": {message.message_id for message in state.messages if message.message_id},
        "subject": {message.subject for message in state.messages if message.subject},
        "sender address": {address_of(message.sender) for message in state.messages},
        "attachment key": {attachment.key for attachment in attachments},
        "attachment filename": {attachment.filename for attachment in attachments},
    }


def _collisions(worlds: list[World]) -> list[str]:
    maps = [_keys(world.gmail) for world in worlds]
    lines: list[str] = []
    for index, first in enumerate(maps):
        for second in maps[index + 1 :]:
            for kind, values in first.items():
                lines.extend(f"shared {kind}: {value}" for value in sorted(values & second[kind]))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mockgmail.check")
    parser.add_argument("scenarios", nargs="+")
    paths = parser.parse_args(argv).scenarios
    worlds: list[World] = []
    for path in paths:
        try:
            worlds.append(World(load_scenario(path), 7))
        except (ScenarioError, OSError, json.JSONDecodeError) as error:
            print(f"{path}: {error}")
            return 1
    collisions = _collisions(worlds)
    for line in collisions:
        print(line)
    if collisions:
        return 1
    print(f"ok: {len(worlds)} scenarios, disjoint")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
