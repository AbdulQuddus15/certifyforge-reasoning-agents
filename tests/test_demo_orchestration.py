import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from certifyforge_agents.demo_orchestration import run_demo_orchestration
from certifyforge_agents.readiness_server import run_full_orchestration


@pytest.mark.asyncio
async def test_run_demo_orchestration_offline():
    result = await run_demo_orchestration(seed=42)
    assert result["iterations"] >= 1
    assert "status" in result
    assert "plan" in result
    assert len(result["plan"]) >= 5


@pytest.mark.asyncio
async def test_demo_and_hosted_result_key_parity():
    fixture = {
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "work_signals": {"focus_hours_per_week": 10},
        "seed": 42,
    }
    shared_result = {
        "status": "completed_with_verification",
        "iterations": 1,
        "plan": [{"step": "learning_path"}],
        "results": {
            "learning_path": {"output": {}},
            "study_plan": {"output": {}},
            "assessment": {"output": {}},
        },
    }
    with patch("certifyforge_agents.demo_orchestration.SimpleOrchestrator") as demo_orch, \
         patch("certifyforge_agents.readiness_server.get_foundry_llm_client", side_effect=RuntimeError("no llm")), \
         patch("certifyforge_agents.readiness_server.get_azure_search_config", return_value={}), \
         patch("certifyforge_agents.readiness_server.LocalFoundryIQ"), \
         patch("certifyforge_agents.readiness_server.FabricIQ"), \
         patch("certifyforge_agents.readiness_server.SimpleOrchestrator") as hosted_orch:
        demo_orch.return_value.handle_request = AsyncMock(return_value=shared_result)
        hosted_orch.return_value.handle_request = AsyncMock(return_value=shared_result)
        demo_result = await run_demo_orchestration(seed=42, request=fixture)
        hosted_result = await run_full_orchestration(fixture)
    assert set(demo_result.keys()) == set(hosted_result.keys())
    assert set(demo_result["results"].keys()) == set(hosted_result["results"].keys())