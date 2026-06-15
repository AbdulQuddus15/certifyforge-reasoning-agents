"""
Base grounding abstractions for the three Microsoft IQ layers.

This separation is a core principle from the Reasoning Agents architecture document.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class GroundingLayer(ABC):
    """Base class for all grounding layers."""

    @abstractmethod
    def name(self) -> str:
        """Human-readable name of this grounding layer."""
        pass

    @abstractmethod
    async def query(self, query: str, **kwargs) -> Any:
        """Execute a query against this grounding layer."""
        pass


class FoundryIQ(GroundingLayer):
    """
    Foundry IQ — Knowledge grounding (RAG + citations from approved sources).
    
    Used by: Learning Path Curator, Assessment Agent
    Must always return cited content. Never free-text invention.
    """

    def name(self) -> str:
        return "Foundry IQ (Knowledge Grounding)"

    @abstractmethod
    async def retrieve_with_citations(
        self, 
        query: str, 
        top_k: int = 5,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant chunks with source citations.
        
        Returns list of dicts containing at minimum:
        - content: str
        - citation: str (source identifier)
        - score: float (optional)
        """
        pass


class FabricIQ(GroundingLayer):
    """
    Fabric IQ — Semantic meaning and relationships (ontology).
    
    Used by: Study Plan Generator, Assessment Agent (thresholds), Manager Insights.
    Models entities like Learner, Role, Certification, Skill, ReadinessScore, etc.
    """

    def name(self) -> str:
        return "Fabric IQ (Semantic Layer)"

    @abstractmethod
    async def get_semantic_context(
        self, 
        entity_type: str, 
        identifiers: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Return structured semantic information for given entities.
        
        Example: get_semantic_context("Certification", {"id": "AZ-204"})
        """
        pass


class WorkIQ(GroundingLayer):
    """
    Work IQ — Real work context signals (meetings, focus time, collaboration load).
    
    Used by: Engagement Agent, Manager Insights Agent.
    Drives realistic, capacity-aware behavior instead of one-size-fits-all.
    """

    def name(self) -> str:
        return "Work IQ (Work Context)"

    @abstractmethod
    async def get_work_context(self, employee_id: str) -> Dict[str, Any]:
        """
        Return work context signals for a specific person.
        
        Expected fields include: meeting_hours_per_week, focus_hours_per_week,
        preferred_learning_slot, collaboration_load, etc.
        """
        pass
