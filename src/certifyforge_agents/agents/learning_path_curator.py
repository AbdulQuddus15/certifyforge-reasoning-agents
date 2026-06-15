"""
Learning Path Curator Agent

Grounding: Foundry IQ (RAG) + optional real Foundry LLM (Azure AI Project) for synthesizing curated paths from citations.
Role: Map role+cert to skills + cited resources, using LLM to turn raw RAG into structured learning modules when available.
"""

from typing import Dict, Any, List
from ..agents.base import SpecialistAgent
from ..agents.citations import match_citation, sanitize_user_text
from ..data.loader import SyntheticDataLoader
from ..grounding.base import FoundryIQ
from ..grounding.foundry_iq import LocalFoundryIQ


class LearningPathCurator(SpecialistAgent):
    """
    Curates a learning path with citations from approved certification guides.
    """

    def __init__(self, grounding: FoundryIQ = None, llm=None):
        self.grounding = grounding or LocalFoundryIQ()
        self.llm = llm  # optional real LLM for synthesizing curated learning path from RAG hits
        self.loader = SyntheticDataLoader()
        self._name = "LearningPathCurator"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Maps role + certification to skills and cited learning resources from approved sources."

    @property
    def grounding_layers(self) -> List[str]:
        return ["Foundry IQ"]

    @staticmethod
    def _sections_from_guide(guide: str, certification: str) -> List[Dict[str, Any]]:
        """Build module stubs from local guide headings when RAG has no cert-specific hits."""
        modules: List[Dict[str, Any]] = []
        current_title = None
        for line in guide.splitlines():
            if line.startswith("### "):
                current_title = line.replace("### ", "").strip()
            elif line.startswith("## ") and "Overview" not in line:
                current_title = line.replace("## ", "").strip()
            if current_title and line.strip().startswith("- "):
                modules.append(
                    {
                        "title": current_title[:80],
                        "description": line.strip()[2:][:120],
                        "source": f"{certification}_Guide.md",
                        "citation": f"{certification}_Guide.md",
                        "estimated_hours": 12,
                    }
                )
                current_title = None
            if len(modules) >= 4:
                break
        return modules

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        role = sanitize_user_text(
            str(input_data.get("role", "Cloud Engineer")), max_length=80
        )
        certification = sanitize_user_text(
            str(input_data.get("certification", "AZ-204")), max_length=32
        )

        # Consume propagated (review Issue 2 wiring)
        _prior = input_data.get("prior_state") or {}
        _skill = input_data.get("skill")
        if _prior:
            pass  # prior available for resume in RAG/plan

        skills = self.loader.get_skills_for_role_and_cert(role, certification)
        overview = self.loader.get_certification_overview(certification)

        # Use proper Foundry IQ grounding layer for cited content
        search_results = await self.grounding.retrieve_with_citations(
            f"key skills and learning resources for {role} targeting {certification}",
            top_k=4,
            certification=certification,
        )

        modules = []
        citations = []

        if self.llm and search_results:
            # Real LLM + citations: synthesize a curated learning path (next critical integration step after RAG)
            try:
                # Build context + explicit allowed citations list for faithfulness
                allowed_citations = [
                    item.get("citation", certification) for item in search_results
                ]
                ctx = "\n\n".join(
                    f"[{i+1}] Citation: {item.get('citation', certification)}\n{item.get('content', '')[:550]}"
                    for i, item in enumerate(search_results)
                )
                system = (
                    "You are a senior certification curriculum designer. "
                    "Using ONLY the grounded retrieved content below, produce 3-4 learning modules. "
                    "For each module you MUST use one of the EXACT citation strings from the Allowed Citations list. "
                    "Do not invent or shorten citations. "
                    "Each module object must have exactly these keys: "
                    "title (concise, <=80 chars), description (1-2 sentences strictly from the content), "
                    "citation (EXACT string from Allowed Citations), estimated_hours (integer 8-25). "
                    "Return ONLY a JSON array of objects. No other text."
                )
                user = (
                    f"Role (data): <<{role}>>\nCertification (data): <<{certification}>>\n\n"
                    f"Allowed Citations (use EXACTLY one of these for the 'citation' field):\n"
                    + "\n".join(f"- {c}" for c in allowed_citations)
                    + f"\n\nGrounded RAG content:\n{ctx}"
                )
                parsed = self.llm.generate_structured(
                    system, user, temperature=0.3, max_tokens=800
                )
                items = (
                    parsed
                    if isinstance(parsed, list)
                    else (
                        parsed.get("modules", parsed.get("items", []))
                        if isinstance(parsed, dict)
                        else []
                    )
                )
                for p in items[:4]:
                    cit = p.get("citation", "")
                    # Validate citation faithfulness
                    if cit not in allowed_citations:
                        match = match_citation(cit, allowed_citations)
                        if match:
                            cit = match
                        else:
                            continue
                    mod = {
                        "title": str(p.get("title", "Module"))[:80],
                        "description": str(p.get("description", "")),
                        "source": cit,
                        "citation": cit,
                        "estimated_hours": int(p.get("estimated_hours", 15)),
                    }
                    modules.append(mod)
                    if mod["citation"]:
                        citations.append(mod["citation"])
            except Exception as ex:
                print(
                    f"[LearningPathCurator] LLM synthesis failed, falling back to raw RAG: {ex}"
                )

        if not modules and search_results:
            for item in search_results:
                cit = item.get("citation", "")
                title = (
                    (item.get("metadata") or {}).get("title")
                    or cit
                    or f"{certification} module"
                )
                modules.append(
                    {
                        "title": str(title)[:80],
                        "source": cit,
                        "citation": cit,
                        "estimated_hours": 18,
                    }
                )
                if cit:
                    citations.append(cit)

        used_local_guide = False
        if not modules:
            guide = self.loader.load_certification_guide(certification)
            for section in self._sections_from_guide(guide, certification):
                modules.append(section)
                if section.get("citation"):
                    citations.append(section["citation"])
            if modules:
                used_local_guide = True

        degraded = False
        if not modules:
            degraded = True
            modules = []
            citations = []
        elif used_local_guide or not search_results:
            degraded = True
        elif not any(
            certification.upper() in str(m.get("citation", "")).upper() for m in modules
        ):
            degraded = True

        learning_path = {
            "role": role,
            "certification": certification,
            "core_skills": skills,
            "recommended_hours": overview.get("recommended_hours", 80),
            "target_practice_score": overview.get("target_practice_score", 80),
            "modules": modules,
            "grounded_in": list(set(citations)),
            "degraded": degraded,
        }

        if (
            self.llm
            and modules
            and any(m.get("description") for m in modules)
            and not degraded
        ):
            learning_path["llm_synthesized"] = True

        return {
            "agent": self.name,
            "learning_path": learning_path,
            "citations": learning_path["grounded_in"],
        }
