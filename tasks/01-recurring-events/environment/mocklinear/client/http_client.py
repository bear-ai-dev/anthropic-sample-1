from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SERVICE = "linear"
DEFAULT_URL = "http://127.0.0.1:4570"
URL_ENV = "MOCKLINEAR_URL"
VIA_HEADER = "x-mocklinear-via"


class DaemonUnreachable(RuntimeError):
    pass


class ServiceUnavailable(RuntimeError):
    pass


def base_url() -> str:
    return (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/")


def post_message(message: dict[str, Any], via: str, timeout: float = 30.0) -> Any:
    url = f"{base_url()}/mcp/{SERVICE}"
    request = Request(
        url,
        data=json.dumps(message).encode(),
        headers={"Content-Type": "application/json", VIA_HEADER: via},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as error:
        detail = json.loads(error.read() or b"{}").get("error", "")
        if error.code == 404:
            raise ServiceUnavailable(detail) from error
        raise DaemonUnreachable(f"{url} answered {error.code}: {detail}") from error
    except URLError as error:
        raise DaemonUnreachable(f"mocklinear daemon not reachable at {base_url()}") from error
    return json.loads(raw) if raw else None
