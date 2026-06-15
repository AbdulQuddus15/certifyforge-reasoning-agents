from certifyforge_agents.data.factory import SyntheticDataFactory


def test_factory_seed_reproducibility():
    a = SyntheticDataFactory(seed=42).create_learner(role="Cloud Engineer", certification="AZ-204")
    b = SyntheticDataFactory(seed=42).create_learner(role="Cloud Engineer", certification="AZ-204")
    assert a.learner_id == b.learner_id


def test_study_plan_invariants():
    factory = SyntheticDataFactory(seed=42)
    learner = factory.create_learner()
    work = factory.create_work_signal()
    plan = factory.create_study_plan(learner=learner, work_signal=work)
    assert plan.total_hours > 0
    assert len(plan.milestones) >= 1
    assert 0.0 <= plan.feasibility_score <= 1.0