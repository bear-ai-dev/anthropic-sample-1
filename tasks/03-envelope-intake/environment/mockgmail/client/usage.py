from __future__ import annotations

USAGE = """mockgmail - a fake Gmail mailbox behind the Gmail MCP tool surface

  gmail                       speak MCP over stdio (this is how an MCP client runs it)
  gmail tools                 list the tools this mailbox answers, with their schemas
  gmail <tool> [--name value ...] [--json '{...}']
                              call one tool and print what it answers

Examples

  gmail search_emails --query "from:pat.ryan is:unread" --maxResults 20
  gmail read_email --messageId 3f9c1a2b7d4e5f60
  gmail list_email_labels
  gmail download_attachment --json '{"messageId": "...", "attachmentId": "...", "savePath": "."}'
  gmail search_emails --query -- "-in:sent newer_than:7d"

A value that begins with a dash has to come after --, so that it is never read
as another flag. The daemon answers on $MOCKGMAIL_URL (default
http://127.0.0.1:4570) and needs no credential.
"""
