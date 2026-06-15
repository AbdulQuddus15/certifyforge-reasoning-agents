"""
Real Foundry IQ implementation backed by Azure AI Search.

This class connects to the Azure AI Search index provisioned by the project's Bicep templates
(typically `az204-certification-index` or similar).

It implements the same interface as LocalFoundryIQ so it can be swapped in transparently.
"""

import inspect
import os
import subprocess
import pathlib
from typing import List, Dict, Any, Optional

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.models import VectorizedQuery

from .base import FoundryIQ


def _is_hosted_runtime() -> bool:
    return os.environ.get("HOSTED_AGENT", "").strip().lower() in ("1", "true", "yes")


def _get_azd_value(key: str) -> str:
    """Get value preferring azd env (authoritative source of truth).

    - Always invoke azd with explicit cwd at project root (4 parents from this file) so it works
      when python is launched from src/ or certifyforge_agents/ (user's common PowerShell pattern).
    - If azd project is active but key is absent -> return "" (ignore any stale value in os.environ).
      This defeats leftover AZURE_AI_SEARCH_ENDPOINT=https://srch-29413975... etc from prior shells/provisions.
    - Only fall back to os.environ if azd itself could not be consulted (not in PATH, or no project context at all).
    - After successful azd fetch, propagate to os.environ for downstream consistency.
    - In hosted containers (HOSTED_AGENT=1), skip azd subprocess and read os.environ only.
    """
    if _is_hosted_runtime():
        return os.environ.get(key, "")
    try:
        this_file = pathlib.Path(__file__).resolve()
        # grounding/azure... -> grounding/ -> certifyforge_agents/ -> src/ -> CREATIVE_APP_02/
        project_root = this_file.parent.parent.parent.parent
        result = subprocess.run(
            ["azd", "env", "get-value", key],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(project_root),
        )
        out = (result.stdout or "").strip()
        if result.returncode == 0:
            if out and not out.startswith("ERROR:"):
                os.environ[key] = out
                return out
        # azd ran (project context existed or not)
        lower_out = out.lower()
        if "no project exists" in lower_out or "no environment configuration" in lower_out:
            # no azd context at all -> allow os.environ fallback (manual export use-case)
            return os.environ.get(key, "")
        # azd project was active, key simply not present in this env -> do NOT let stale os win
        return ""
    except Exception:
        # azd CLI not available or other hard failure -> fallback
        return os.environ.get(key, "")


def get_azure_search_config() -> dict:
    """Central resolver for Azure AI Search config.

    Always prefers azd (with correct root cwd). When azd has SERVICE_NAME but no *_ENDPOINT var,
    we explicitly pop any stale ENDPOINT from os.environ and build the endpoint from the service name.
    This guarantees the SearchClient hits the service the user last did `azd env set AZURE_AI_SEARCH_SERVICE_NAME ...` for.
    Returns dict usable by demo, populate, and the IQ class.
    """
    service = _get_azd_value("AZURE_AI_SEARCH_SERVICE_NAME")
    index = _get_azd_value("AZURE_AI_SEARCH_INDEX_NAME") or "az204-certification-index"
    admin = _get_azd_value("AZURE_SEARCH_ADMIN_KEY")
    ep = _get_azd_value("AZURE_AI_SEARCH_ENDPOINT") or _get_azd_value(
        "AZURE_SEARCH_SERVICE_ENDPOINT"
    )

    if service:
        os.environ["AZURE_AI_SEARCH_SERVICE_NAME"] = service
        if not ep:
            os.environ.pop("AZURE_AI_SEARCH_ENDPOINT", None)
            os.environ.pop("AZURE_SEARCH_SERVICE_ENDPOINT", None)
    if index:
        os.environ["AZURE_AI_SEARCH_INDEX_NAME"] = index
    if admin:
        os.environ["AZURE_SEARCH_ADMIN_KEY"] = admin
    if ep:
        os.environ["AZURE_AI_SEARCH_ENDPOINT"] = ep

    if not ep and service:
        ep = f"https://{service}.search.windows.net"

    if ep:
        os.environ["AZURE_AI_SEARCH_ENDPOINT"] = ep

    return {
        "search_service_name": service,
        "index_name": index,
        "endpoint": ep,
        "admin_key": admin,
    }


