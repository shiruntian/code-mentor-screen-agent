"""统一的业务异常：所有可预期错误都转成结构化响应，绝不抛裸 500。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "app_error"
    http_status = 400

    def __init__(self, message: str, *, hint: str | None = None, detail: Any = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        # 所有响应都带 ok：前端与冒烟测试只看这一个字段就知道成没成
        payload: dict[str, Any] = {"ok": False, "code": self.code, "message": self.message}
        if self.hint:
            payload["hint"] = self.hint
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


class NotFoundError(AppError):
    code = "not_found"
    http_status = 404


class ValidationError(AppError):
    code = "validation_error"
    http_status = 422


class LLMNotConfiguredError(AppError):
    code = "llm_not_configured"
    http_status = 400


class LLMCallError(AppError):
    code = "llm_call_failed"
    http_status = 502


class ToolExecutionError(AppError):
    code = "tool_failed"
    http_status = 500


class ScreenControlError(AppError):
    code = "screen_control_error"
    http_status = 500