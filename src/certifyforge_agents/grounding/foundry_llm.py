"""
Foundry LLM client: real chat completions via direct AzureOpenAI (key or cognitive AAD/MI).

This completes the "Foundry" side of the architecture:
- Foundry IQ (RAG/citations) via AzureSearchFoundryIQ (already working)
- Real LLM generation via the AI Project model deployment (this module; direct OpenAI client, no AIProjectClient ctor)

It reuses the same azd-first resolver (_get_azd_value) so `azd env set` for
AZURE_AI_PROJECT_ENDPOINT / AZURE_AI_PROJECT_KEY / AZURE_AI_MODEL_DEPLOYMENT_NAME
(or MODEL_DEPLOYMENT_NAME) is the single source of truth, exactly like search.

Supports key auth (for local dev/demo) or DefaultAzureCredential (hosted / RBAC).
"""

import os
from typing import List, Dict, Any, Optional

from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential

from .azure_search_foundry_iq import _get_azd_value, _is_hosted_runtime

# Classic account OpenAI endpoint (embeddings on *.openai.azure.com) uses cognitiveservices scope.
# (Direct AzureOpenAI + this scope used for both key and AAD/MI paths post LLM init hardening.)
_COGNITIVE_SERVICES_TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


def get_foundry_llm_client(
    project_endpoint: Optional[str] = None,
    deployment_name: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """Factory mirroring get_azure_search_foundry_iq for consistency."""
    return FoundryLLMClient(
        project_endpoint=project_endpoint,
        deployment_name=deployment_name,
        api_key=api_key,
    )


class FoundryLLMClient:
    """
    Thin wrapper over Azure AI Project inference for chat completions.

    Usage in a specialist:
        llm = FoundryLLMClient()
        content = llm.generate(
            system_prompt="You are a helpful certification study assistant. ...",
            user_prompt="Using ONLY the grounded content below, produce ...\\n\\n" + grounded_text
        )
    """

    def __init__(
        self,
        project_endpoint: Optional[str] = None,
        deployment_name: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        # azd-first resolution (same helper used for search + project prints in demo).
        # Always defeat stale os.environ values when azd reports the key is absent for the active project.
        ep = (
            project_endpoint
            or _get_azd_value("AZURE_AI_PROJECT_ENDPOINT")
            or _get_azd_value("FOUNDRY_PROJECT_ENDPOINT")
        )
        if not ep:
            for k in ("AZURE_AI_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT"):
                os.environ.pop(k, None)
            ep = (
                os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
                or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
                or ""
            )
        self.project_endpoint = ep

        model_azd = _get_azd_value("AZURE_AI_MODEL_DEPLOYMENT_NAME") or _get_azd_value(
            "MODEL_DEPLOYMENT_NAME"
        )
        if not model_azd:
            for k in ("AZURE_AI_MODEL_DEPLOYMENT_NAME", "MODEL_DEPLOYMENT_NAME"):
                os.environ.pop(k, None)
        model_env = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME") or os.environ.get(
            "MODEL_DEPLOYMENT_NAME"
        )
        dep = deployment_name or model_azd or model_env or "gpt-4.1-mini"
        self.deployment_name = dep

        embed_azd = _get_azd_value("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME")
        if not embed_azd:
            os.environ.pop("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME", None)
        embed_env = os.environ.get("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME")
        self.embedding_deployment = embed_azd or embed_env or None
        if not self.embedding_deployment:
            if self.project_endpoint:
                print(
                    "[LLM][WARN] AZURE_AI_EMBEDDING_DEPLOYMENT_NAME not present via azd (active project/env has no value). "
                    "Vector/hybrid RAG DISABLED (keyword search only). Deploy embedding model (text-embedding-3-small) "
                    "and `azd env set AZURE_AI_EMBEDDING_DEPLOYMENT_NAME text-embedding-3-small` then re-deploy agent."
                )
            # embed() will safely return [] when self.embedding_deployment is falsy

        key = (
            api_key
            or _get_azd_value("AZURE_AI_PROJECT_KEY")
            or os.environ.get("AZURE_AI_PROJECT_KEY")
        )

        self._openai = None

        if key:
            self.credential = AzureKeyCredential(key)
            print("[LLM] Using project API key (key auth) for Foundry LLM calls")
            if _is_hosted_runtime():
                print(
                    "[SECURITY][WARN] Project key injected into hosted container env (prefer MI + correct RBAC; rotate frequently; see security review)."
                )
            # Direct OpenAI client for project + key (discovered working combo for this project's /openai/v1 endpoint)
            try:
                from openai import OpenAI

                base = self.project_endpoint.rstrip("/") + "/openai/v1"
                self._openai = OpenAI(
                    base_url=base,
                    api_key=key,
                    default_headers={"api-version": "2024-12-01-preview"},
                )
            except Exception as ex:
                print(f"[LLM] direct OpenAI(key) construction note: {ex}")
        else:
            self.credential = DefaultAzureCredential()
            print("[LLM] Using DefaultAzureCredential for Foundry LLM calls")

        if not self._openai:
            self._openai = self._build_aad_openai_client()

        self.last_usage = None  # populated after each complete/generate call with {prompt_tokens, completion_tokens, total_tokens}
        self.total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }  # cumulative across calls for observability

        print(
            f"[LLM] FoundryLLMClient initialized: endpoint={self.project_endpoint} deployment={self.deployment_name} (client=direct OpenAI (key or cognitive AAD))"
        )

        # Prepare standard AzureOpenAI client for embeddings (account-level "OpenAI Language Model Instance API").
        # This reaches classic deployments (esp. text-embedding-*) made on the AI Services account (via portal or bicep seqDeployments)
        # even when the project /openai/v1 proxy or inference EmbeddingsClient return 404 Resource not found.
        # Derives https://{subdomain}.openai.azure.com/ from the project endpoint host (works for both azd-managed and manual/existing projects).
        self.aoai_endpoint = None
        self._aoai = None
        try:
            from openai import AzureOpenAI
            from azure.identity import get_bearer_token_provider

            host = (self.project_endpoint or "").split("://")[-1].split("/")[0]
            if ".services.ai.azure.com" in host:
                aoai_host = host.replace(".services.ai.azure.com", ".openai.azure.com")
            else:
                sub = host.split(".")[0] if "." in host else host
                aoai_host = f"{sub}.openai.azure.com"
            self.aoai_endpoint = f"https://{aoai_host}/"
            if key:
                self._aoai = AzureOpenAI(
                    azure_endpoint=self.aoai_endpoint.rstrip("/"),
                    api_key=key,
                    api_version="2024-02-01",
                )
            else:
                token_provider = get_bearer_token_provider(
                    self.credential, _COGNITIVE_SERVICES_TOKEN_SCOPE
                )
                self._aoai = AzureOpenAI(
                    azure_endpoint=self.aoai_endpoint.rstrip("/"),
                    azure_ad_token_provider=token_provider,
                    api_version="2024-02-01",
                )
            print(f"[LLM] Prepared AzureOpenAI client for embeddings: {self.aoai_endpoint}")
        except Exception as ex:
            print(f"[LLM] AzureOpenAI (embeddings) prep note: {ex}")

    def _build_aad_openai_client(self):
        """Build an OpenAI-compatible client for the Foundry project using AAD/MI (direct path only)."""
        if not self.project_endpoint:
            raise ValueError("AZURE_AI_PROJECT_ENDPOINT is required for Foundry LLM calls")

        # Direct AzureOpenAI + token_provider (cognitive scope) is the hardened path for AAD/MI in hosted.
        # (Avoids AIProjectClient ctor issues from prior; guarantees real calls; key path uses plain OpenAI above.)
        from azure.identity import get_bearer_token_provider
        from openai import AzureOpenAI

        # Cognitive scope fixes 401 audience for project /openai/v1 with MI (matches embeddings path).
        token_provider = get_bearer_token_provider(
            self.credential,
            _COGNITIVE_SERVICES_TOKEN_SCOPE,
        )
        project_base = self.project_endpoint.rstrip("/")
        return AzureOpenAI(
            azure_endpoint=f"{project_base}/openai/v1",
            azure_ad_token_provider=token_provider,
            api_version="2024-12-01-preview",
        )

    def complete(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1200,
        **kwargs: Any,
    ) -> str:
        """
        Low-level complete using the project-scoped OpenAI client.

        messages: [{"role": "system" | "user", "content": "..."}, ...]
        Returns the assistant content string (or error string on failure).
        """
        if not messages:
            return ""

        # Normalize to plain dicts for openai SDK
        oai_messages = [
            {"role": (m.get("role") or "user").lower(), "content": m.get("content") or ""}
            for m in messages
        ]

        try:
            resp = self._openai.chat.completions.create(
                model=self.deployment_name,
                messages=oai_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            if resp and resp.choices:
                choice = resp.choices[0]
                content = (
                    choice.message.content.strip()
                    if choice.message and choice.message.content
                    else ""
                )
                # Capture usage for observability / polish
                if hasattr(resp, "usage") and resp.usage:
                    self.last_usage = {
                        "prompt_tokens": getattr(resp.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(resp.usage, "completion_tokens", 0),
                        "total_tokens": getattr(resp.usage, "total_tokens", 0),
                    }
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        self.total_usage[k] += self.last_usage.get(k, 0)
                return content
            self.last_usage = None
            return ""
        except Exception as ex:
            self.last_usage = None
            err = str(ex)[:200]
            print(f"[LLM] complete() failed for model={self.deployment_name}: {err}")
            return ""

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 1200,
        **kwargs: Any,
    ) -> str:
        """Convenience wrapper for the common system + user pattern used by specialists."""
        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.complete(msgs, temperature=temperature, max_tokens=max_tokens, **kwargs)

    def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1200,
    ) -> dict:
        """
        Generate with JSON mode + robust extraction.
        Returns parsed dict (or list as dict for uniformity) or {} on failure.
        Encourages the model to output only JSON.
        """
        import json
        import re

        # Append instruction for strict JSON
        full_user = (
            user_prompt
            + "\n\nIMPORTANT: Return ONLY a single valid JSON object or array. No markdown, no explanations, no ```json fences."
        )

        raw = self.generate(
            system_prompt,
            full_user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

        if not raw:
            return {}

        raw = raw.strip()

        # Direct parse
        try:
            if raw.startswith("{") or raw.startswith("["):
                return json.loads(raw)
        except Exception:
            pass

        # Extract JSON block
        try:
            match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
            if match:
                return json.loads(match.group(1))
        except Exception:
            pass

        # Last resort: try to find any {...}
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            pass

        return {}

    _embed_failure_warned = False

    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text using the embedding deployment.
        Tries (in order):
          1. The project-scoped OpenAI client (/openai/v1) - works for some chat-proxied setups.
          2. azure.ai.inference EmbeddingsClient on the AI Foundry base host.
          3. Standard AzureOpenAI client on the account's "OpenAI Language Model Instance API"
             (https://{sub}.openai.azure.com/) - this is the reliable path for classic account
             deployments of embedding models (the ones bicep creates as 'deployments' and that
             appear in the Azure OpenAI / portal deployment lists). This fixes the persistent
             404 "Resource not found" when using a manual/existing project + portal-deployed
             embedding (or azd-managed account) even if the project inference paths don't surface it.
        """
        if not text or not text.strip() or not getattr(self, "embedding_deployment", None):
            return []
        last_err = None
        model = self.embedding_deployment

        # 1. Project OpenAI client (chat proxy path)
        if self._openai:
            for ver in [
                "2024-02-01",
                "2024-10-01-preview",
                "2024-12-01-preview",
                "2025-01-01-preview",
            ]:
                try:
                    resp = self._openai.embeddings.create(
                        model=model,
                        input=text[:8000],
                        extra_headers={"api-version": ver},
                    )
                    if resp and resp.data:
                        return resp.data[0].embedding
                    return []
                except Exception as ex:
                    last_err = ex
                    if "API version not supported" in str(ex) or "api_version" in str(ex).lower():
                        continue
                    if (
                        "Resource not found" in str(ex)
                        or "404" in str(ex)
                        or "DeploymentNotFound" in str(ex)
                    ):
                        break
                    continue

        # 2. Inference EmbeddingsClient fallback (for inference-routed models)
        try:
            from azure.ai.inference import EmbeddingsClient
            from azure.core.credentials import AzureKeyCredential

            base_host = (self.project_endpoint or "").split("/api/")[0]
            cred = self.credential
            if hasattr(cred, "key"):
                cred = AzureKeyCredential(cred.key)
            for ver in [
                "2024-02-01",
                "2024-10-01-preview",
                "2024-12-01-preview",
                "2025-01-01-preview",
            ]:
                try:
                    temp_client = EmbeddingsClient(
                        endpoint=base_host, credential=cred, api_version=ver
                    )
                    response = temp_client.embed(model=model, input=text[:8000])
                    if response and response.data:
                        return response.data[0].embedding
                    return []
                except Exception as ex:
                    last_err = ex
                    if (
                        "API version not supported" in str(ex)
                        or "api_version" in str(ex).lower()
                        or "unexpected keyword" in str(ex).lower()
                    ):
                        continue
                    continue
        except Exception as ex:
            last_err = ex

        # 3. Standard AzureOpenAI client on the account OpenAI endpoint (the one that actually serves
        #    the deployments created at account level for embeddings). This is the fix for the
        #    "hallucinating" 404s when the project proxy / inference paths don't see the model.
        if getattr(self, "_aoai", None):
            for ver in ["2024-02-01", "2024-10-01-preview", "2025-01-01-preview"]:
                try:
                    # Recreate per-version if needed (ctor version is default; for strict we can ignore or enhance)
                    resp = self._aoai.embeddings.create(
                        model=model,
                        input=text[:8000],
                    )
                    if resp and resp.data:
                        return resp.data[0].embedding
                    return []
                except Exception as ex:
                    last_err = ex
                    msg = str(ex)
                    if (
                        "Resource not found" in msg
                        or "404" in msg
                        or "DeploymentNotFound" in msg
                        or "model_not_found" in msg.lower()
                    ):
                        # Not on this account / wrong name - stop this path
                        break
                    if "API version" in msg or "api_version" in msg.lower():
                        continue
                    continue

        if last_err:
            if not FoundryLLMClient._embed_failure_warned:
                print(f"[LLM] embed failed for model={model}: {str(last_err)[:200]}")
                print(
                    "   (Further embed failures silent. Deploy the embedding model in your Azure AI Project/Foundry portal"
                )
                print(
                    "    OR via azure.yaml + azd provision (for azd-managed projects). Then: azd env set AZURE_AI_EMBEDDING_DEPLOYMENT_NAME <name>"
                )
                print(
                    "   For manual/existing projects the code now auto-derives the account OpenAI endpoint"
                )
                print(
                    "    (https://{subdomain}.openai.azure.com/) and uses the classic AzureOpenAI embeddings API."
                )
                print(
                    "   You can also: azd env set AZURE_OPENAI_ENDPOINT https://<your-subdomain>.openai.azure.com/"
                )
                print(
                    "   Exact name must match the deployment name shown in the portal for that account/project.)"
                )
                FoundryLLMClient._embed_failure_warned = True
            raise last_err
        return []

    def name(self) -> str:
        return f"Foundry LLM ({self.deployment_name})"
