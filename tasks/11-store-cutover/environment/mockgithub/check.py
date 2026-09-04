from __future__ import annotations

import argparse
import json

from .github.state import GithubState
from .scenario import ScenarioError, load_scenario
from .world import World


def _keys(state: GithubState) -> dict[str, set[str]]:
    repos = state.repos
    return {
        "repository": {repo.full_name for repo in repos},
        "login": {user.login for user in state.users},
        "user email": {user.email for user in state.users if user.email},
        "issue number": {
            f"{repo.full_name}#{issue.number}" for repo in repos for issue in repo.issues
        },
        "pull number": {f"{repo.full_name}#{pull.number}" for repo in repos for pull in repo.pulls},
        "branch name": {
            f"{repo.full_name}:{branch.name}" for repo in repos for branch in repo.branches
        },
        "commit key": {
            f"{repo.full_name}:{commit.key}" for repo in repos for commit in repo.commits
        },
        "tag name": {f"{repo.full_name}:{tag.name}" for repo in repos for tag in repo.tags},
    }


def _collisions(worlds: list[World]) -> list[str]:
    maps = [_keys(world.github) for world in worlds]
    lines: list[str] = []
    for index, first in enumerate(maps):
        for second in maps[index + 1 :]:
            for kind, values in first.items():
                lines.extend(f"shared {kind}: {value}" for value in sorted(values & second[kind]))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mockgithub.check")
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
