import pytest
from unittest.mock import AsyncMock, MagicMock

from certifyforge_agents.agents.study_plan_generator import StudyPlanGenerator
from certifyforge_agents.agents.assessment_agent import AssessmentAgent
from certifyforge_agents.agents.engagement_agent import EngagementAgent
from certifyforge_agents.agents.manager_insights_agent import ManagerInsightsAgent
from certifyforge_agents.agents.learning_path_curator import LearningPathCurator


@pytest.mark.asyncio
async def test_assessment_agent_degraded_without_rag():
    agent = AssessmentAgent(grounding=MagicMock())
    agent.grounding.retrieve_with_citations = AsyncMock(return_value=[])
    result = await agent.execute({"certification": "AZ-204"})
    assert result["assessment"]["degraded"] is True
    assert result["assessment"]["questions"] == []
    assert result["grounded_in"] == []


@pytest.mark.asyncio
async def test_study_plan_generator_applies_critic_feedback():
    fabric = MagicMock()
    fabric.get_certification_requirements.return_value = MagicMock(recommended_hours=80)
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9, "recommended": True}
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.7,
        "gap_penalty": 0.0,
        "available_focus_per_week": 10,
        "risk_level": "low",
        "estimated_weeks": 8,
        "feasibility_score": 0.7,
    }
    fabric.build_skill_gap_analysis.return_value = []
    fabric.estimate_time_to_readiness.return_value = {"estimated_weeks": 8}
    agent = StudyPlanGenerator(grounding=fabric)
    base = await agent.execute({
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "learning_path": {"core_skills": ["Compute"]},
        "work_signals": {"focus_hours_per_week": 10},
    })
    reduced = await agent.execute({
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "learning_path": {"core_skills": ["Compute"]},
        "work_signals": {"focus_hours_per_week": 10},
        "_critic_feedback": {
            "accepted": False,
            "issues": ["Capacity utilization high (1.2). Risk of burnout."],
            "needs_replan": False,
        },
    })
    assert reduced["study_plan"]["total_hours"] <= base["study_plan"]["total_hours"]


@pytest.mark.asyncio
async def test_engagement_agent_schema():
    agent = EngagementAgent()
    result = await agent.execute({"work_signals": {"focus_hours_per_week": 8, "preferred_learning_slot": "Evening"}})
    assert "recommendations" in result
    assert result["recommendations"]["best_slots"] == ["Evening"]


@pytest.mark.asyncio
async def test_manager_insights_agent_schema():
    agent = ManagerInsightsAgent()
    result = await agent.execute({"team_id": "TEAM-1"})
    assert result["insights"]["team_id"] == "TEAM-1"
    assert "recommended_actions" in result["insights"]


@pytest.mark.asyncio
async def test_manager_insights_sanitizes_team_id():
    agent = ManagerInsightsAgent()
    result = await agent.execute({"team_id": "TEAM\x00-1\nINJECT"})
    assert "\x00" not in result["insights"]["team_id"]
    assert "\n" not in result["insights"]["team_id"]


@pytest.mark.asyncio
async def test_assessment_agent_llm_synthesis_with_valid_citation():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[
        {"citation": "AZ-204_Guide.md", "content": "Azure Functions hosting models"},
    ])
    llm = MagicMock()
    llm.generate_structured.return_value = [
        {"question": "What is a consumption plan?", "citation": "AZ-204_Guide.md", "difficulty": "Medium"},
    ]
    agent = AssessmentAgent(grounding=grounding, llm=llm)
    result = await agent.execute({"certification": "AZ-204"})
    assert result.get("llm_synthesized") is True
    assert len(result["assessment"]["questions"]) == 1
    assert result["assessment"]["questions"][0]["citation"] == "AZ-204_Guide.md"


@pytest.mark.asyncio
async def test_assessment_agent_skips_hallucinated_citation():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[
        {"citation": "AZ-204_Guide.md", "content": "Azure Functions hosting models"},
    ])
    llm = MagicMock()
    llm.generate_structured.return_value = [
        {"question": "Fake?", "citation": "Totally_Fake_Guide.md", "difficulty": "Hard"},
    ]
    agent = AssessmentAgent(grounding=grounding, llm=llm)
    result = await agent.execute({"certification": "AZ-204"})
    assert result.get("llm_synthesized") is not True
    assert all(q["citation"] == "AZ-204_Guide.md" for q in result["assessment"]["questions"])


