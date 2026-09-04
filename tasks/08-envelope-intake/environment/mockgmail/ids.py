from __future__ import annotations

import hashlib


def stable_digest(seed: int, service: str, kind: str, key: str) -> str:
    return hashlib.sha1(f"{seed}:{service}:{kind}:{key}".encode()).hexdigest()


def uuid_for(seed: int, service: str, kind: str, key: str) -> str:
    digest = stable_digest(seed, service, kind, key)
    parts = (digest[0:8], digest[8:12], digest[12:16], digest[16:20], digest[20:32])
    return "-".join(parts)


def hex_for(seed: int, service: str, kind: str, key: str, length: int) -> str:
    digest = stable_digest(seed, service, kind, key)
    return (digest * (length // len(digest) + 1))[:length]
