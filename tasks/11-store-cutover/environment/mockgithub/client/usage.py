from __future__ import annotations

from ..scenario import SERVICE

USAGE = f"""usage: {SERVICE} tools
       {SERVICE} <tool> [--name value ...] [--json '{{...}}'] [-- value-with-dashes]

Talks to the mock{SERVICE} daemon (MOCKGITHUB_URL, default http://127.0.0.1:4570).
Without arguments it speaks MCP over stdio for a client such as Claude Code.

  {SERVICE} tools                                  list the tools and their input schemas
  {SERVICE} get_me                                 run a tool without arguments
  {SERVICE} list_issues --owner o --repo r         run a tool with flag arguments
  {SERVICE} search_issues --json '{{"query": "x"}}'  run a tool with JSON arguments
  {SERVICE} search_issues --query -- -label:bug     pass a value that starts with a dash

Prints the text the tool returns; exits 1 when the tool reports an error, 2 on misuse.
"""
