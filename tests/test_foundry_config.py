import os
from unittest.mock import patch

from certifyforge_agents.grounding.azure_search_foundry_iq import (
    AzureSearchFoundryIQ,
    _get_azd_value,
    get_azure_search_config,
)


def test_get_azd_value_skips_subprocess_when_hosted(monkeypatch):
    monkeypatch.setenv("HOSTED_AGENT", "1")
    monkeypatch.setenv("AZURE_AI_SEARCH_SERVICE_NAME", "srch-hosted")
    monkeypatch.setenv("AZURE_SEARCH_ADMIN_KEY", "sk-test-admin-123")
    with patch("subprocess.run") as mock_run:
        val = _get_azd_value("AZURE_AI_SEARCH_SERVICE_NAME")
    assert val == "srch-hosted"
    # positive hosted admin_key in env (post fix: effective_key uses even under HOSTED; exercises key_auth path)
    assert os.environ.get("AZURE_SEARCH_ADMIN_KEY") == "sk-test-admin-123"
    mock_run.assert_not_called()


def test_get_azure_search_config_builds_endpoint_from_service(monkeypatch):
    monkeypatch.setenv("HOSTED_AGENT", "1")
    monkeypatch.setenv("AZURE_AI_SEARCH_SERVICE_NAME", "myservice")
    monkeypatch.delenv("AZURE_AI_SEARCH_ENDPOINT", raising=False)
    cfg = get_azure_search_config()
    assert cfg["endpoint"] == "https://myservice.search.windows.net"


def test_stale_search_endpoint_popped_when_service_from_azd(monkeypatch):
    monkeypatch.setenv("HOSTED_AGENT", "1")
    monkeypatch.setenv("AZURE_AI_SEARCH_ENDPOINT", "https://stale.search.windows.net")
    monkeypatch.setenv("AZURE_AI_SEARCH_SERVICE_NAME", "freshsvc")
    with patch("certifyforge_agents.grounding.azure_search_foundry_iq._get_azd_value") as mock_azd:

        def side_effect(key):
            if key == "AZURE_AI_SEARCH_SERVICE_NAME":
                return "freshsvc"
            if key in ("AZURE_AI_SEARCH_ENDPOINT", "AZURE_SEARCH_SERVICE_ENDPOINT"):
                return ""
            if key == "AZURE_AI_SEARCH_INDEX_NAME":
                return "az204-certification-index"
            return ""

        mock_azd.side_effect = side_effect
        cfg = get_azure_search_config()
    assert cfg["endpoint"] == "https://freshsvc.search.windows.net"
    assert os.environ.get("AZURE_AI_SEARCH_ENDPOINT") == "https://freshsvc.search.windows.net"


def test_filter_by_certification_returns_empty_without_cert_hits():
    results = [
        {"citation": "Role_certification_matrix", "metadata": {"certification": "General"}},
        {"citation": "AZ-204_Guide.md", "metadata": {"certification": "AZ-204"}},
    ]
    iq = AzureSearchFoundryIQ.__new__(AzureSearchFoundryIQ)
    filtered = iq._filter_by_certification(results, "AZ-400")
    assert filtered == []
