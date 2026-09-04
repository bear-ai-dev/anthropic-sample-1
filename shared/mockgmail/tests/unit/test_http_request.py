import json

import pytest

from mockgmail.http_request import Request, Response, json_response
from mockgmail.tool_errors import InvalidArguments


def _request(body: bytes = b"", headers: dict[str, str] | None = None) -> Request:
    return Request(method="POST", path="/mcp/gmail", query={}, headers=headers or {}, body=body)


def test_an_empty_body_reads_as_an_empty_object() -> None:
    assert _request().json() == {}


def test_a_json_body_is_decoded() -> None:
    payload = {"method": "tools/call", "params": {"name": "read_email"}}
    assert _request(json.dumps(payload).encode()).json() == payload


def test_a_body_that_is_not_json_is_an_invalid_argument() -> None:
    with pytest.raises(InvalidArguments, match="body is not valid JSON"):
        _request(b"{not json").json()


def test_headers_match_case_insensitively_however_they_were_stored() -> None:
    request = _request(headers={"X-Mockgmail-Admin-Token": "secret"})
    assert request.header("x-mockgmail-admin-token") == "secret"
    assert request.header("X-MOCKGMAIL-ADMIN-TOKEN") == "secret"
    assert request.header("authorization") == ""
    assert request.header("authorization", "none") == "none"


def test_a_response_defaults_to_an_empty_two_hundred_with_its_own_headers() -> None:
    response = Response()
    assert response.status == 200
    assert response.body == b""
    assert response.headers == {}
    response.headers["Content-Type"] = "text/plain"
    assert Response().headers == {}


def test_a_json_response_is_compact_and_declares_its_media_type() -> None:
    response = json_response({"ok": True, "count": 2})
    assert response.body == b'{"ok":true,"count":2}'
    assert response.headers == {"Content-Type": "application/json"}
    assert response.status == 200
    assert json_response({"error": "forbidden"}, 403).status == 403
