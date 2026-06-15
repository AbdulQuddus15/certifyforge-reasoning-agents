"""
Orchestrator Agent — The central Planner + Router + Loop Manager.

This is the most important component in the Reasoning Agents architecture.
It does NOT do domain work itself. It decomposes requests, routes to specialists,
manages the pass/fail loop, and integrates the Critic/Verifier.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class Orchestrator(ABC):
    """
    Base interface for the top-level Orchestrator.
    
    Responsibilities (per the official architecture):
    - Decompose incoming request into an explicit plan
    - Route steps to the appropriate specialist agents
    - Manage workflow state and the pass/fail loop
    - Integrate Critic/Verifier results
    - Produce final synthesized response
    """

    @abstractmethod
    async def handle_request(
        self, 
        user_request: Dict[str, Any],
        prior_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Main entry point.
        
        Args:
            user_request: The incoming request (e.g. {"role": "...", "certification": "..."})
            prior_state: Optional previous state for multi-turn or retry scenarios
            
        Returns:
            Final response containing plan, specialist outputs, and final answer.
        """
        pass

    @abstractmethod
    async def create_plan(
        self, 
        user_request: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Break the request into an ordered, inspectable plan.
        Each step should clearly indicate which specialist handles it.
        """
        pass

    @abstractmethod
    async def route_and_execute(
        self, 
        plan_step: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute one step of the plan by routing to the correct specialist."""
        pass
