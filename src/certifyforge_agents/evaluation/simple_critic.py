"""
Simple / Rule-based CriticVerifier implementation.

This is a starting point for the verification layer described in the architecture.
It performs basic feasibility and grounding checks.

In later phases this can be upgraded to use an LLM-as-Judge or more sophisticated rules.
"""

import logging
from typing import Dict, Any, Optional

from .critic import CriticVerifier
from ..data.models import StudyPlan, AssessmentResult, Learner
from ..grounding.fabric_iq import FabricIQ
from ..data.factory import SyntheticDataFactory


class SimpleCriticVerifier(CriticVerifier):
    """
    Basic rule-based critic that can optionally use a real FabricIQ instance
    for more accurate semantic validation.
    """

    def __init__(self, fabric_iq: FabricIQ = None):
        self.fabric_iq = fabric_iq or FabricIQ()
        self.logger = logging.getLogger(__name__)

    async def verify_study_plan(self, plan: StudyPlan, work_context: Dict[str, Any], learner: Optional[Learner] = None) -> Dict[str, Any]:
        # Prefer the real Fabric IQ semantic model when available (now richer)
        if self.fabric_iq:
            base = self.fabric_iq.calculate_plan_feasibility(plan, work_context, learner=learner)
            # Enrich for consistent Critic return shape (confidence, issues, suggestions, accepted)
            util = base.get("capacity_utilization", 0.6)
            gap_pen = base.get("gap_penalty", 0.0)
            feas = base.get("is_feasible", True)
            confidence = 0.92 if feas and util < 1.1 and gap_pen < 0.15 else (0.65 if feas else 0.35)
            issues = []
            suggestions = []
            if util > 1.15:
                issues.append(f"Capacity utilization high ({util}). Risk of burnout or slippage.")
                suggestions.append("Spread over more weeks or reduce milestone density.")
            if gap_pen > 0.15:
                issues.append(f"Significant skill gaps detected (penalty={gap_pen}). Plan may under-estimate effort.")
                suggestions.append("Add prerequisite modules or increase hands-on practice allocation.")
            if not feas:
                issues.append("Plan exceeds reasonable capacity limits given work signals.")
                suggestions.append("Lower total hours or obtain manager approval for focus time.")

            return {
                **base,
                "is_feasible": feas,
                "confidence": round(confidence, 2),
                "issues": issues,
                "suggestions": suggestions,
                "accepted": feas and gap_pen < 0.2,
                "needs_replan": gap_pen >= 0.2,
            }

        # Fallback to simple rule-based logic
        issues = []
        suggestions = []

        focus_hours = work_context.get("focus_hours_per_week", 10)
        max_reasonable_hours = int(focus_hours * 1.5)
        total = getattr(plan, "total_hours", 0)

        if total > max_reasonable_hours:
            issues.append(
                f"Study plan requires {total} hours, but learner only has ~{focus_hours} focus hours/week. "
                f"Maximum reasonable load ≈ {max_reasonable_hours}h."
            )
            suggestions.append("Reduce weekly milestones or extend timeline.")

        is_feasible = len(issues) == 0
        confidence = 0.85 if is_feasible else 0.4

        return {
            "is_feasible": is_feasible,
            "confidence": confidence,
            "issues": issues,
            "suggestions": suggestions,
            "accepted": is_feasible,
        }

    async def verify_assessment(self, result: AssessmentResult) -> Dict[str, Any]:
        issues = []

        if not (0.0 <= result.readiness_score <= 1.0):
            issues.append(f"Readiness score {result.readiness_score} is outside valid range [0, 1].")

        # Check that questions have citations
        for q in result.questions:
            if not q.get("citation"):
                issues.append("One or more assessment questions are missing citations.")

        # Use Fabric IQ semantic thresholds when available
        cert_reqs = self.fabric_iq.get_certification_requirements(result.certification)
        if cert_reqs:
            threshold = cert_reqs.pass_threshold
            if result.readiness_score < threshold and result.passed:
                issues.append(
                    f"Readiness score {result.readiness_score} is below the semantic pass threshold "
                    f"({threshold}) for {result.certification}, but marked as passed."
                )
            if result.readiness_score >= threshold and not result.passed:
                issues.append(
                    f"Readiness score {result.readiness_score} meets the threshold for {result.certification}, "
                    f"but was marked as failed."
                )

        is_valid = len(issues) == 0
        confidence = 0.9 if is_valid else 0.5

        return {
            "is_valid": is_valid,
            "confidence": confidence,
            "issues": issues,
        }

    async def should_retry(self, verification_result: Dict[str, Any]) -> bool:
        """Simple policy: retry if confidence is low or there are blocking issues."""
        confidence = verification_result.get("confidence", 0.0)
        issues = verification_result.get("issues", [])

        if confidence < 0.5:
            return True
        if issues:
            return True
        return False
