from __future__ import annotations

from .state import GithubState


def human_keys(state: GithubState) -> dict[str, set[str]]:
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
