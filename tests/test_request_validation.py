import pytest

from certifyforge_agents.request_validation import (
    ValidationError,
    clamp_body_length,
    is_oversize_body,
    parse_content_length,
    validate_structured_request,
)


def test_parse_content_length_malformed():
    assert parse_content_length("not-a-number") == 0
    assert parse_content_length("-5") == 0


def test_oversize_body_rejected():
    assert is_oversize_body(300_000) is True
    assert clamp_body_length(300_000) == 256 * 1024


def test_validate_structured_request_defaults():
    req = validate_structured_request({})
    assert req["role"] == "Cloud Engineer"
    assert req["certification"] == "AZ-204"
    assert 4 <= req["work_signals"]["focus_hours_per_week"] <= 40


def test_validate_structured_request_seed_and_sanitize():
    req = validate_structured_request({
        "role": "DevOps Engineer",
        "certification": "az400",
        "work_signals": {"focus_hours_per_week": 8, "preferred_learning_slot": "Evening"},
        "seed": 7,
    })
    assert req["certification"] == "AZ-400"
    assert req["seed"] == 7
    assert req["work_signals"]["preferred_learning_slot"] == "Evening"


def test_validate_rejects_non_dict():
    with pytest.raises(ValidationError):
        validate_structured_request([])  # type: ignore[arg-type]


def test_validate_coerces_unknown_role_and_cert():
    req = validate_structured_request({
        "role": "Hacker",
        "certification": "FAKE-999",
        "work_signals": {"preferred_learning_slot": "Midnight"},
    })
    assert req["role"] == "Cloud Engineer"
    assert req["certification"] == "AZ-204"
    assert req["work_signals"]["preferred_learning_slot"] == "Morning"


def test_validate_structured_request_hoists_run_full_from_work_signals():
    req = validate_structured_request({
        "role": "Cloud Engineer",
        "certification": "DP-203",
        "work_signals": {
            "focus_hours_per_week": 17,
            "run_full": True,
        },
    })
    assert req["run_full"] is True
    assert "run_full" not in req["work_signals"]
    assert req["work_signals"]["focus_hours_per_week"] == 17


def test_is_structured_invoke_payload_chat_role_user():
    from certifyforge_agents.request_validation import is_structured_invoke_payload
    assert is_structured_invoke_payload({"role": "user", "content": "hello"}) is False
    assert is_structured_invoke_payload({"role": "Cloud Engineer", "certification": "AZ-204"}) is True
    assert is_structured_invoke_payload({"work_signals": {}}) is False
    assert is_structured_invoke_payload({"invoke": True, "role": "Hacker"}) is True


def test_redact_for_log_extended_patterns():
    from certifyforge_agents.request_validation import redact_for_log
    text = "ghp_abcdefghijklmnopqrstuvwxyz123456 xoxb-1-abc DefaultEndpointsProtocol=https;AccountKey=secret"
    redacted = redact_for_log(text, 200)
    assert "ghp_***" in redacted or "ghp_" not in redacted
    assert "xox" in redacted
    assert "DefaultEndpointsProtocol=***" in redacted