class AzureSearchFoundryIQ(FoundryIQ):
    """
    Production-grade Foundry IQ using Azure AI Search.

    Expected environment / configuration:
    - AZURE_AI_SEARCH_SERVICE_NAME or full endpoint
    - AZURE_AI_SEARCH_INDEX_NAME (e.g. "az204-certification-index")
    - Uses Managed Identity / DefaultAzureCredential (recommended for hosted agents)
    """

    def __init__(
        self,
        search_service_name: Optional[str] = None,
        index_name: Optional[str] = None,
        credential=None,
        endpoint: Optional[str] = None,
        admin_key: Optional[str] = None,
        llm_client=None,  # optional FoundryLLMClient to enable embeddings / vector search
    ):
        # Use central resolver for azd-first values + stale ENDPOINT cleanup. Then apply ctor overrides.
        cfg = get_azure_search_config()

        env_service = cfg["search_service_name"]
        env_index = cfg["index_name"]
        env_admin_key = cfg["admin_key"]
        env_endpoint = cfg["endpoint"]

        self.search_service_name = (
            search_service_name or env_service or os.environ.get("AZURE_AI_SEARCH_SERVICE_NAME")
        )
        self.index_name = (
            index_name
            or env_index
            or os.environ.get("AZURE_AI_SEARCH_INDEX_NAME", "az204-certification-index")
        )

        self.llm_client = llm_client

        # Endpoint decision (strict): explicit param (advanced) > azd endpoint > build from (passed or azd) service > last os
        if endpoint:
            self.endpoint = endpoint
        elif env_endpoint:
            self.endpoint = env_endpoint
        elif self.search_service_name:
            self.endpoint = f"https://{self.search_service_name}.search.windows.net"
        else:
            os_ep = os.environ.get("AZURE_AI_SEARCH_ENDPOINT") or os.environ.get(
                "AZURE_SEARCH_SERVICE_ENDPOINT"
            )
            if os_ep:
                self.endpoint = os_ep
            else:
                raise ValueError(
                    "Provide search_service_name, or set AZURE_AI_SEARCH_SERVICE_NAME / AZURE_AI_SEARCH_ENDPOINT"
                )

        # Use admin key if present in env (via azd ${} or ctor), even in hosted (for MI role/propagation/Instance Identity 403 cases).
        # Falls back to DefaultAzureCredential/MI only if no key. Keeps local demo parity + defensive hosted.
        effective_key = admin_key or env_admin_key or os.environ.get("AZURE_SEARCH_ADMIN_KEY")
        if effective_key:
            self.credential = AzureKeyCredential(effective_key)
            print("[Grounding] Using Azure Search admin key (key auth)")
            if _is_hosted_runtime():
                print(
                    "[SECURITY][WARN] Admin key injected into hosted container env (prefer MI + RBAC 'Search Index Data Reader' on Instance Identity principal from azd ai agent show; rotate; see security review)."
                )
        else:
            self.credential = credential or DefaultAzureCredential()
            print("[Grounding] Using DefaultAzureCredential for Azure Search (MI in hosted)")

        print(
            f"[Grounding] AzureSearchFoundryIQ built: endpoint={self.endpoint} service={self.search_service_name} index={self.index_name} key_auth={bool(effective_key)}"
        )

        self.client = SearchClient(
            endpoint=self.endpoint, index_name=self.index_name, credential=self.credential
        )

    def name(self) -> str:
        svc = self.search_service_name or self.endpoint.replace("https://", "").split(".")[0]
        return f"Foundry IQ (Azure AI Search - {svc} / {self.index_name})"

    async def query(self, query: str, **kwargs) -> Any:
        """Perform search (keyword or hybrid/vector if embeddings available via llm_client)."""
        top_k = kwargs.get("top_k", 5)
        query_vec = None
        if self.llm_client and hasattr(self.llm_client, "embed"):
            try:
                query_vec = self.llm_client.embed(query)
            except Exception as ex:
                # Never let embed failure kill the request; caller gets keyword results (still useful).
                if not getattr(self, "_embed_fail_logged", False):
                    print(f"[Grounding] llm.embed for hybrid failed (keyword-only this run): {ex}")
                    self._embed_fail_logged = True
                query_vec = None

        results = []
        try:
            if query_vec:
                # Hybrid: keyword + vector (better results)
                if not getattr(self, "_vector_search_logged", False):
                    print("[Grounding] Using hybrid search (keyword + vector embeddings)")
                    self._vector_search_logged = True
                # Prefer k= (current SDK); fall back to k_nearest_neighbors for older container images.
                vector_query = self._build_vector_query(query_vec, top_k)
                search_results = self.client.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    top=top_k,
                    query_type="simple",
                    include_total_count=True,
                )
            else:
                # Fallback to pure keyword (backward compatible)
                search_results = self.client.search(
                    search_text=query,
                    top=top_k,
                    query_type="simple",
                    include_total_count=True,
                )

            # Consume the pager here so auth/execution errors are caught in this try block.
            # (The .search() call is often lazy; HTTP + deserialization happens on iteration.)
            for r in search_results:
                # Support both the upload script schema (Content, source, title) and other common variants
                content = (
                    r.get("Content")
                    or r.get("content")
                    or r.get("chunk")
                    or r.get("text")
                    or str(r)[:500]
                )
                citation = (
                    r.get("source")
                    or r.get("title")
                    or r.get("certification")
                    or f"{self.index_name}:{r.get('id', 'unknown')}"
                )
                # Prefer vector score if present, else keyword
                score = (
                    r.get("@search.reranker_score")
                    or r.get("@search.score", 0.0)
                    or (r.get("@search.features", {}) or {})
                    .get("content_vector", {})
                    .get("similarity", 0.0)
                )
                results.append(
                    {
                        "content": content,
                        "citation": citation,
                        "score": score,
                        "vector_score": (r.get("@search.features", {}) or {})
                        .get("content_vector", {})
                        .get("similarity"),
                        "metadata": {k: v for k, v in r.items() if not k.startswith("@")},
                    }
                )

        except Exception as ex:
            err_str = str(ex)
            if query_vec:
                print(
                    f"[Grounding] Hybrid/vector search failed: {err_str}. Falling back to keyword-only (if possible)."
                )
            else:
                print(f"[Grounding] Keyword search failed: {err_str}")

            if (
                "Forbidden" in err_str
                or "401" in err_str
                or "Permission" in err_str
                or "Unauthorized" in err_str
            ):
                print(
                    "[Grounding][ACTION REQUIRED] Search query got Forbidden/401 with Managed Identity."
                )
                print(
                    "   The hosted agent's MI principal needs 'Search Index Data Reader' (or Reader + data plane) on the search service."
                )
                print(
                    "   Example (use the exact principal ID from `azd ai agent show` and adjust subscription/RG if needed):"
                )
                print(
                    f"   az role assignment create --assignee <principal-id> --role 'Search Index Data Reader' --scope /subscriptions/<sub-id>/resourceGroups/rg-creative-app-02-dev/providers/Microsoft.Search/searchServices/{self.search_service_name}"
                )
                print("   Then re-deploy the agent so the MI can use the role.")
            # Return whatever we collected (or empty). Do not let search auth errors kill the whole request.
            # Specialists will still produce output (synthetic fallbacks where applicable).

        return results

    @staticmethod
    def _build_vector_query(query_vec: List[float], top_k: int) -> VectorizedQuery:
        params = inspect.signature(VectorizedQuery.__init__).parameters
        if "k" in params:
            return VectorizedQuery(vector=query_vec, k=top_k, fields="content_vector")
        return VectorizedQuery(
            vector=query_vec,
            k_nearest_neighbors=top_k,
            fields="content_vector",
        )

    @staticmethod
    def _result_cert_tag(result: Dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        return str(meta.get("certification") or meta.get("cert") or "").strip().upper()

    @staticmethod
    def _result_matches_cert(result: Dict[str, Any], certification: str) -> bool:
        cert = certification.strip().upper()
        tag = AzureSearchFoundryIQ._result_cert_tag(result)
        if tag and tag == cert:
            return True
        citation = str(result.get("citation", "")).upper()
        return cert in citation

    @staticmethod
    def _result_is_general(result: Dict[str, Any]) -> bool:
        tag = AzureSearchFoundryIQ._result_cert_tag(result)
        return tag in ("", "GENERAL")

    def _filter_by_certification(
        self, results: List[Dict[str, Any]], certification: Optional[str]
    ) -> List[Dict[str, Any]]:
        if not certification:
            return results
        cert = certification.strip().upper()
        cert_hits = [r for r in results if self._result_matches_cert(r, cert)]
        general_hits = [r for r in results if self._result_is_general(r)]
        if cert_hits:
            return cert_hits + [g for g in general_hits if g not in cert_hits]
        if not hasattr(self, "_cert_miss_logged"):
            self._cert_miss_logged = set()
        if cert not in self._cert_miss_logged:
            print(
                f"[Grounding] No index chunks tagged for {certification}; "
                f"specialists will use local {certification}_Guide.md fallback. "
                "Run populate_search_index.py to index cert-specific content."
            )
            self._cert_miss_logged.add(cert)
        return []

    async def retrieve_with_citations(
        self, query: str, top_k: int = 5, certification: Optional[str] = None, **kwargs
    ) -> List[Dict[str, Any]]:
        cert = certification or kwargs.pop("certification", None)
        fetch_k = top_k * 3 if cert else top_k
        results = await self.query(query, top_k=fetch_k, **kwargs)
        filtered = self._filter_by_certification(results, cert)
        return filtered[:top_k]
