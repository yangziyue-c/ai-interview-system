"""统一响应格式

所有接口返回：
    {"code": 0, "message": "ok", "data": ...}
"""
from typing import Any


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
