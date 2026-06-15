import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from certifyforge_agents.orchestrator.simple_orchestrator import SimpleOrchestrator
from certifyforge_agents.data.models import StudyPlan, AssessmentResult
from certifyforge_agents.evaluation.simple_critic import SimpleCriticVerifier


@pytest.mark.asyncio
async def test_create_plan_inserts_role_alignment_for_low_alignment():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.3}
    fabric.get_certification_requirements.return_value = None
    orch = SimpleOrchestrator(fabric_iq=fabric, seed=42)
    plan = await orch.create_plan({"role": "Data Engineer", "certification": "AZ-204"})
    steps = [p["step"] for p in plan]
    assert "role_alignment_check" in steps


@pytest.mark.asyncio
async def test_study_plan_receives_learning_path_from_curator():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    fabric.get_certification_requirements.return_value = None
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.8,
        "gap_penalty": 0.0,
    }

    captured = {}

    async def fake_execute(input_data):
        captured["learning_path"] = input_data.get("learning_path")
        return {"study_plan": {"learner_id": "L-1", "certification": "AZ-204", "milestones": [], "total_hours": 40, "feasibility_score": 0.7}}

    with patch("certifyforge_agents.orchestrator.simple_orchestrator.LearningPathCurator") as lp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.StudyPlanGenerator") as sp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.AssessmentAgent") as ass_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.EngagementAgent") as eng_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.ManagerInsightsAgent") as mgr_cls:

        lp_inst = lp_cls.return_value
        lp_inst.execute = AsyncMock(return_value={
            "learning_path": {
                "core_skills": ["Functions", "Storage"],
                "modules": [{"title": "Mod1"}],
                "grounded_in": ["AZ-204_Guide.md"],
            }
        })
        sp_inst = sp_cls.return_value
        sp_inst.execute = fake_execute
        ass_cls.return_value.execute = AsyncMock(return_value={
            "assessment": {
                "readiness_score": 0.8,
                "passed": True,
                "questions": [{"citation": "AZ-204_Guide.md"}],
            }
        })
        eng_cls.return_value.execute = AsyncMock(return_value={})
        mgr_cls.return_value.execute = AsyncMock(return_value={})

        orch = SimpleOrchestrator(fabric_iq=fabric, seed=42)
        orch.critic = SimpleCriticVerifier(fabric_iq=fabric)
        await orch.handle_request({"role": "Cloud Engineer", "certification": "AZ-204", "work_signals": {"focus_hours_per_week": 10}})

    assert captured["learning_path"]["core_skills"] == ["Functions", "Storage"]


@pytest.mark.asyncio
async def test_llm_adjustment_mutates_milestones():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    fabric.get_certification_requirements.return_value = None
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.8,
        "gap_penalty": 0.0,
    }

    llm = MagicMock()
    llm.generate.return_value = "Focus on hands-on labs for Functions."

    with patch("certifyforge_agents.orchestrator.simple_orchestrator.LearningPathCurator") as lp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.StudyPlanGenerator") as sp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.AssessmentAgent") as ass_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.EngagementAgent") as eng_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.ManagerInsightsAgent") as mgr_cls:

        lp_cls.return_value.execute = AsyncMock(return_value={"learning_path": {"core_skills": []}})
        sp_cls.return_value.execute = AsyncMock(return_value={
            "study_plan": {
                "learner_id": "L-1",
                "certification": "AZ-204",
                "milestones": [{"week": 1, "topic": "Intro", "hours": 5}],
                "total_hours": 40,
                "feasibility_score": 0.7,
            },
            "milestones": [{"week": 1, "topic": "Intro", "hours": 5}],
        })
        ass_cls.return_value.execute = AsyncMock(return_value={
            "assessment": {"readiness_score": 0.8, "passed": True, "questions": [{"citation": "AZ-204_Guide.md"}]}
        })
        eng_cls.return_value.execute = AsyncMock(return_value={})
        mgr_cls.return_value.execute = AsyncMock(return_value={})

        orch = SimpleOrchestrator(fabric_iq=fabric, llm_client=llm, seed=42)
        result = await orch.handle_request({"role": "Cloud Engineer", "certification": "AZ-204", "work_signals": {"focus_hours_per_week": 10}})

    sp_out = result["results"]["study_plan"]["output"]
    milestones = sp_out.get("milestones") or sp_out.get("study_plan", {}).get("milestones", [])
    assert len(milestones) >= 2
    total_hours = sp_out.get("study_plan", {}).get("total_hours", sp_out.get("total_hours", 0))
    assert total_hours >= 43
    assert result["status"] in ("completed_with_verification", "partial")
    assert result["iterations"] <= 2


@pytest.mark.asyncio
async def test_create_plan_inserts_prerequisite_check():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    prereq = MagicMock()
    prereq.prerequisites = ["AZ-900"]
    fabric.get_certification_requirements.return_value = prereq
    orch = SimpleOrchestrator(fabric_iq=fabric, seed=42)
    plan = await orch.create_plan({"role": "DevOps Engineer", "certification": "AZ-400"})
    assert plan[0]["step"] == "prerequisite_check"


