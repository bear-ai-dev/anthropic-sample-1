from __future__ import annotations

import argparse
import json

from .linear.keys import human_keys
from .scenario import ScenarioError, load_scenario
from .world import World


def _collisions(worlds: list[World]) -> list[str]:
    maps = [human_keys(world.linear) for world in worlds]
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
