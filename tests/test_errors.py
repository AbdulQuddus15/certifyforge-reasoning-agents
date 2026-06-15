from certifyforge_agents.errors import (
    GENERIC_CHAT_MESSAGE,
    client_error_code,
    client_safe_message,
    error_envelope,
)
from certifyforge_agents.request_validation import redact_for_log


class AuthException(Exception):
    pass


def test_client_error_code_auth():
    assert client_error_code(AuthException("fail")) == "AUTH_ERROR"


def test_client_safe_message_chat_context():
    assert client_safe_message(RuntimeError("secret sdk"), context="chat") == GENERIC_CHAT_MESSAGE


def test_redact_for_log_masks_common_secrets():
    text = "api_key=supersecret sk-abcdefghijklmnopqrstuvwxyz123456"
    redacted = redact_for_log(text)
    assert "supersecret" not in redacted
    assert "sk-***" in redacted


def test_error_envelope_has_choices():
    env = error_envelope("msg", error_code="X")
    assert env["choices"][0]["message"]["content"] == "msg"