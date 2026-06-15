import pytest
from unittest.mock import AsyncMock, MagicMock

from certifyforge_agents.agents.learning_path_curator import LearningPathCurator


@pytest.mark.asyncio
async def test_degraded_when_no_rag_modules():
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[])
    curator = LearningPathCurator(grounding=grounding, llm=None)
    result = await curator.execute({"role": "Cloud Engineer", "certification": "AZ-204"})
    lp = result["learning_path"]
    assert lp["degraded"] is True
    assert len(lp["modules"]) >= 1
    assert all("AZ-204_Guide.md" in m.get("citation", "") for m in lp["modules"])
    assert "AZ-204_Guide.md" in lp["grounded_in"]


@pytest.mark.asyncio
async def test_assessment_agent_no_fake_guide_citations():
    from certifyforge_agents.agents.assessment_agent import AssessmentAgent
    grounding = MagicMock()
    grounding.retrieve_with_citations = AsyncMock(return_value=[])
    agent = AssessmentAgent(grounding=grounding, llm=None)
    result = await agent.execute({"certification": "AZ-204"})
    assert result["assessment"]["degraded"] is True
    assert "Guide" not in str(result["grounded_in"])