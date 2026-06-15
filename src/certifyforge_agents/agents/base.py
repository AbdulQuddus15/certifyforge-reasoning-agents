"""
Base class for all specialist agents.

Every specialist must have a single, clearly defined responsibility.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class SpecialistAgent(ABC):
    """
    Base class for domain-specific agents (Learning Path Curator, 
    Study Plan Generator, Engagement, Assessment, Manager Insights).
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Short, unique name for this specialist (used by Orchestrator for routing)."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """One-sentence description of what this agent does."""
        pass

    @abstractmethod
    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute this agent's core responsibility.
        
        Must return a structured result (never just print).
        Should declare which grounding layer(s) it used.
        """
        pass

    @property
    def grounding_layers(self) -> list[str]:
        """Which of the three IQ layers this agent primarily uses (for observability)."""
        return []
