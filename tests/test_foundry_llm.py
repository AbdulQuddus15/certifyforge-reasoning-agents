import os
from unittest.mock import ANY, MagicMock, patch

from certifyforge_agents.grounding.foundry_llm import FoundryLLMClient
from certifyforge_agents.grounding import foundry_llm as foundry_llm_mod


def test_complete_returns_empty_on_sdk_error():
    with patch.object(FoundryLLMClient, "__init__", lambda self, **kw: None):
        client = FoundryLLMClient()
        client.deployment_name = "gpt-test"
        client._openai = MagicMock()
        client._openai.chat.completions.create.side_effect = RuntimeError(
            "DeploymentNotFound 404 secret-detail"
        )
        client.last_usage = None
        client.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        out = client.complete([{"role": "user", "content": "hi"}])
        assert out == ""
        assert "404" not in out
        assert "[LLM error" not in out


def test_embedding_deployment_clears_stale_env_when_azd_empty(monkeypatch):
    monkeypatch.setenv("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME", "text-embedding-ada-002")
    with (
        patch("certifyforge_agents.grounding.foundry_llm._get_azd_value", return_value=""),
        patch("certifyforge_agents.grounding.foundry_llm.DefaultAzureCredential"),
        patch.object(FoundryLLMClient, "_aoai", None, create=True),
    ):
        client = FoundryLLMClient(
            project_endpoint="https://proj.services.ai.azure.com/api/projects/p1"
        )
        assert client.embedding_deployment is None
        assert "AZURE_AI_EMBEDDING_DEPLOYMENT_NAME" not in os.environ
        assert client.embed("x") == []


def test_aad_direct_openai_cognitive_scope_path(monkeypatch):
    monkeypatch.delenv("AZURE_AI_PROJECT_KEY", raising=False)
    fake_openai = MagicMock()
    with (
        patch("certifyforge_agents.grounding.foundry_llm._get_azd_value", return_value=""),
        patch("azure.identity.get_bearer_token_provider", return_value=lambda: "token") as mock_tok,
        patch("openai.AzureOpenAI", return_value=fake_openai) as mock_aoai,
        patch("certifyforge_agents.grounding.foundry_llm.DefaultAzureCredential"),
    ):
        client = FoundryLLMClient(
            project_endpoint="https://projectcert-resource.services.ai.azure.com/api/projects/ProjectCert"
        )
        assert client._openai is fake_openai
        assert mock_aoai.call_args_list[0].kwargs["azure_endpoint"].endswith("/openai/v1")
        # Direct AAD cognitive scope path (no AIProjectClient ctor attempted post-hardening for hosted 401/ctor compatibility).
        mock_tok.assert_any_call(ANY, "https://cognitiveservices.azure.com/.default")
        # Ensure no project client attr (dead code removed in LLM init fix).
        assert (
            not hasattr(client, "_project_client")
            or getattr(client, "_project_client", None) is None
        )


def test_embedding_deployment_none_when_azd_empty(monkeypatch):
    monkeypatch.setenv("HOSTED_AGENT", "1")
    monkeypatch.delenv("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME", raising=False)
    with (
        patch("certifyforge_agents.grounding.foundry_llm._get_azd_value", return_value=""),
        patch("certifyforge_agents.grounding.foundry_llm.DefaultAzureCredential"),
        patch.object(FoundryLLMClient, "_aoai", None, create=True),
    ):
        client = FoundryLLMClient(
            project_endpoint="https://proj.services.ai.azure.com/api/projects/p1"
        )
        assert client.embedding_deployment is None
        assert client.embed("hello") == []
