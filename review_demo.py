r"""
REVIEW + DEMO: CertifyForge Reasoning Agents (Current State)

This is a standalone script to review the architecture we have built
following the official Reasoning Agents Multi-Agent Architecture plan.

Run with:
    cd C:\Users\abdul\CREATIVE_APP_02
    python review_demo.py
"""

import sys
from pathlib import Path

# Add the agents folder directly so we can import the modules
agents_dir = Path(__file__).parent / "src" / "certifyforge_agents"
sys.path.insert(0, str(agents_dir))

from data.models import JobRequest, Learner, WorkSignal
from data.factory import SyntheticDataFactory
from data.loader import SyntheticDataLoader
from orchestrator.simple_orchestrator import SimpleOrchestrator
from evaluation.simple_critic import SimpleCriticVerifier
from agents.learning_path_curator import LearningPathCurator
from agents.study_plan_generator import StudyPlanGenerator


def main():
    print("=" * 70)
    print("CERTIFYFORGE REASONING AGENTS - CURRENT STATE REVIEW")
    print("=" * 70)
    print()

    # 1. Data Layer
    print("1. DATA LAYER")
    print("-" * 40)
    factory = SyntheticDataFactory(seed=123)
    loader = SyntheticDataLoader()

    learner = factory.create_learner()
    work = factory.create_work_signal()

    print(f"   SyntheticDataFactory can create:")
    print(f"     - Learners, WorkSignals, CertificationModels, StudyPlans, etc.")
    print(f"   Example Learner: {learner.learner_id} | {learner.role} → {learner.certification}")
    print(f"   Example WorkSignal: {work.employee_id} | {work.meeting_hours_per_week} meeting hrs, {work.focus_hours_per_week} focus hrs")
    print()

    # 2. Grounding
    print("2. GROUNDING LAYERS")
    print("-" * 40)
    print("   - LocalFoundryIQ (stub, ready to connect to real Azure AI Search)")
    print("   - FabricIQ and WorkIQ abstractions defined (to be implemented)")
    print()

    # 3. Agents
    print("3. SPECIALIST AGENTS (Implemented)")
    print("-" * 40)
    curator = LearningPathCurator()
    study_plan = StudyPlanGenerator()

    print(f"   - {curator.name}")
    print(f"   - {study_plan.name}")
    print("   (Assessment, Engagement, and ManagerInsights also implemented)")
    print()

    # 4. Orchestrator + Critic Loop
    print("4. ORCHESTRATOR + CRITIC / VERIFIER")
    print("-" * 40)
    critic = SimpleCriticVerifier()
    orchestrator = SimpleOrchestrator(critic=critic)

    request = {
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "work_signals": {
            "meeting_hours_per_week": 22,
            "focus_hours_per_week": 10,
            "preferred_learning_slot": "Morning"
        }
    }

    print("   Running Orchestrator with Critic loop...\n")
    import asyncio
    result = asyncio.run(orchestrator.handle_request(request))

    print(f"   Status: {result['status']}")
    print(f"   Iterations: {result['iterations']}")
    print(f"   Plan steps: {len(result['plan'])}")
    print()

    for step, data in result["results"].items():
        ver = data.get("verification", {})
        accepted = ver.get("accepted", "N/A")
        print(f"   - {step}: status={data.get('status')}, critic_accepted={accepted}")

    print()
    print("=" * 70)
    print("CURRENT STRENGTHS")
    print("=" * 70)
    print("• Clean separation of concerns (models, grounding, agents, orchestrator, critic)")
    print("• Real Orchestrator with Planner + explicit Critic/Verifier loop")
    print("• Multiple real specialist agents (not just stubs)")
    print("• Self-contained synthetic data + factory")
    print("• Follows the official Reasoning Agents architecture document")
    print()
    print("NEXT MAJOR STEP (as discussed): Real Fabric IQ implementation")
    print("=" * 70)


if __name__ == "__main__":
    main()
