"""
Quick validation that Real Fabric IQ is working.
"""

from .grounding.fabric_iq import FabricIQ
from .data.factory import SyntheticDataFactory

def main():
    fiq = FabricIQ()
    factory = SyntheticDataFactory(seed=42)

    learner = factory.create_learner()
    work = factory.create_work_signal()
    plan = factory.create_study_plan(learner=learner, work_signal=work)

    print("=== Real Fabric IQ Test ===")
    print(f"Learner: {learner.learner_id} ({learner.role})")
    print(f"Target: {learner.certification}")

    feasibility = fiq.calculate_plan_feasibility(plan, {
        "focus_hours_per_week": work.focus_hours_per_week,
        "meeting_hours_per_week": work.meeting_hours_per_week
    })

    print(f"\nFeasibility Analysis:")
    print(f"  Is feasible: {feasibility['is_feasible']}")
    print(f"  Risk level: {feasibility['risk_level']}")
    print(f"  Estimated weeks: {feasibility.get('estimated_weeks')}")

    alignment = fiq.role_certification_alignment(learner.role, learner.certification)
    print(f"\nRole-Certification Alignment:")
    print(f"  Score: {alignment['alignment_score']}")
    print(f"  Is recommended: {alignment['recommended']}")

    cert_reqs = fiq.get_certification_requirements(learner.certification)
    if cert_reqs:
        print(f"\nCertification Requirements:")
        print(f"  Recommended hours: {cert_reqs.recommended_hours}")
        print(f"  Pass threshold: {cert_reqs.pass_threshold}")

    assert isinstance(feasibility["risk_level"], str)
    assert feasibility.get("estimated_weeks", 0) > 0
    assert alignment["alignment_score"] > 0
    print("\n✅ Real Fabric IQ is operational!")


def test_fabric_iq_smoke():
    main()


if __name__ == "__main__":
    main()
