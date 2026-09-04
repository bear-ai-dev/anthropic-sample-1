from __future__ import annotations

import base64
import hashlib

from .models import Attachment


def attachment_bytes(attachment: Attachment) -> bytes:
    if attachment.data_b64 is not None:
        return base64.b64decode(attachment.data_b64)
    block = hashlib.sha256(attachment.key.encode()).digest()
    return (block * (attachment.size // len(block) + 1))[: attachment.size]