@pytest.mark.asyncio
async def test_llm_duplicate_milestone_guard():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    fabric.get_certification_requirements.return_value = None
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.8,
        "gap_penalty": 0.0,
    }
    llm = MagicMock()
    llm.generate.return_value = "Focus on hands-on labs for Functions."
    existing_reinforcement = {
        "week": 2,
        "topic": "Hands-on reinforcement: Focus on hands-on labs for Functions.",
        "hours": 3,
    }

    with patch("certifyforge_agents.orchestrator.simple_orchestrator.LearningPathCurator") as lp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.StudyPlanGenerator") as sp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.AssessmentAgent") as ass_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.EngagementAgent") as eng_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.ManagerInsightsAgent") as mgr_cls:
        lp_cls.return_value.execute = AsyncMock(return_value={"learning_path": {"core_skills": []}})
        sp_cls.return_value.execute = AsyncMock(return_value={
            "study_plan": {
                "learner_id": "L-1",
                "certification": "AZ-204",
                "milestones": [{"week": 1, "topic": "Intro", "hours": 5}, existing_reinforcement],
                "total_hours": 43,
                "feasibility_score": 0.7,
            },
            "milestones": [{"week": 1, "topic": "Intro", "hours": 5}, existing_reinforcement],
        })
        ass_cls.return_value.execute = AsyncMock(return_value={"assessment": {"readiness_score": 0.8, "passed": True, "questions": [{"citation": "AZ-204_Guide.md"}]}})
        eng_cls.return_value.execute = AsyncMock(return_value={})
        mgr_cls.return_value.execute = AsyncMock(return_value={})
        orch = SimpleOrchestrator(fabric_iq=fabric, llm_client=llm, seed=42)
        result = await orch.handle_request({"role": "Cloud Engineer", "certification": "AZ-204", "work_signals": {"focus_hours_per_week": 10}})
    milestones = result["results"]["study_plan"]["output"].get("milestones", [])
    assert len(milestones) == 2
    reinforcement_topics = [m.get("topic", "") for m in milestones if "Hands-on reinforcement" in str(m.get("topic", ""))]
    assert len(reinforcement_topics) == 1


@pytest.mark.asyncio
async def test_critic_retry_second_iteration():
    fabric = MagicMock()
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    fabric.get_certification_requirements.return_value = None
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.8,
        "gap_penalty": 0.0,
    }

    reject = {"accepted": False, "needs_replan": True, "confidence": 0.3, "issues": ["Plan too aggressive"]}
    accept = {"accepted": True, "needs_replan": False, "confidence": 0.9, "issues": []}
    verify_calls = {"n": 0}

    async def verify_side_effect(plan, work_context, learner=None):
        verify_calls["n"] += 1
        return reject if verify_calls["n"] == 1 else accept

    sp_call_count = {"n": 0}
    captured_feedback = {}

    async def sp_execute(input_data):
        sp_call_count["n"] += 1
        if input_data.get("_critic_feedback"):
            captured_feedback["fb"] = input_data["_critic_feedback"]
        return {
            "study_plan": {
                "learner_id": "L-1",
                "certification": "AZ-204",
                "milestones": [{"week": 1, "topic": "Intro", "hours": 5}],
                "total_hours": 40,
                "feasibility_score": 0.7,
            },
            "milestones": [{"week": 1, "topic": "Intro", "hours": 5}],
        }

    with patch("certifyforge_agents.orchestrator.simple_orchestrator.LearningPathCurator") as lp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.StudyPlanGenerator") as sp_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.AssessmentAgent") as ass_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.EngagementAgent") as eng_cls, \
         patch("certifyforge_agents.orchestrator.simple_orchestrator.ManagerInsightsAgent") as mgr_cls, \
         patch.object(SimpleCriticVerifier, "verify_study_plan", side_effect=verify_side_effect), \
         patch.object(SimpleCriticVerifier, "verify_assessment", new_callable=AsyncMock, return_value={"is_valid": True, "confidence": 0.9, "issues": []}):

        lp_cls.return_value.execute = AsyncMock(return_value={"learning_path": {"core_skills": []}})
        sp_cls.return_value.execute = AsyncMock(side_effect=sp_execute)
        ass_cls.return_value.execute = AsyncMock(return_value={
            "assessment": {"readiness_score": 0.8, "passed": True, "questions": [{"citation": "AZ-204_Guide.md"}]}
        })
        eng_cls.return_value.execute = AsyncMock(return_value={})
        mgr_cls.return_value.execute = AsyncMock(return_value={})

        orch = SimpleOrchestrator(fabric_iq=fabric, seed=42)
        result = await orch.handle_request({"role": "Cloud Engineer", "certification": "AZ-204", "work_signals": {"focus_hours_per_week": 10}})

    assert result["iterations"] == 2
    assert sp_call_count["n"] == 2
    assert captured_feedback["fb"]["accepted"] is False


@pytest.mark.asyncio
async def test_fabric_iq_prerequisite_and_alignment_steps():
    cert_reqs = MagicMock()
    cert_reqs.prerequisites = ["AZ-900"]
    cert_reqs.recommended_hours = 80
    cert_reqs.pass_threshold = 0.75
    fabric = MagicMock()
    fabric.get_certification_requirements.return_value = cert_reqs
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.3, "recommended": False}
    fabric.get_missing_prerequisites.return_value = ["AZ-900"]
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.8,
        "gap_penalty": 0.0,
        "feasibility_score": 0.7,
        "estimated_weeks": 8,
        "risk_level": "low",
        "available_focus_per_week": 8,
    }
    fabric.build_skill_gap_analysis.return_value = []
    fabric.estimate_time_to_readiness.return_value = {"estimated_weeks": 8}

    orch = SimpleOrchestrator(fabric_iq=fabric, seed=42)
    result = await orch.handle_request({
        "role": "DevOps Engineer",
        "certification": "AZ-400",
        "work_signals": {"focus_hours_per_week": 8},
    })
    prereq_out = result["results"].get("prerequisite_check", {}).get("output", {})
    alignment_out = result["results"].get("role_alignment_check", {}).get("output", {})
    assert prereq_out.get("prerequisites") == ["AZ-900"]
    assert alignment_out.get("alignment", {}).get("alignment_score") == 0.3