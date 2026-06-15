import pytest

from certifyforge_agents.readiness_server import parse_user_intent


@pytest.mark.parametrize("message,cert", [
    ("targeting az204", "AZ-204"),
    ("going for dp-203", "DP-203"),
    ("architect path az305", "AZ-305"),
])
def test_parse_cert_aliases(message, cert):
    _, parsed_cert, _ = parse_user_intent(message)
    assert parsed_cert == cert


def test_parse_devops_az400_evening():
    role, cert, signals = parse_user_intent(
        "I'm a DevOps engineer targeting AZ-400 with 8 focus hours per week evening"
    )
    assert role == "DevOps Engineer"
    assert cert == "AZ-400"
    assert signals["focus_hours_per_week"] == 8
    assert signals["preferred_learning_slot"] == "Evening"


@pytest.mark.parametrize("message,role", [
    ("data engineer path az-204", "Data Engineer"),
    ("data platform certification dp-203", "Data Engineer"),
    ("solutions architect az305", "Solutions Architect"),
])
def test_parse_role_detection(message, role):
    parsed_role, _, _ = parse_user_intent(message)
    assert parsed_role == role


def test_parse_meeting_hours_and_night_slot():
    _, _, signals = parse_user_intent("cloud engineer az-204 with 30 meeting hours per week night")
    assert signals["meeting_hours_per_week"] == 30
    assert signals["preferred_learning_slot"] == "Evening"


def test_parse_defaults_for_empty():
    role, cert, signals = parse_user_intent("")
    assert role == "Cloud Engineer"
    assert cert == "AZ-204"
    assert signals["focus_hours_per_week"] == 10