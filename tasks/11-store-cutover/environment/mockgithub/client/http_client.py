from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..scenario import SERVICE

DEFAULT_URL = "http://127.0.0.1:4570"
URL_ENV = "MOCKGITHUB_URL"
VIA_HEADER = "x-mockgithub-via"
ACCEPTED = 202


class DaemonUnreachable(RuntimeError):
    pass


class ServiceUnavailable(RuntimeError):
    pass


def base_url() -> str:
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


def post_message(message: dict[str, Any], via: str, timeout: float = 30.0) -> dict[str, Any] | None:
    url = base_url()
    request = Request(
        f"{url}/mcp/{SERVICE}",
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json", VIA_HEADER: via},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status == ACCEPTED:
                return None
            answer: dict[str, Any] = json.loads(response.read())
            return answer
    except HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        if error.code == 404 and f"unknown service: {SERVICE}" in body:
            raise ServiceUnavailable(f"unknown service: {SERVICE}") from error
        raise DaemonUnreachable(f"{SERVICE} daemon answered {error.code}: {body}") from error
    except URLError as error:
        raise DaemonUnreachable(f"mock{SERVICE} daemon not reachable at {url}") from error
