from __future__ import annotations

from .examples import EXAMPLES, SUMMARY
from .http_client import DEFAULT_URL, SERVICE, URL_ENV

USAGE = f"""mock{SERVICE} - {SUMMARY}

  {SERVICE}
      speak MCP over stdio (this is how an MCP client runs it)
  {SERVICE} tools
      list the tools it answers, with their schemas
  {SERVICE} <tool> [--name value ...] [--json '{{...}}']
      call one tool and print what it answers

Examples

{EXAMPLES}
A value that begins with a dash has to come after --, so that it is never read
as another flag. The daemon answers on ${URL_ENV} (default {DEFAULT_URL}) and
needs no credential. A tool that reports an error exits 1; misuse exits 2.
"""
