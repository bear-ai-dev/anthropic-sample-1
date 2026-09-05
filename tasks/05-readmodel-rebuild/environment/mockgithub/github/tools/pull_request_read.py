from __future__ import annotations

from typing import Any

from ...tool_result import ToolResult, text_result
from ...tool_spec import ToolSpec
from ...world import World
from ..diff import changed_files, commit_diff
from ..envelope import compact, graphql_list, rest_list
from ..history import ancestry, resolve_ref
from ..lookup import PAGE_SCHEMA, REPO_SCHEMA, pull_of, repo_of
from ..models_pulls import Pull
from ..models_repo import Commit, Repo
from ..render_issues import comment
from ..render_pulls import check_run, combined_status, rest_pull, review, review_thread
from ..render_repo import commit as render_commit
from ..render_repo import file_entry

METHODS = [
    "get",
    "get_diff",
    "get_status",
    "get_files",
    "get_commits",
    "get_review_comments",
    "get_reviews",
    "get_comments",
    "get_check_runs",
]
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "enum": METHODS, "description": "The read operation"},
        **REPO_SCHEMA,
        "pullNumber": {"type": "integer", "description": "Pull request number"},
        **PAGE_SCHEMA,
        "after": {"type": "string", "description": "Cursor for pagination"},
    },
    "required": ["method", "owner", "repo", "pullNumber"],
}


def _head(repo: Repo, pull: Pull) -> Commit | None:
    return repo.commit_by_key(pull.head_key)


def _pull_commits(repo: Repo, pull: Pull, head: Commit) -> list[Commit]:
    base = resolve_ref(repo, pull.base_ref)
    on_base = set() if base is None else {commit.key for commit in ancestry(repo, base)}
    own = [commit for commit in ancestry(repo, head) if commit.key not in on_base]
    return own or [head]


def _paged(world: World, repo: Repo, pull: Pull, arguments: dict[str, Any]) -> ToolResult:
    state = world.github
    method = arguments["method"]
    head = _head(repo, pull)
    if method == "get_files":
        changes = [] if head is None else changed_files(repo, head)
        rendered, page = rest_list(changes, arguments, lambda pair: file_entry(*pair))
    elif method == "get_commits":
        commits = [] if head is None else _pull_commits(repo, pull, head)
        rendered, page = rest_list(commits, arguments, lambda c: render_commit(repo, c, state))
    else:
        rendered, page = rest_list(
            list(pull.comments),
            arguments,
            lambda item: comment(repo, "pull", pull.number, item, state),
        )
    return compact(rendered, page=page)


def handle(world: World, arguments: dict[str, Any]) -> ToolResult:
    repo = repo_of(world, arguments)
    pull = pull_of(repo, int(arguments["pullNumber"]))
    method = arguments["method"]
    head = _head(repo, pull)
    if method == "get":
        return compact(rest_pull(repo, pull, world.github))
    if method == "get_diff":
        return text_result("" if head is None else commit_diff(repo, head))
    if method == "get_status":
        return compact(combined_status(repo, pull))
    if method == "get_reviews":
        return compact([review(item) for item in pull.reviews])
    if method == "get_check_runs":
        sha = "" if head is None else head.sha
        runs = [check_run(item, sha) for item in pull.check_runs]
        return compact({"total_count": len(runs), "check_runs": runs})
    if method == "get_review_comments":
        threads, info, page = graphql_list(list(pull.review_comments), arguments, review_thread)
        payload = {
            "reviewThreads": threads,
            "pageInfo": info,
            "totalCount": len(pull.review_comments),
        }
        return compact(payload, page=page)
    return _paged(world, repo, pull, arguments)


SPEC = ToolSpec(
    "pull_request_read",
    "Get information about a specific pull request: details, diff, status, files, commits, "
    "review comments, reviews, comments or check runs.",
    SCHEMA,
    handle,
)
