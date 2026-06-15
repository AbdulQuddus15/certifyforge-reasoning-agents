"""
Basic Foundry IQ Grounding Layer implementation.

This provides a simple, local implementation that returns cited content from approved guides.
In production this would be replaced by (or backed by) Azure AI Search + semantic reranking
via the Foundry IQ connection.
"""

from typing import List, Dict, Any

from .base import FoundryIQ
from ..data.loader import SyntheticDataLoader


class LocalFoundryIQ(FoundryIQ):
    """
    Local / development implementation of Foundry IQ.

    - Loads content from the synthetic certification guides.
    - Always returns results with citations.
    - Can later be extended or swapped for real Azure AI Search retrieval.
    """

    def __init__(self):
        self.loader = SyntheticDataLoader()

    def name(self) -> str:
        return "Foundry IQ (Local / Stub)"

    async def query(self, query: str, **kwargs) -> Any:
        """Generic query (simple keyword match for now)."""
        cert_id = kwargs.get("certification", "AZ-204")
        guide = self.loader.load_certification_guide(cert_id)

        # Very naive retrieval: return sections containing keywords from the query
        keywords = [w.lower() for w in query.split() if len(w) > 3]
        lines = guide.splitlines()

        relevant = []
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in keywords):
                relevant.append({
                    "content": line.strip(),
                    "citation": f"{cert_id} Guide - line ~{i}",
                    "score": 0.7,
                })

        # Fallback: return first few sections if nothing matched
        if not relevant:
            relevant = [
                {
                    "content": line.strip(),
                    "citation": f"{cert_id} Guide",
                    "score": 0.4,
                }
                for line in lines[:8]
                if line.strip()
            ]

        return relevant[:5]  # top 5

    async def retrieve_with_citations(
        self, 
        query: str, 
        top_k: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """Main method used by agents that need grounded + cited content."""
        results = await self.query(query, **kwargs)
        return results[:top_k]
