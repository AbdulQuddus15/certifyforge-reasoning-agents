"""HTTP-boundary validation for structured orchestration requests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .agents.citations import sanitize_user_text

ALLOWED_CERTIFICATIONS = frozenset({"AZ-204", "AZ-400", "DP-203", "AZ-305", "SC-300", "DP-600"})
ALLOWED_ROLES = frozenset({
    "Cloud Engineer",
    "Cloud Developer",
    "DevOps Engineer",
    "Data Engineer",
    "Solutions Architect",
    "Security Engineer",
})
CHAT_MESSAGE_ROLES = frozenset({"user", "assistant", "system"})
MAX_ROLE_LEN = 80
MAX_CERT_LEN = 32
MAX_BODY_BYTES = 256 * 1024


@dataclass
class ValidationError(Exception):
    message: str
    code: str = "VALIDATION_ERROR"

    def __str__(self) -> str:
        return self.message


def parse_content_length(header_value: Optional[str]) -> int:
    """Parse Content-Length safely; negative or malformed values become 0."""
    try:
        length = int(header_value or "0")
        return max(0, length)
    except (TypeError, ValueError):
        return 0


def clamp_body_length(length: int, max_bytes: int = MAX_BODY_BYTES) -> int:
    """Return length capped to max_bytes (caller treats oversize as rejection)."""
    return max(0, min(length, max_bytes))


def is_oversize_body(length: int, max_bytes: int = MAX_BODY_BYTES) -> bool:
    return length > max_bytes


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        num = default
    return max(minimum, min(maximum, num))


def _normalize_cert(cert: str) -> str:
    cert = sanitize_user_text(cert, max_length=MAX_CERT_LEN).upper()
    aliases = {
        "AZ204": "AZ-204",
        "AZ400": "AZ-400",
        "DP203": "DP-203",
        "AZ305": "AZ-305",
        "SC300": "SC-300",
        "DP600": "DP-600",
    }
    return aliases.get(cert.replace("-", ""), cert) if cert else "AZ-204"


def is_structured_invoke_payload(data: Dict[str, Any]) -> bool:
    """True only for Call-tab / azd invoke payloads, not Chat single-message shapes."""
    if not isinstance(data, dict):
        return False
    if data.get("invoke") is True:
        return True

    role_raw = str(data.get("role", "")).strip()
    cert_raw = str(data.get("certification", "")).strip()
    has_content = bool(data.get("content") or data.get("message"))

    if role_raw.lower() in CHAT_MESSAGE_ROLES and has_content and role_raw not in ALLOWED_ROLES:
        return False

    role = sanitize_user_text(role_raw, max_length=MAX_ROLE_LEN) if role_raw else ""
    cert = _normalize_cert(cert_raw) if cert_raw else ""

    has_valid_role = role in ALLOWED_ROLES
    # Allow known certs or any plausible cert code (e.g. DP-600, PL-300, AZ-500, SC-400) so unknown certs don't force defaults
    has_valid_cert = cert in ALLOWED_CERTIFICATIONS or bool(re.match(r'^[A-Z]{2,3}-\d{3}$', cert))

    if data.get("messages") and not (has_valid_role and has_valid_cert):
        return False

    return has_valid_role and has_valid_cert


def validate_structured_request(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize structured invoke payloads before orchestration."""
    if not isinstance(data, dict):
        raise ValidationError("Request body must be a JSON object")

    role_raw = sanitize_user_text(str(data.get("role", "Cloud Engineer")), max_length=MAX_ROLE_LEN)
    cert_raw = _normalize_cert(str(data.get("certification", "AZ-204")))

    role = role_raw if role_raw in ALLOWED_ROLES else "Cloud Engineer"
    # Keep user-provided cert if it matches known or looks like a real cert code (supports unknown certs gracefully)
    if cert_raw in ALLOWED_CERTIFICATIONS or re.match(r'^[A-Z]{2,3}-\d{3}$', cert_raw):
        cert = cert_raw
    else:
        cert = "AZ-204"

    work_signals_in = dict(data.get("work_signals")) if isinstance(data.get("work_signals"), dict) else {}
    run_full = data.get("run_full") is True
    if not run_full and work_signals_in.pop("run_full", None) is True:
        run_full = True
    work_signals = {
        "meeting_hours_per_week": _coerce_int(
            work_signals_in.get("meeting_hours_per_week"), 22, 0, 50
        ),
        "focus_hours_per_week": _coerce_int(
            work_signals_in.get("focus_hours_per_week"), 10, 4, 40
        ),
        "preferred_learning_slot": sanitize_user_text(
            str(work_signals_in.get("preferred_learning_slot", "Morning")), max_length=32
        ) or "Morning",
    }
    if work_signals["preferred_learning_slot"] not in {"Morning", "Afternoon", "Evening"}:
        work_signals["preferred_learning_slot"] = "Morning"

    seed: Optional[int] = None
    if "seed" in data:
        try:
            seed = int(data.get("seed"))
        except (TypeError, ValueError):
            seed = 42

    sanitized: Dict[str, Any] = {
        "role": role,
        "certification": cert,
        "work_signals": work_signals,
    }
    if seed is not None:
        sanitized["seed"] = seed
    if run_full:
        sanitized["run_full"] = True
    if data.get("source"):
        sanitized["source"] = sanitize_user_text(str(data["source"]), max_length=32)
    if data.get("original_message"):
        sanitized["original_message"] = sanitize_user_text(str(data["original_message"]), max_length=500)
    return sanitized


def redact_for_log(text: str, max_len: int = 120) -> str:
    if not text:
        return "(empty)"
    redacted = text
    patterns = [
        (r"(?i)(key|token|password|secret|bearer|authorization)\s*[:=]\s*\S+", r"\1=***"),
        (r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "eyJ***JWT***"),
        (r"sk-[A-Za-z0-9]{20,}", "sk-***"),
        (r"ghp_[A-Za-z0-9]{20,}", "ghp_***"),
        (r"xox[baprs]-[A-Za-z0-9-]+", "xox***"),
        (r"(?i)DefaultEndpointsProtocol=\S+", "DefaultEndpointsProtocol=***"),
        (r"(?i)AccountKey=\S+", "AccountKey=***"),
        (r"(?i)SharedAccessSignature=\S+", "SharedAccessSignature=***"),
        (r"(?i)sig=[A-Za-z0-9%+/=]{8,}", "sig=***"),
        (r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |OPENSSH )?PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----***"),
    ]
    for pattern, repl in patterns:
        redacted = re.sub(pattern, repl, redacted)
    return redacted[:max_len]