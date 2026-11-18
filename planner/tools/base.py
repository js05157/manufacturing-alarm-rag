"""Stable Tool contract shared by external and local server tools."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    category: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    @classmethod
    def success(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, code: str, message: str, *, retryable: bool = False) -> "ToolResult":
        return cls(ok=False, error=ToolError(code, message, retryable))

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": self.ok}
        if self.ok:
            payload["data"] = self.data or {}
        else:
            payload["error"] = (self.error or ToolError("UNKNOWN", "알 수 없는 오류입니다.")).as_dict()
        return payload


class Tool(Protocol):
    spec: ToolSpec

    def invoke(self, **kwargs: Any) -> ToolResult:
        ...


COMMON_OUTPUT_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "required": ["ok", "data"],
            "properties": {"ok": {"const": True}, "data": {"type": "object"}},
        },
        {
            "type": "object",
            "required": ["ok", "error"],
            "properties": {
                "ok": {"const": False},
                "error": {
                    "type": "object",
                    "required": ["code", "message", "retryable"],
                    "properties": {
                        "code": {"type": "string"},
                        "message": {"type": "string"},
                        "retryable": {"type": "boolean"},
                    },
                },
            },
        },
    ]
}
