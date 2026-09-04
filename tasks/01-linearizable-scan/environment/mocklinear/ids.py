from __future__ import annotations

import hashlib


def stable_digest(seed: int, service: str, kind: str, key: str) -> str:
    return hashlib.sha1(f"{seed}:{service}:{kind}:{key}".encode()).hexdigest()


def uuid_for(seed: int, service: str, kind: str, key: str) -> str:
    digest = stable_digest(seed, service, kind, key)
    variant = "89ab"[int(digest[16], 16) % 4]
    parts = (
        digest[0:8],
        digest[8:12],
        f"4{digest[13:16]}",
        f"{variant}{digest[17:20]}",
        digest[20:32],
    )
    return "-".join(parts)
