from __future__ import annotations

USAGE = """mocklinear - a fake Linear workspace behind the Linear MCP tool surface

  linear                      speak MCP over stdio (this is how an MCP client runs it)
  linear tools                list the tools this workspace answers, with their schemas
  linear <tool> [--name value ...] [--json '{...}']
                              call one tool and print what it answers

Examples

  linear list_issues --assignee me --limit 20
  linear get_issue --id WEB-611
  linear list_issues --json '{"team": "WEB", "state": "started"}'
  linear list_issues --updatedAt -- -P1W

A value that begins with a dash has to come after --, so that it is never read
as another flag. The daemon answers on $MOCKLINEAR_URL (default
http://127.0.0.1:4570) and needs no credential.
"""
