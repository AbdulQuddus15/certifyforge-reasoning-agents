"""
Manager Insights Agent (light implementation)

Grounding: Work IQ + Fabric IQ
Role: Provide team-level certification readiness insights (no PII).
"""

from typing import Dict, Any, List

from ..agents.base import SpecialistAgent
from ..agents.citations import sanitize_user_text


class ManagerInsightsAgent(SpecialistAgent):

    def __init__(self):
        self._name = "ManagerInsights"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Provides team-level certification readiness insights with concrete patterns and risk areas."

    @property
    def grounding_layers(self) -> List[str]:
        return ["Work IQ", "Fabric IQ"]

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        team_id = sanitize_user_text(str(input_data.get("team_id", "TEAM-UNKNOWN")), max_length=64)

        return {
            "agent": self.name,
            "insights": {
                "team_id": team_id,
                "summary": "Mixed readiness across the team. Several members at 65-75% readiness.",
                "at_risk": ["L-1004 (low hours studied)"],
                "recommended_actions": [
                    "Prioritize hands-on labs for the next 3 weeks",
                    "Pair high performers with at-risk learners",
                ],
                "timeline": "Target 80%+ team readiness by end of Q3.",
            },
            "grounded_in": ["Work IQ + Fabric IQ (team patterns)"],
        }
