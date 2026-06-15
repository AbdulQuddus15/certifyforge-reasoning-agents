"""
Engagement Agent (light implementation)

Grounding: Work IQ
Role: Suggest adaptive study timing and reminders based on the learner's actual work schedule.
"""

from typing import Dict, Any, List

from ..agents.base import SpecialistAgent


class EngagementAgent(SpecialistAgent):

    def __init__(self):
        self._name = "EngagementAgent"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return "Suggests best study times and reminders based on the learner's work schedule and focus windows."

    @property
    def grounding_layers(self) -> List[str]:
        return ["Work IQ"]

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        work = input_data.get("work_signals", {})
        focus = work.get("focus_hours_per_week", 10)
        slot = work.get("preferred_learning_slot", "Morning")

        return {
            "agent": self.name,
            "recommendations": {
                "best_slots": [slot],
                "weekly_reminders": f"Block {focus} focused hours in {slot.lower()}s",
                "escalation": "Gentle nudges if 2+ weeks of low activity",
            },
            "grounded_in": ["Work IQ signals"],
        }
