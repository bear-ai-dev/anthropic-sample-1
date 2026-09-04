from __future__ import annotations

SUMMARY = "a fake GitHub account behind the GitHub MCP tool surface"
EXAMPLES = """  github get_me
  github list_issues --owner ExampleCo --repo membership-ledger --state OPEN
  github get_file_contents --json '{"owner": "ExampleCo", "repo": "membership-ledger", "path": "/"}'
  github search_issues --query -- -label:docs is:open
"""
