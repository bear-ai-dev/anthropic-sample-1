from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from ..gmail.format import confirmation
from ..payload import ATTACHMENT_KEY
from ..tool_errors import InvalidArguments


def write_attachment(payload: dict[str, Any], cwd: Path) -> tuple[Path, int]:
    directory = Path(str(payload.get("savePath") or cwd))
    root = (directory if directory.is_absolute() else cwd / directory).resolve()
    name = str(payload.get("filename") or "")
    target = (root / name).resolve()
    if not name or target == root or not target.is_relative_to(root):
        raise InvalidArguments("filename escapes savePath")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(str(payload.get("data_b64", "")))
    target.write_bytes(data)
    return target, len(data)


def _payload(block: dict[str, Any]) -> dict[str, Any] | None:
    if block.get("type") != "text":
        return None
    try:
        parsed = json.loads(str(block.get("text", "")))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not isinstance(parsed.get(ATTACHMENT_KEY), dict):
        return None
    payload: dict[str, Any] = parsed[ATTACHMENT_KEY]
    return payload


def _materialise(block: dict[str, Any], cwd: Path) -> dict[str, Any]:
    payload = _payload(block)
    if payload is None:
        return block
    try:
        target, size = write_attachment(payload, cwd)
    except InvalidArguments as refused:
        return {"type": "text", "text": f"Error: {refused.message}"}
    except OSError as failure:
        return {"type": "text", "text": f"Error: {failure}"}
    return {"type": "text", "text": confirmation(str(payload["filename"]), size, str(target))}


def rewrite(answer: Any, cwd: Path) -> Any:
    if not isinstance(answer, dict) or not isinstance(answer.get("result"), dict):
        return answer
    content = answer["result"].get("content")
    if not isinstance(content, list):
        return answer
    result = dict(answer["result"], content=[_materialise(block, cwd) for block in content])
    return dict(answer, result=result)
