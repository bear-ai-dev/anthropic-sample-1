from typing import Any

from mockgithub.github.search_query import matches, parse

ISSUE: dict[str, Any] = {
    "type": "issue",
    "state": "closed",
    "merged": False,
    "draft": False,
    "labels": ["ci", "flaky"],
    "author": "rhea-menon",
    "assignees": ["mbeaulieu"],
    "repo": "ExampleCo/membership-ledger",
    "title": "ci: the build job times out",
    "body": "modernc.org/sqlite is nearly all of it. Warm module cache: 90 seconds.",
}
PULL: dict[str, Any] = dict(
    ISSUE, type="pr", merged=True, labels=["area/api"], author="jiwon-park", title="ledger view"
)
CODE: dict[str, Any] = {
    "repo": "ExampleCo/membership-ledger",
    "path": "internal/ledger/view.go",
    "filename": "view.go",
    "content": "package ledger\n\ntype View interface {}\n",
}


def _hit(query: str, doc: dict[str, Any]) -> bool:
    return matches(parse(query), doc)


def test_bare_words_match_title_and_body_case_insensitively_and_all_must_match() -> None:
    assert _hit("BUILD sqlite", ISSUE)
    assert not _hit("build postgres", ISSUE)
    assert _hit("", ISSUE)


def test_a_quoted_phrase_must_appear_contiguously() -> None:
    assert _hit('"module cache"', ISSUE)
    assert not _hit('"cache module"', ISSUE)
    assert _hit('"times out" -"never fails"', ISSUE)


def test_in_restricts_where_bare_words_are_looked_for() -> None:
    assert _hit("sqlite in:body", ISSUE)
    assert not _hit("sqlite in:title", ISSUE)
    assert _hit("build in:title", ISSUE)
    assert _hit("build in:title,body", ISSUE)


def test_type_state_and_merge_qualifiers() -> None:
    assert _hit("is:issue", ISSUE) and not _hit("is:pr", ISSUE)
    assert _hit("type:pr", PULL) and not _hit("type:issue", PULL)
    assert _hit("is:closed state:closed", ISSUE) and not _hit("is:open", ISSUE)
    assert _hit("is:merged", PULL) and not _hit("is:merged", ISSUE)
    assert _hit("is:unmerged", ISSUE) and not _hit("is:unmerged", PULL)
    assert not _hit("is:draft", PULL)
    assert _hit("-is:draft", PULL)


def test_label_author_assignee_and_repo_qualifiers() -> None:
    assert _hit("label:ci label:flaky", ISSUE)
    assert not _hit("label:bug", ISSUE)
    assert _hit('label:"area/api"', PULL)
    assert _hit("author:rhea-menon", ISSUE) and not _hit("author:nobody", ISSUE)
    assert _hit("assignee:mbeaulieu", ISSUE) and not _hit("assignee:rhea-menon", ISSUE)
    assert _hit("repo:ExampleCo/membership-ledger", ISSUE)
    assert not _hit("repo:ExampleCo/other", ISSUE)
    assert _hit("org:ExampleCo user:ExampleCo", ISSUE) and not _hit("org:acme", ISSUE)


def test_negation_flips_words_and_qualifiers() -> None:
    assert _hit("-label:bug", ISSUE) and not _hit("-label:ci", ISSUE)
    assert _hit("-postgres", ISSUE) and not _hit("-sqlite", ISSUE)
    assert _hit("-author:nobody", ISSUE)


def test_an_unknown_qualifier_is_ignored() -> None:
    assert _hit("milestone:3 sqlite", ISSUE)
    assert _hit("sort:updated-desc", ISSUE)


def test_code_search_looks_at_content_path_and_filename() -> None:
    assert _hit("View interface", CODE)
    assert not _hit("package main", CODE)
    assert _hit("path:internal/ledger", CODE) and not _hit("path:docs", CODE)
    assert _hit("filename:view.go", CODE) and not _hit("filename:other.go", CODE)
    assert _hit("repo:ExampleCo/membership-ledger View", CODE)
    assert _hit("extension:go", CODE) and not _hit("extension:md", CODE)
    assert _hit("in:path ledger", CODE) and not _hit("in:path interface", CODE)


def test_the_parsed_query_records_what_was_asked() -> None:
    query = parse('is:pr -label:bug "exact phrase" word in:title')
    assert query.terms == (("exact phrase", False), ("word", False))
    assert query.qualifiers == (("is", "pr", False), ("label", "bug", True))
    assert query.fields == ("title",)
    assert parse("").fields == ()


def test_an_unknown_is_flag_matches_everything() -> None:
    assert _hit("is:public", ISSUE)
    assert not _hit("-is:public", ISSUE)
