import pytest

from certifyforge_agents.evaluation.simple_critic import SimpleCriticVerifier
from certifyforge_agents.data.models import StudyPlan, AssessmentResult


@pytest.mark.asyncio
async def test_verify_study_plan_rejects_high_gap_penalty():
    fabric = type("F", (), {
        "calculate_plan_feasibility": lambda self, plan, ctx, learner=None: {
            "is_feasible": True,
            "capacity_utilization": 0.7,
            "gap_penalty": 0.25,
        }
    })()
    critic = SimpleCriticVerifier(fabric_iq=fabric)
    plan = StudyPlan(learner_id="L-1", certification="AZ-204", milestones=[], total_hours=40, feasibility_score=0.7)
    result = await critic.verify_study_plan(plan, {"focus_hours_per_week": 10})
    assert result["accepted"] is False
    assert result["needs_replan"] is True


@pytest.mark.asyncio
async def test_verify_assessment_flags_threshold_mismatch():
    fabric = type("F", (), {
        "get_certification_requirements": lambda self, cert: type("R", (), {"pass_threshold": 0.75})(),
    })()
    critic = SimpleCriticVerifier(fabric_iq=fabric)
    assessment = AssessmentResult(
        learner_id="L-1",
        certification="AZ-204",
        questions=[{"citation": "AZ-204_Guide.md"}],
        readiness_score=0.6,
        passed=True,
        feedback="",
        grounded_in=["AZ-204_Guide.md"],
    )
    result = await critic.verify_assessment(assessment)
    assert result["is_valid"] is False


@pytest.mark.asyncio
async def test_should_retry_low_confidence():
    critic = SimpleCriticVerifier()
    assert await critic.should_retry({"confidence": 0.3, "issues": []}) is True