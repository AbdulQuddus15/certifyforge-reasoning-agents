from certifyforge_agents.grounding.fabric_iq import FabricIQ
from certifyforge_agents.data.factory import SyntheticDataFactory


def test_fabric_iq_feasibility_for_standard_plan():
    fiq = FabricIQ()
    factory = SyntheticDataFactory(seed=42)
    learner = factory.create_learner(role="Cloud Engineer", certification="AZ-204")
    work = factory.create_work_signal()
    plan = factory.create_study_plan(learner=learner, work_signal=work)

    feasibility = fiq.calculate_plan_feasibility(plan, {
        "focus_hours_per_week": work.focus_hours_per_week,
        "meeting_hours_per_week": work.meeting_hours_per_week,
    })
    assert isinstance(feasibility["risk_level"], str)
    assert feasibility.get("estimated_weeks", 0) > 0


def test_role_cert_alignment_az204_cloud_engineer():
    fiq = FabricIQ()
    alignment = fiq.role_certification_alignment("Cloud Engineer", "AZ-204")
    assert alignment["alignment_score"] > 0


def test_az204_pass_threshold():
    fiq = FabricIQ()
    reqs = fiq.get_certification_requirements("AZ-204")
    assert reqs is not None
    assert reqs.pass_threshold == 0.75
    assert reqs.recommended_hours >= 60