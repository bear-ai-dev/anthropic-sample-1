from __future__ import annotations

SUMMARY = "a fake Gmail mailbox behind the Gmail MCP tool surface"
EXAMPLES = """  gmail search_emails --query "from:pat.ryan is:unread" --maxResults 20
  gmail read_email --messageId 3f9c1a2b7d4e5f60
  gmail list_email_labels
  gmail download_attachment --json '{"messageId": "...", "attachmentId": "...", "savePath": "."}'
  gmail search_emails --query -- "-in:sent newer_than:7d"
"""
