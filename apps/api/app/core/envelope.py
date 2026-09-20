"""统一响应 Envelope — 契约固定，禁止改字段名
{"ok": bool, "data": {}, "error": null|{code,message}, "request_id": "...", "trace": {"stage": "..."}}
"""
import uuid
from typing import Any

_STAGE = "p0"


def ok(data: Any = None, stage: str = _STAGE) -> dict:
    return {
        "ok": True,
        "data": data if data is not None else {},
        "error": None,
        "request_id": str(uuid.uuid4()),
        "trace": {"stage": stage},
    }


def err(code: str, message: str, stage: str = _STAGE) -> dict:
    return {
        "ok": False,
        "data": {},
        "error": {"code": code, "message": message},
        "request_id": str(uuid.uuid4()),
        "trace": {"stage": stage},
    }
