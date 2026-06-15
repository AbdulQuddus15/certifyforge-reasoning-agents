"""Shared citation faithfulness helpers for specialist agents."""

from __future__ import annotations

import re
from typing import List, Optional


def _normalize_citation(value: str) -> str:
    x = value.lower().replace("_", " ").replace("-", " ").replace(".md", "").strip()
    x = x.replace(" (part ", " part ").replace(")", "").strip()
    return " ".join(x.split())


def match_citation(cit: str, allowed: List[str]) -> Optional[str]:
    """Robust citation matcher for LLM outputs vs allowed list from RAG.

    Handles exact, substring, case, whitespace, .md omission, and 'part X' variants.
    Returns the canonical allowed string or None.
    """
    if not cit:
        return None
    cit_s = str(cit).strip()
    if cit_s in allowed:
        return cit_s
    for c in allowed:
        if c and (c in cit_s or cit_s in c):
            return c
    n_cit = _normalize_citation(cit_s)
    for c in allowed:
        n_c = _normalize_citation(c)
        if n_c == n_cit or n_c in n_cit or n_cit in n_c:
            return c
    for c in allowed:
        key = (c or "").split()[0].lower() if c else ""
        if key and key in n_cit:
            return c
    return None


def sanitize_user_text(value: str, *, max_length: int = 200) -> str:
    """Strip control chars/newlines and cap length for untrusted user fields."""
    if not value:
        return ""
    cleaned = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    cleaned = " ".join(cleaned.split())
    return cleaned[:max_length]


def sanitize_llm_output(value: str, *, max_length: int = 500) -> str:
    """Strip markdown-significant patterns from LLM text before client reflection."""
    if not value:
        return ""
    cleaned = sanitize_user_text(str(value), max_length=max_length)
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)
    cleaned = re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", cleaned)
    cleaned = re.sub(r"(?i)javascript:", "", cleaned)
    cleaned = re.sub(r"(?i)https?://\S+", "[link removed]", cleaned)
    cleaned = re.sub(r"(?i)<script[^>]*>.*?</script>", "", cleaned)
    return cleaned.strip()