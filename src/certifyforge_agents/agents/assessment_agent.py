"""
Assessment Agent

Grounding: Foundry IQ (RAG citations) + optional real Foundry LLM (via Azure AI Project) for question synthesis + Fabric IQ (scoring).
Role: Generate grounded, cited questions (LLM-synthesized when available) and evaluate readiness.
"""

from typing import Dict, Any, List

from ..agents.base import SpecialistAgent
from ..agents.citations import match_citation, sanitize_user_text
from ..data.loader import SyntheticDataLoader
from ..grounding.base import FoundryIQ
from ..grounding.fabric_iq import FabricIQ
from ..grounding.foundry_iq import LocalFoundryIQ


class AssessmentAgent(SpecialistAgent):
    """
    Generates grounded practice questions and produces a readiness score.
    """

    def __init__(self, grounding: FoundryIQ = None, llm=None):
        self.grounding = grounding or LocalFoundryIQ()
        self.llm = llm
        self.loader = SyntheticDataLoader()
        self._name = "AssessmentAgent"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Generates grounded, cited practice questions and evaluates readiness against known criteria."

    @property
    def grounding_layers(self) -> List[str]:
        return ["Foundry IQ", "Fabric IQ"]

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        certification = sanitize_user_text(str(input_data.get("certification", "AZ-204")), max_length=32)
        topic = sanitize_user_text(str(input_data.get("topic", f"{certification} readiness")), max_length=120)
        fabric = FabricIQ()
        critic_fb = input_data.get("_critic_feedback", {}) or {}

        search_results = await self.grounding.retrieve_with_citations(
            f"practice questions and key concepts for {certification}",
            top_k=6,
            certification=certification,
        )

        questions = []
        used_llm_path = False

        if self.llm and search_results:
            try:
                allowed_citations = [item.get("citation", "") for item in search_results if item.get("citation")]
                if allowed_citations:
                    grounded_context = "\n\n".join(
                        f"[{i+1}] (Citation: {item.get('citation', '')})\n{item.get('content', '')[:600]}"
                        for i, item in enumerate(search_results[:4])
                    )
                    system = (
                        "You are an expert Azure certification exam question writer. "
                        "Generate 4-5 high-quality practice questions strictly based on the provided grounded study content. "
                        "Each question must reference concepts from the content. "
                        "For the 'citation' field you MUST use one of the EXACT citation strings from the Allowed Citations list. "
                        "Return ONLY a JSON array of objects with keys: question (string), citation (exact from allowed list), difficulty (Easy|Medium|Hard). "
                        "No explanations or extra text."
                    )
                    user = (
                        f"Certification (data): <<{certification}>>\n\n"
                        f"Allowed Citations (use EXACTLY):\n" + "\n".join(f"- {c}" for c in allowed_citations) +
                        f"\n\nGrounded content with citations:\n{grounded_context}\n\nProduce the questions now as JSON array."
                    )
                    parsed = self.llm.generate_structured(system, user, temperature=0.4, max_tokens=900)
                    items = parsed if isinstance(parsed, list) else parsed.get("questions", parsed.get("items", [])) if isinstance(parsed, dict) else []
                    for idx, q in enumerate(items[:5], 1):
                        cit = q.get("citation", "")
                        if cit not in allowed_citations:
                            match = match_citation(cit, allowed_citations)
                            if match:
                                cit = match
                            else:
                                continue
                        questions.append({
                            "id": f"Q{idx}",
                            "question": str(q.get("question", "Key concept?")),
                            "citation": cit,
                            "difficulty": str(q.get("difficulty", "Medium")),
                        })
                    if questions:
                        used_llm_path = True
            except Exception as ex:
                print(f"[AssessmentAgent] LLM question gen failed, falling back: {ex}")

        if not questions:
            for i, item in enumerate(search_results[:5], 1):
                cit = item.get("citation", "")
                if not cit:
                    continue
                topic = str((item.get("metadata") or {}).get("title") or cit).strip()
                questions.append({
                    "id": f"Q{i}",
                    "question": (
                        f"For {certification}, explain a key concept from '{topic}' "
                        "and how it applies to exam objectives."
                    ),
                    "citation": cit,
                    "difficulty": "Medium",
                })

        degraded = False
        if not questions:
            degraded = True

        if critic_fb and not critic_fb.get("accepted", True) and questions:
            questions = questions[: max(2, len(questions) - 1)]

        difficulty_weights = {"Easy": 0.05, "Medium": 0.08, "Hard": 0.12}
        base_score = 0.45 if questions else 0.0
        for q in questions:
            base_score += difficulty_weights.get(str(q.get("difficulty", "Medium")), 0.08)
        pass_threshold = fabric.get_pass_threshold(certification)
        readiness_score = round(min(0.95, base_score), 2) if questions else 0.0
        passed = readiness_score >= pass_threshold if questions else False

        feedback = (
            "Assessment degraded: no grounded content available. Configure Azure AI Search or populate the index."
            if degraded
            else ("Good foundational knowledge. Focus on hands-on labs for higher score." if not passed else "Strong across domains. Ready for exam with final review.")
        )

        result = {
            "agent": self.name,
            "assessment": {
                "certification": certification,
                "questions": questions,
                "readiness_score": readiness_score,
                "passed": passed,
                "feedback": feedback,
                "degraded": degraded,
            },
            "grounded_in": [q["citation"] for q in questions],
        }
        if used_llm_path:
            result["llm_synthesized"] = True
        return result