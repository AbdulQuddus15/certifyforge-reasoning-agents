"""
Clean synthetic data models for the CertifyForge Reasoning Agents system.

All identifiers are fabricated (L-XXXX, EMP-XXXX, TEAM-XXXX). No PII.
This follows the data model guidance from the Reasoning Agents architecture document.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime


@dataclass
class Learner:
    learner_id: str                    # e.g. "L-1001"
    role: str                          # e.g. "Cloud Engineer"
    certification: str                 # e.g. "AZ-204"
    practice_score_avg: float = 0.0
    hours_studied: int = 0
    exam_outcome: Optional[str] = None  # "pass", "fail", or None


@dataclass
class WorkSignal:
    employee_id: str
    meeting_hours_per_week: int
    focus_hours_per_week: int
    preferred_learning_slot: str       # "Morning", "Afternoon", "Evening"
    collaboration_load: str = "medium" # low / medium / high


@dataclass
class CertificationModel:
    id: str
    skills: List[str]
    recommended_hours: int
    prerequisites: List[str] = field(default_factory=list)


@dataclass
class StudyPlan:
    learner_id: str
    certification: str
    milestones: List[Dict[str, Any]]
    total_hours: int
    feasibility_score: float           # 0.0 – 1.0 (validated by Critic)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class AssessmentResult:
    learner_id: str
    certification: str
    questions: List[Dict[str, Any]]    # Must contain citations
    readiness_score: float
    passed: bool
    feedback: str
    grounded_in: List[str]             # Source citations


@dataclass
class ManagerInsight:
    team_id: str
    period: str
    summary: str
    at_risk_learners: List[str]
    capacity_constraints: List[str]
    recommended_actions: List[str]
    generated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class JobRequest:
    """Input payload for a certification assistance job."""
    role: str
    certification: str
    learner_id: Optional[str] = None
    team_id: Optional[str] = None
    additional_context: Dict[str, Any] = field(default_factory=dict)
