"""
Critic / Verifier — Cross-cutting validation layer.

Per the Reasoning Agents architecture, this component validates:
- Study plan feasibility (does it fit the learner's actual capacity?)
- Assessment quality (are questions grounded? Is the scoring threshold applied correctly?)

It can trigger self-reflection/iteration when confidence is low.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any

from ..data.models import StudyPlan, AssessmentResult


class CriticVerifier(ABC):
    """
    Validates outputs from specialists before they are accepted by the Orchestrator.
    """

    @abstractmethod
    async def verify_study_plan(self, plan: StudyPlan, work_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if the study plan is realistic given the learner's work signals.
        
        Returns something like:
        {
            "is_feasible": bool,
            "confidence": float,
            "issues": [...],
            "suggestions": [...]
        }
        """
        pass

    @abstractmethod
    async def verify_assessment(self, result: AssessmentResult) -> Dict[str, Any]:
        """
        Validate that assessment questions are properly grounded and the readiness
        score was calculated correctly against known thresholds.
        """
        pass

    @abstractmethod
    async def should_retry(self, verification_result: Dict[str, Any]) -> bool:
        """Decide whether the Orchestrator should route back for another cycle."""
        pass
