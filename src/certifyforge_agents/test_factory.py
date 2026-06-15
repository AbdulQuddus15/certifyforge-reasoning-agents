"""
Quick test script for SyntheticDataFactory.
Run with (from src directory):
    python -m certifyforge_agents.test_factory
"""

from .data.factory import SyntheticDataFactory
from .data.models import Learner, WorkSignal

def main():
    factory = SyntheticDataFactory(seed=42)

    print("=== Testing SyntheticDataFactory ===")
    print()

    learner = factory.create_learner()
    print("Created Learner:")
    print(f"  {learner}")
    print()

    work = factory.create_work_signal()
    print("Created WorkSignal:")
    print(f"  {work}")
    print()

    cert = factory.create_certification_model("AZ-204")
    print("Created CertificationModel:")
    print(f"  {cert}")
    print()

    plan = factory.create_study_plan(learner=learner, work_signal=work)
    print("Created StudyPlan:")
    print(f"  total_hours={plan.total_hours}, feasibility={plan.feasibility_score}")
    print(f"  milestones count: {len(plan.milestones)}")
    print()

    assessment = factory.create_assessment_result(learner=learner)
    print("Created AssessmentResult:")
    print(f"  readiness_score={assessment.readiness_score}, passed={assessment.passed}")
    print(f"  questions count: {len(assessment.questions)}")
    print()

    job = factory.create_job_request()
    print("Created JobRequest:")
    print(f"  {job}")
    print()

    # Assertions for pytest / CI (legacy main() still prints for manual smoke)
    assert learner.learner_id
    assert plan.total_hours > 0
    assert len(plan.milestones) >= 1
    assert 0.0 <= assessment.readiness_score <= 1.0
    print("=== Factory test complete - all methods working ===")


def test_factory_smoke():
    main()


if __name__ == "__main__":
    main()
