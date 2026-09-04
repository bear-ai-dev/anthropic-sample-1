from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models_issues import Issue, Label, Milestone
from .models_pulls import Pull

SHA_PREFIX_MIN = 4


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str
    content: str | None
    sha: str


@dataclass(frozen=True)
class Commit:
    key: str
    sha: str
    message: str
    author_login: str
    date: datetime
    parent_keys: tuple[str, ...]
    files: tuple[FileChange, ...]


@dataclass(frozen=True)
class Branch:
    name: str
    head_key: str


@dataclass(frozen=True)
class Tag:
    name: str
    commit_key: str


@dataclass(frozen=True)
class Release:
    id: int
    tag: str
    name: str
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Repo:
    id: int
    owner: str
    name: str
    default_branch: str
    description: str
    labels: tuple[Label, ...]
    milestones: tuple[Milestone, ...]
    commits: tuple[Commit, ...]
    branches: tuple[Branch, ...]
    tags: tuple[Tag, ...]
    releases: tuple[Release, ...]
    issues: tuple[Issue, ...]
    pulls: tuple[Pull, ...]

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.name}"

    def label(self, name: str) -> Label | None:
        return next((item for item in self.labels if item.name == name), None)

    def milestone(self, number: int) -> Milestone | None:
        return next((item for item in self.milestones if item.number == number), None)

    def issue(self, number: int) -> Issue | None:
        return next((item for item in self.issues if item.number == number), None)

    def pull(self, number: int) -> Pull | None:
        return next((item for item in self.pulls if item.number == number), None)

    def branch(self, name: str) -> Branch | None:
        return next((item for item in self.branches if item.name == name), None)

    def tag(self, name: str) -> Tag | None:
        return next((item for item in self.tags if item.name == name), None)

    def commit_by_key(self, key: str) -> Commit | None:
        return next((item for item in self.commits if item.key == key), None)

    def commit(self, sha: str) -> Commit | None:
        wanted = sha.strip().lower()
        if len(wanted) < SHA_PREFIX_MIN:
            return None
        return next((item for item in self.commits if item.sha.startswith(wanted)), None)