@pytest.mark.asyncio
async def test_learning_path_curator_llm_synthesis_with_valid_citation():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[
        {"citation": "AZ-204_Guide.md", "content": "Functions and App Service patterns"},
    ])
    grounding.get_certification_overview = MagicMock(return_value={"recommended_hours": 80})
    grounding.get_skills_for_certification = MagicMock(return_value=["Compute"])
    llm = MagicMock()
    llm.generate_structured.return_value = [
        {"title": "Functions", "description": "Serverless basics", "citation": "AZ-204_Guide.md", "estimated_hours": 12},
    ]
    agent = LearningPathCurator(grounding=grounding, llm=llm)
    result = await agent.execute({"role": "Cloud Engineer", "certification": "AZ-204"})
    assert result["learning_path"].get("llm_synthesized") is True
    assert result["learning_path"]["modules"][0]["citation"] == "AZ-204_Guide.md"


@pytest.mark.asyncio
async def test_learning_path_curator_skips_hallucinated_citation():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[
        {"citation": "AZ-204_Guide.md", "content": "Functions"},
    ])
    grounding.get_certification_overview = MagicMock(return_value={"recommended_hours": 80})
    grounding.get_skills_for_certification = MagicMock(return_value=["Compute"])
    llm = MagicMock()
    llm.generate_structured.return_value = [
        {"title": "Fake", "description": "Bad", "citation": "Fake_Guide.md", "estimated_hours": 10},
    ]
    agent = LearningPathCurator(grounding=grounding, llm=llm)
    result = await agent.execute({"role": "Cloud Engineer", "certification": "AZ-204"})
    assert result["learning_path"].get("llm_synthesized") is not True
    assert result["learning_path"]["modules"][0]["citation"] == "AZ-204_Guide.md"


@pytest.mark.asyncio
async def test_study_plan_generator_llm_milestones():
    fabric = MagicMock()
    fabric.get_certification_requirements.return_value = MagicMock(recommended_hours=80)
    fabric.role_certification_alignment.return_value = {"alignment_score": 0.9}
    fabric.calculate_plan_feasibility.return_value = {
        "is_feasible": True,
        "capacity_utilization": 0.7,
        "gap_penalty": 0.0,
        "available_focus_per_week": 10,
        "risk_level": "low",
        "estimated_weeks": 8,
        "feasibility_score": 0.7,
    }
    fabric.build_skill_gap_analysis.return_value = []
    fabric.estimate_time_to_readiness.return_value = {"estimated_weeks": 8}
    llm = MagicMock()
    llm.generate_structured.return_value = [
        {"week": 1, "topic": "Functions deep dive", "focus_area": "Labs", "hours": 8, "prerequisites": []},
    ]
    agent = StudyPlanGenerator(grounding=fabric, llm=llm)
    result = await agent.execute({
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "learning_path": {"core_skills": ["Functions"], "modules": [{"title": "Functions", "citation": "AZ-204_Guide.md"}]},
        "work_signals": {"focus_hours_per_week": 10},
    })
    assert result["study_plan"]["milestones"][0]["topic"] == "Functions deep dive"


@pytest.mark.asyncio
async def test_assessment_agent_critic_trim_on_retry():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[
        {"citation": "AZ-204_Guide.md", "content": "topic"},
        {"citation": "AZ-204_Guide.md", "content": "topic2"},
        {"citation": "AZ-204_Guide.md", "content": "topic3"},
    ])
    agent = AssessmentAgent(grounding=grounding)
    base = await agent.execute({"certification": "AZ-204"})
    trimmed = await agent.execute({
        "certification": "AZ-204",
        "_critic_feedback": {"accepted": False, "issues": ["low score"]},
    })
    assert len(trimmed["assessment"]["questions"]) <= len(base["assessment"]["questions"])