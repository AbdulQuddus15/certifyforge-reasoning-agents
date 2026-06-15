"""
Synthetic Data Factory for CertifyForge.

Provides easy generation of realistic synthetic test data for development,
testing, and evaluation. All generated data uses fabricated identifiers only.
"""

import random
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from .models import (
    Learner,
    WorkSignal,
    CertificationModel,
    StudyPlan,
    AssessmentResult,
    JobRequest,
)


class SyntheticDataFactory:
    """
    Factory for generating synthetic CertifyForge data objects.

    Useful for:
    - Unit/integration testing
    - Demo scripts
    - Evaluation harness
    - Rapid prototyping of new agents
    """

    # Common roles and certifications for realistic generation
    ROLES = ["Cloud Engineer", "DevOps Engineer", "Data Engineer", "Solutions Architect", "Security Engineer"]
    CERTIFICATIONS = ["AZ-204", "AZ-400", "DP-203", "AZ-305", "SC-300"]

    ROLE_CERT_SKILLS = {
        "Cloud Engineer": {
            "AZ-204": ["App Service", "Azure Functions", "Blob Storage", "Key Vault", "Managed Identities"],
            "AZ-305": ["Architecture", "Networking", "Identity", "Governance"],
        },
        "DevOps Engineer": {
            "AZ-400": ["CI/CD", "Infrastructure as Code", "GitHub Actions", "Monitoring", "Security"],
        },
        "Data Engineer": {
            "DP-203": ["Data Factory", "Synapse", "Cosmos DB", "Data Lake", "Streaming"],
        },
    }

    def __init__(self, seed: Optional[int] = None):
        if seed is not None and seed > 0:
            random.seed(seed)
        # If seed is None or <= 0, we leave random unseeded → truly random behavior

    # ------------------------------------------------------------------
    # Core entity factories
    # ------------------------------------------------------------------
    def create_learner(
        self,
        learner_id: Optional[str] = None,
        role: Optional[str] = None,
        certification: Optional[str] = None,
        practice_score_avg: Optional[float] = None,
        hours_studied: Optional[int] = None,
        exam_outcome: Optional[str] = None,
    ) -> Learner:
        role = role or random.choice(self.ROLES)
        cert = certification or self._get_primary_cert_for_role(role)

        return Learner(
            learner_id=learner_id or self._generate_learner_id(),
            role=role,
            certification=cert,
            practice_score_avg=practice_score_avg if practice_score_avg is not None else round(random.uniform(55, 92), 1),
            hours_studied=hours_studied if hours_studied is not None else random.randint(8, 45),
            exam_outcome=exam_outcome or random.choice(["Pass", "Fail", None]),
        )

    def create_work_signal(
        self,
        employee_id: Optional[str] = None,
    ) -> WorkSignal:
        meeting_hours = random.randint(8, 28)
        focus_hours = max(6, 35 - meeting_hours)

        return WorkSignal(
            employee_id=employee_id or self._generate_employee_id(),
            meeting_hours_per_week=meeting_hours,
            focus_hours_per_week=focus_hours,
            preferred_learning_slot=random.choice(["Morning", "Afternoon", "Evening"]),
            collaboration_load=random.choice(["low", "medium", "high"]),
        )

    def create_certification_model(self, cert_id: Optional[str] = None) -> CertificationModel:
        cert_id = cert_id or random.choice(self.CERTIFICATIONS)
        skills = self._get_skills_for_cert(cert_id)

        return CertificationModel(
            id=cert_id,
            skills=skills,
            recommended_hours=random.randint(60, 140),
            prerequisites=self._get_prerequisites(cert_id),
        )

    def create_study_plan(
        self,
        learner: Optional[Learner] = None,
        work_signal: Optional[WorkSignal] = None,
        total_hours: Optional[int] = None,
    ) -> StudyPlan:
        learner = learner or self.create_learner()
        work = work_signal or self.create_work_signal(role=learner.role)

        if total_hours is None:
            # Make it deliberately challenging sometimes
            base = random.randint(35, 95)
            if random.random() < 0.3:
                base += 25  # over-ambitious plan

        milestones = self._generate_milestones(learner.certification, total_hours or base)

        return StudyPlan(
            learner_id=learner.learner_id,
            certification=learner.certification,
            milestones=milestones,
            total_hours=total_hours or base,
            feasibility_score=round(random.uniform(0.55, 0.98), 2),
        )

    def create_assessment_result(
        self,
        learner: Optional[Learner] = None,
        readiness_score: Optional[float] = None,
    ) -> AssessmentResult:
        learner = learner or self.create_learner()
        score = readiness_score if readiness_score is not None else round(random.uniform(0.48, 0.94), 2)

        questions = [
            {
                "id": f"Q{i}",
                "question": f"Sample {learner.certification} question {i} about {random.choice(['compute', 'storage', 'security', 'networking'])}.",
                "citation": f"{learner.certification} Guide v3.2 - Section {random.randint(1,5)}.{i}",
            }
            for i in range(1, 6)
        ]

        return AssessmentResult(
            learner_id=learner.learner_id,
            certification=learner.certification,
            questions=questions,
            readiness_score=score,
            passed=score >= 0.75,
            feedback="Strong in compute and storage. Needs improvement on security best practices." if score < 0.8 else "Well prepared across all domains.",
            grounded_in=[q["citation"] for q in questions],
        )

    # ------------------------------------------------------------------
    # Job Request helper
    # ------------------------------------------------------------------
    def create_job_request(
        self,
        role: Optional[str] = None,
        certification: Optional[str] = None,
    ) -> JobRequest:
        role = role or random.choice(self.ROLES)
        cert = certification or self._get_primary_cert_for_role(role)

        return JobRequest(
            role=role,
            certification=cert,
            learner_id=self._generate_learner_id(),
            team_id=f"TEAM-{random.randint(100, 999)}",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _generate_learner_id(self) -> str:
        return f"L-{random.randint(1000, 9999)}"

    def _generate_employee_id(self) -> str:
        return f"EMP-{random.randint(100, 999)}"

    def _get_primary_cert_for_role(self, role: str) -> str:
        mapping = {
            "Cloud Engineer": "AZ-204",
            "DevOps Engineer": "AZ-400",
            "Data Engineer": "DP-203",
            "Solutions Architect": "AZ-305",
            "Security Engineer": "SC-300",
        }
        return mapping.get(role, "AZ-204")

    def _get_skills_for_cert(self, cert_id: str) -> List[str]:
        for role_skills in self.ROLE_CERT_SKILLS.values():
            if cert_id in role_skills:
                return role_skills[cert_id]
        return ["Core Azure Services", "Security", "Monitoring", "DevOps"]

    def _get_prerequisites(self, cert_id: str) -> List[str]:
        prereqs = {
            "AZ-204": ["AZ-900"],
            "AZ-400": ["AZ-204", "AZ-104"],
            "DP-203": ["DP-900", "AZ-204"],
            "AZ-305": ["AZ-104", "AZ-204"],
        }
        return prereqs.get(cert_id, [])

    def _generate_milestones(self, certification: str, total_hours: int) -> List[Dict[str, Any]]:
        num_milestones = random.randint(4, 7)
        base_hours = total_hours // num_milestones

        milestones = []
        for i in range(num_milestones):
            milestones.append({
                "week": i + 1,
                "topic": f"{certification} Topic {i+1}",
                "hours": base_hours + random.randint(-3, 5),
                "focus_area": random.choice(["Hands-on labs", "Theory + docs", "Practice exams", "Project work"]),
            })
        return milestones
