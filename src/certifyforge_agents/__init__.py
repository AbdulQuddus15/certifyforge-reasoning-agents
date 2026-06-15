"""
CertifyForge Reasoning Agents

Clean implementation following the official Reasoning Agents architecture document.

Priority order being followed:
1. A (Orchestrator + Critic + Data Models) ← Currently finishing
2. B (Synthetic Data Loaders + Datasets)
3. C (Specialist implementations, grounding, evaluation, etc.)
"""

from .data.models import *
from .data.loader import SyntheticDataLoader
from .data.factory import SyntheticDataFactory
from .orchestrator.simple_orchestrator import SimpleOrchestrator
from .evaluation.simple_critic import SimpleCriticVerifier
from .grounding.fabric_iq import FabricIQ
from .grounding.foundry_iq import LocalFoundryIQ
from .grounding.foundry_llm import FoundryLLMClient, get_foundry_llm_client

def get_azure_search_foundry_iq(*args, **kwargs):
    """Lazy import to avoid requiring azure packages unless actually used.
    Supports search_service_name, index_name, endpoint, credential, admin_key.
    """
    from .grounding.azure_search_foundry_iq import AzureSearchFoundryIQ, _get_azd_value, get_azure_search_config
    return AzureSearchFoundryIQ(*args, **kwargs)


def get_foundry_llm_client(*args, **kwargs):
    """Lazy import for the real Foundry LLM client (Azure AI Project)."""
    from .grounding.foundry_llm import FoundryLLMClient as _FoundryLLMClient, get_foundry_llm_client as _get
    # allow both direct class and the factory
    if args or kwargs:
        return _get(*args, **kwargs)
    return _FoundryLLMClient

__all__ = [
    "SyntheticDataLoader",
    "SyntheticDataFactory",
    "SimpleOrchestrator",
    "SimpleCriticVerifier",
    "FabricIQ",
    "LocalFoundryIQ",
    "get_azure_search_foundry_iq",
    "_get_azd_value",
    "get_azure_search_config",
    "FoundryLLMClient",
    "get_foundry_llm_client",
]
