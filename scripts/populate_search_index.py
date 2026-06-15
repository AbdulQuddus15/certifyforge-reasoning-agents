r"""
Populate Azure AI Search index for real Foundry IQ grounding (RAG + citations).

This is the key script to enable *real* grounding instead of the LocalFoundryIQ stub.

It uploads the synthetic certification guides (and supporting files) from
src/data/certification_guides/ into the index used by AzureSearchFoundryIQ.

The index must already exist (or be created by the Bicep + a one-time manual step in portal,
or by extending this script with index creation).

Expected index fields (simple schema that works with the current AzureSearchFoundryIQ + old upload):
    id (Edm.String, key)
    Content (Edm.String, searchable)
    title (Edm.String)
    source (Edm.String)
    certification (Edm.String, optional but recommended for filtering)

Usage (after azd up or having the search service + proper RBAC):

    # From repo root (CREATIVE_APP_02), with venv activated
    cd <your-project-root>
    # (or activate first: .\venv\Scripts\Activate.ps1 )

    # Make sure your azd env has the search outputs (or export the vars)
    azd env get-values

    # Run with the (activated) project python
    python scripts\populate_search_index.py

Environment variables (azd will set many of these after provision):
    AZURE_AI_SEARCH_SERVICE_NAME=...
    AZURE_AI_SEARCH_INDEX_NAME=az204-certification-index   (default)

    Or full:
    AZURE_AI_SEARCH_ENDPOINT=https://yoursearch.search.windows.net

Authentication: DefaultAzureCredential (recommended). Make sure your user has
"Search Index Data Contributor" on the search service.

This script is intentionally simple (character chunking). For production you would
use Azure AI Search indexers, skillsets, or LangChain / LlamaIndex with better
chunking + embeddings if you enable vector search.

Vector/hybrid search support:
- The script reuses FoundryLLMClient (same as demo) to call embed().
- It now tries the project /openai/v1 path, inference EmbeddingsClient, *and* the standard
  AzureOpenAI client on the derived account OpenAI endpoint (https://{sub}.openai.azure.com/).
  This reaches classic deployments created in the portal under your project/account (the
  primary way embeddings become available, even for manual/existing projects like ProjectCert).
- If embedding still 404s, docs are uploaded without content_vector (keyword search still works;
  index schema always includes the vector field).
- To enable vectors + hybrid:
  - For azd project: keep the block in azure.yaml deployments, azd provision, azd env set the EMBEDDING var.
  - For manual project (your current setup): deploy/confirm the model in portal under the project,
    ensure AZURE_AI_PROJECT_ENDPOINT + KEY + AZURE_AI_EMBEDDING_DEPLOYMENT_NAME point at it,
    then re-run this script. Code derives the .openai.azure.com endpoint automatically.
"""

import os
import sys
import pathlib
import subprocess
from pathlib import Path
from typing import List, Dict

# Add the src to path so we can import if needed, but we keep this standalone
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from azure.identity import DefaultAzureCredential
    from azure.search.documents import SearchClient
    from azure.search.documents.indexes import SearchIndexClient
    from azure.search.documents.indexes.models import (
        SearchIndex,
        SimpleField,
        SearchFieldDataType,
        SearchableField,
        SearchField,
        VectorSearch,
        VectorSearchProfile,
        HnswAlgorithmConfiguration,
        VectorSearchAlgorithmKind,
    )
except ImportError:
    print("Missing azure-search-documents or azure-identity.")
    print("   In the project venv: pip install azure-search-documents azure-identity")
    sys.exit(1)

# --- Configuration (prefers azd / env vars set by the Bicep outputs) ---
def _get_azd_value(key: str) -> str:
    """Prefer azd env (with forced project root cwd), fallback to os.environ ONLY if azd cannot provide context.
    When azd project is active but key absent -> return "" so stale os.environ (e.g. old 2941 endpoint) is ignored.
    """
    try:
        this_file = pathlib.Path(__file__).resolve()
        # scripts/ -> CREATIVE_APP_02/
        project_root = this_file.parent
        result = subprocess.run(
            ["azd", "env", "get-value", key],
            capture_output=True, text=True, check=False,
            cwd=str(project_root)
        )
        out = (result.stdout or "").strip()
        if result.returncode == 0:
            if out and not out.startswith("ERROR:"):
                os.environ[key] = out
                return out
        lower_out = out.lower()
        if "no project exists" in lower_out or "no environment configuration" in lower_out:
            return os.environ.get(key, "")
        return ""
    except Exception:
        return os.environ.get(key, "")

