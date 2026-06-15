"""Client-safe error mapping for hosted HTTP responses."""

from __future__ import annotations

from typing import Any, Dict


GENERIC_ORCHESTRATION_MESSAGE = (
    "An internal error occurred while processing your request. "
    "See container logs for details."
)
GENERIC_CHAT_MESSAGE = (
    "Thanks for your message! I ran into an issue while building your response. "
    "Please try the Call agent tab with structured JSON, or use `azd ai agent invoke`."
)


def client_error_code(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "auth" in name or "credential" in name:
        return "AUTH_ERROR"
    if "validation" in name:
        return "VALIDATION_ERROR"
    if "timeout" in name:
        return "TIMEOUT_ERROR"
    return "ORCHESTRATION_ERROR"


def client_safe_message(exc: Exception, *, context: str = "orchestration") -> str:
    """Never forward raw SDK/exception strings to HTTP clients."""
    if context == "chat":
        return GENERIC_CHAT_MESSAGE
    return GENERIC_ORCHESTRATION_MESSAGE


def error_envelope(
    message: str,
    *,
    error_code: str = "REQUEST_ERROR",
    include_result: bool = False,
    result: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Always-200 compatible envelope with choices + output."""
    payload: Dict[str, Any] = {
        "status": "error",
        "error_code": error_code,
        "summary": message,
        "choices": [{"message": {"role": "assistant", "content": message}}],
        "output": message,
    }
    if include_result:
        payload["result"] = result or {"status": "error"}
    return payload