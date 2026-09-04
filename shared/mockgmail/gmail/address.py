from __future__ import annotations

from email.utils import parseaddr


def address_of(header: str) -> str:
    return parseaddr(header)[1].casefold()