# Use the exact same central resolver as the runtime demo (ensures identical service/endpoint/key decisions).
try:
    from certifyforge_agents.grounding.azure_search_foundry_iq import get_azure_search_config
    cfg = get_azure_search_config()
    SEARCH_SERVICE_NAME = cfg["search_service_name"]
    INDEX_NAME = cfg["index_name"]
    SEARCH_ENDPOINT = cfg["endpoint"]
except Exception:
    # Fallback for completely standalone use (no src on path)
    SEARCH_SERVICE_NAME = _get_azd_value("AZURE_AI_SEARCH_SERVICE_NAME")
    INDEX_NAME = _get_azd_value("AZURE_AI_SEARCH_INDEX_NAME") or os.environ.get("AZURE_AI_SEARCH_INDEX_NAME") or "az204-certification-index"
    SEARCH_ENDPOINT = (
        _get_azd_value("AZURE_AI_SEARCH_ENDPOINT")
        or _get_azd_value("AZURE_SEARCH_SERVICE_ENDPOINT")
    )
    if not SEARCH_ENDPOINT and SEARCH_SERVICE_NAME:
        SEARCH_ENDPOINT = f"https://{SEARCH_SERVICE_NAME}.search.windows.net"

# Embeddings support for vector/hybrid search (reuses the Foundry LLM client + project for embeddings)
EMBED_LLM = None
EMBED_MODEL = None
try:
    from certifyforge_agents.grounding.foundry_llm import get_foundry_llm_client
    EMBED_LLM = get_foundry_llm_client()
    EMBED_MODEL = getattr(EMBED_LLM, "embedding_deployment", None)
    if EMBED_MODEL:
        print(f"[Populate] Vector embeddings ENABLED (deployment={EMBED_MODEL})")
    else:
        print("[Populate] AZURE_AI_EMBEDDING_DEPLOYMENT_NAME not set — keyword-only upload.")
        EMBED_LLM = None
except Exception as ex:
    print(f"[Populate] Vector embeddings DISABLED (no project LLM client): {ex}. Will upload without vectors (keyword search only).")
    EMBED_LLM = None

# Data location in this project
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "src" / "data" / "certification_guides"

# Files we know about (title, cert tag for metadata)
FILES_TO_UPLOAD = [
    ("AZ-204_Guide.md", "AZ-204 Guide", "AZ-204"),
    ("AZ-400_Guide.md", "AZ-400 Guide", "AZ-400"),
    ("DP-203_Guide.md", "DP-203 Guide", "DP-203"),
    ("Role_certification_matrix", "Role to Certification Matrix", "General"),
    ("Team_Performance_Patterns", "Team Performance Patterns", "General"),
]

