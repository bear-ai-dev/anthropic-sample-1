from __future__ import annotations

SUMMARY = "a fake Linear workspace behind the Linear MCP tool surface"
EXAMPLES = """  linear list_issues --assignee me --limit 20
  linear get_issue --id WEB-611
  linear list_issues --json '{"team": "WEB", "state": "started"}'
  linear list_issues --updatedAt -- -P1W
"""
