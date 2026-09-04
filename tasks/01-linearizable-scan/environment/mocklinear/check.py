from __future__ import annotations

import argparse
import json

from .linear.state import LinearState
from .scenario import ScenarioError, load_scenario
from .world import World


def _keys(state: LinearState) -> dict[str, set[str]]:
    return {
        "issue identifier": {issue.identifier for issue in state.issues},
        "user key": {user.key for user in state.users},
        "user email": {user.email for user in state.users if user.email},
        "user name": {user.name for user in state.users if user.name},
        "team key": {team.key for team in state.teams},
        "project key": {project.key for project in state.projects},
        "document key": {document.key for document in state.documents},
        "issue branch name": {issue.branch_name for issue in state.issues},
        "attachment key": {
            attachment.key for issue in state.issues for attachment in issue.attachments
        },
    }


def _collisions(worlds: list[World]) -> list[str]:
    maps = [_keys(world.linear) for world in worlds]
    lines: list[str] = []
    for index, first in enumerate(maps):
        for second in maps[index + 1 :]:
            for kind, values in first.items():
                lines.extend(f"shared {kind}: {value}" for value in sorted(values & second[kind]))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mocklinear.check")
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