CHUNK_SIZE = 1100
CHUNK_OVERLAP = 120


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Simple overlapping chunker."""
    chunks: List[str] = []
    start = 0
    text = text.strip()
    while start < len(text):
        end = start + size
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


def load_documents() -> List[Dict]:
    documents: List[Dict] = []

    for filename, title, cert in FILES_TO_UPLOAD:
        filepath = DATA_DIR / filename
        if not filepath.exists():
            print(f"⚠️  Skipping missing: {filepath}")
            continue

        raw = filepath.read_text(encoding="utf-8", errors="ignore")
        print(f"Processing {filename} ({len(raw)} chars)")

        if filename.endswith(".md"):
            chunks = chunk_text(raw)
            print(f"   Split into {len(chunks)} chunks")
        else:
            chunks = [raw]

        for i, chunk in enumerate(chunks):
            doc_id = f"{filename.replace('.', '_').replace(' ', '-')}-{i+1:03d}"
            vec = []
            embed_err = None
            if EMBED_LLM:
                try:
                    vec = EMBED_LLM.embed(chunk)
                except Exception as ex:
                    embed_err = ex
                    vec = []
                if not vec:
                    # One-time guidance on first failure
                    if not hasattr(EMBED_LLM, "_embed_warned"):
                        err_msg = str(embed_err)[:200] if embed_err else "unknown error"
                        print(f"   [Populate] WARNING: Embedding generation failed for model={EMBED_MODEL}: {err_msg}")
                        print("   This usually means the embedding model is not deployed (or not visible on the *account's* OpenAI endpoint used for embeddings).")
                        print("   Note: your azd env may track one project/account while AZURE_AI_PROJECT_ENDPOINT/KEY point at a manual/existing one (e.g. ProjectCert on projectcert-resource).")
                        print("   azure.yaml + azd provision only affects the azd-tracked project (AI_PROJECT_DEPLOYMENTS).")
                        print("   Exact steps:")
                        print("     For azd-managed project:")
                        print("       1. Ensure azure.yaml under services.certifyforge-agents.config.deployments has a block for text-embedding-3-small (it does).")
                        print("       2. azd provision   (re-applies deployments to the azd account)")
                        print("       3. azd env set AZURE_AI_EMBEDDING_DEPLOYMENT_NAME text-embedding-3-small")
                        print("       4. (Optional but recommended) azd env set AZURE_OPENAI_ENDPOINT https://<subdomain-from-account>.openai.azure.com/")
                        print("     For your manual/existing ProjectCert (current target):")
                        print("       - Deploy (or confirm) text-embedding-3-small in the Azure Portal under the ProjectCert project / account (exact name, succeeded).")
                        print("       - The code now auto-derives the account OpenAI endpoint (https://projectcert-resource.openai.azure.com/) and tries the classic AzureOpenAI embeddings API.")
                        print("       - Re-run: python scripts\\populate_search_index.py")
                        print("     (The index schema will be updated automatically. Uploads succeed without vectors until this works.)")
                        EMBED_LLM._embed_warned = True
            doc = {
                "id": doc_id,
                "Content": chunk,          # Capital C to match common schema
                "title": title if len(chunks) == 1 else f"{title} (part {i+1})",
                "source": filename,
                "certification": cert,
            }
            if vec:  # only include if we have a real embedding (avoids issues with [] on some indexes)
                doc["content_vector"] = vec
            documents.append(doc)

    return documents


def ensure_index(client: SearchIndexClient, index_name: str):
    """Ensure the index exists and has the expected schema (including vector field for hybrid search).
    If the index already exists but is missing the vector field (from a previous run), this will update it.
    """
    try:
        existing = client.get_index(index_name)
        print(f"Index '{index_name}' already exists. Ensuring schema is up to date (adding vector field if missing)...")
    except Exception:
        print(f"Creating index '{index_name}' ...")

    # Define the desired index with vector support (1536 dims for text-embedding-ada-002 style)
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(
                name="default-hnsw",
                kind=VectorSearchAlgorithmKind.HNSW,
            )
        ],
        profiles=[
            VectorSearchProfile(
                name="default-vector-profile",
                algorithm_configuration_name="default-hnsw",
            )
        ],
    )
    index = SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SearchableField(name="Content", type=SearchFieldDataType.String, searchable=True),
            SimpleField(name="title", type=SearchFieldDataType.String, searchable=True),
            SimpleField(name="source", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="certification", type=SearchFieldDataType.String, filterable=True),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="default-vector-profile",
            ),
        ],
        vector_search=vector_search,
    )
    client.create_or_update_index(index)
    print(f"Index '{index_name}' is ready (with vector support).")


def main():
    if not SEARCH_ENDPOINT:
        print("ERROR: No search endpoint found.")
        print("   Set one of:")
        print("     AZURE_AI_SEARCH_SERVICE_NAME=yoursearch")
        print("     AZURE_AI_SEARCH_ENDPOINT=https://yoursearch.search.windows.net")
        print("   Or run from a provisioned azd environment that has the outputs.")
        return

    print(f"Target: {SEARCH_ENDPOINT}")
    print(f"Index : {INDEX_NAME}")

    # Support key auth if AZURE_SEARCH_ADMIN_KEY is set (useful for local upload when RBAC not yet propagated)
    admin_key = None
    try:
        from certifyforge_agents.grounding.azure_search_foundry_iq import get_azure_search_config
        admin_key = get_azure_search_config()["admin_key"]
    except Exception:
        pass
    admin_key = admin_key or _get_azd_value("AZURE_SEARCH_ADMIN_KEY") or os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    if admin_key:
        from azure.core.credentials import AzureKeyCredential
        credential = AzureKeyCredential(admin_key)
        print("Using admin key credential for search operations.")
    else:
        credential = DefaultAzureCredential()

    client = SearchClient(
        endpoint=SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=credential,
    )

    # Ensure the index exists (creates with minimal schema if missing)
    index_client = SearchIndexClient(endpoint=SEARCH_ENDPOINT, credential=credential)
    ensure_index(index_client, INDEX_NAME)

    docs = load_documents()
    if not docs:
        print("Nothing to upload.")
        return

    print(f"\nUploading {len(docs)} documents to real Azure AI Search...")

    try:
        results = client.upload_documents(documents=docs)
        ok = sum(1 for r in results if r.succeeded)
        fail = len(results) - ok
        print(f"Done: {ok} succeeded, {fail} failed")
        if fail:
            for r in results:
                if not r.succeeded:
                    print(f"   - {r.key}: {r.error_message}")
    except Exception as e:
        print(f"Upload failed: {e}")
        print("   Make sure the index exists with fields: id (key), Content, title, source, certification (optional).")
        print("   You can create a basic index in the Azure Portal or extend this script with index creation.")


if __name__ == "__main__":
    main()
