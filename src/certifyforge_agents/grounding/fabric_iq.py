"""
Real Fabric IQ — Semantic Layer (Ontology + Rules Engine)

Implements a code-native version of the Fabric IQ ontology pattern from:
- Microsoft Learn: "Create an ontology with Fabric IQ", "Build an ontology from a semantic model in Fabric IQ"
- AI Skills Navigator labs: manual creation + generate from Power BI semantic model, entity types, properties (static/time-series), keys, relationship types (configure/bind), preview/graph.
- Video context (Azure Decoded): "Ground AI Apps with Fabric IQ’s Semantic Foundation" — the ontology provides the trusted, queryable business concepts + typed relationships that ground reliable agent reasoning (preventing hallucinated plans/feasibility).

Our "semantic model" analogue: Role_certification_matrix + certification guides + learner/work signals (tables + business relationships).
Entity types: Role, Certification, Skill, Learner (with properties + keys).
Relationship types: recommended_for (role↔cert), prereq_of (transitive chains), requires_skill, has_gap (derived).
Inference: feasibility, time-to-readiness, gaps, alignments — rules over the ontology + data bindings.
Used by the full multi-agent reasoning system (orchestrator plans using ontology facts, specialists + RAG generate, critic verifies with objective ontology signals, trace surfaces the facts for observability).

This keeps the separation: Fabric IQ = structured semantic ontology for grounding & inference; Foundry IQ = vector RAG + LLM for content synthesis.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

from ..data.loader import SyntheticDataLoader
from ..data.models import StudyPlan, WorkSignal, Learner


@dataclass
class CertificationRequirements:
    """Structured semantic model of what a certification requires."""
    id: str
    skills: List[str]
    recommended_hours: int
    prerequisites: List[str] = field(default_factory=list)
    target_practice_score: int = 80
    pass_threshold: float = 0.75
    difficulty_level: str = "Associate"  # Foundational / Associate / Expert


@dataclass
class RoleCertificationAlignment:
    """Semantic mapping of a role to certifications and required skills."""
    role: str
    primary_certification: str
    secondary_certifications: List[str]
    key_skills: List[str]
    relevance_score: float = 0.8  # How relevant this cert is for the role


@dataclass
class Skill:
    """Individual skill in the ontology."""
    name: str
    category: str  # e.g. "Compute", "Security", "Data", "DevOps"
    difficulty: int = 3  # 1-5


@dataclass
class SkillGap:
    """Represents a gap between current state and required skills."""
    skill: str
    current_level: float  # 0-1
    required_level: float
    priority: str  # high / medium / low


@dataclass
class EntityType:
    """Fabric IQ style Entity Type (concept in the ontology)."""
    name: str
    properties: Dict[str, str] = field(default_factory=dict)  # name -> type (e.g. 'recommended_hours': 'int')
    key: Optional[str] = None


@dataclass
class RelationshipType:
    """Fabric IQ style typed Relationship (connection between entity types, like prereq_of, recommended_for, has_gap)."""
    name: str
    from_entity: str
    to_entity: str
    cardinality: str = "many_to_one"  # or one_to_many etc.
    description: str = ""


class FabricIQ:
    """
    Real Fabric IQ implementation.

    This class provides a structured semantic layer over the raw data.
    It can answer questions like:
    - What does it mean for a Cloud Engineer to pursue AZ-204?
    - Is this study plan realistic given the learner's workload?
    - What is the expected readiness threshold for this certification?
    """

    def __init__(self, loader: Optional[SyntheticDataLoader] = None):
        self.loader = loader or SyntheticDataLoader()
        dr = getattr(self.loader, "data_root", None)
        print(f"[FabricIQ] data_root resolved to: {dr}")
        self._cert_models: Dict[str, CertificationRequirements] = {}
        self._role_alignments: Dict[str, RoleCertificationAlignment] = {}
        self._load_ontology()

    def _load_ontology(self):
        """Load and parse the semantic models from data sources.
        The Role_certification_matrix + cert definitions act as our 'semantic model'
        (exactly as in the Fabric IQ labs: generate ontology from semantic model → entity types + relationship types).
        """
        # Load role → certification alignment (our 'semantic model' source)
        matrix = self.loader.load_role_certification_matrix()["raw_content"]
        self._parse_role_matrix(matrix)

        # Load certification models from guides + hardcoded knowledge (tables → entity types)
        # In a more advanced version this would come from a richer ontology or auto-generate step
        self._cert_models = {
            "AZ-204": CertificationRequirements(
                id="AZ-204",
                skills=["App Service", "Azure Functions", "Blob Storage", "Key Vault", "Managed Identities"],
                recommended_hours=80,
                prerequisites=["AZ-900"],
                target_practice_score=80,
                pass_threshold=0.75,
            ),
            "AZ-400": CertificationRequirements(
                id="AZ-400",
                skills=["CI/CD", "Infrastructure as Code", "GitHub Actions", "Monitoring", "Security"],
                recommended_hours=100,
                prerequisites=["AZ-204", "AZ-104"],
                target_practice_score=80,
                pass_threshold=0.75,
            ),
            "DP-203": CertificationRequirements(
                id="DP-203",
                skills=["Data Factory", "Synapse", "Cosmos DB", "Data Lake", "Streaming"],
                recommended_hours=90,
                prerequisites=["DP-900", "AZ-204"],
                target_practice_score=80,
                pass_threshold=0.75,
            ),
            "DP-600": CertificationRequirements(
                id="DP-600",
                skills=["Data Lakehouse", "Spark", "Data Factory", "Synapse", "Real-time Analytics"],
                recommended_hours=90,
                prerequisites=["DP-203", "AZ-204"],
                target_practice_score=80,
                pass_threshold=0.75,
            ),
        }

        # Build the explicit Fabric-IQ-style ontology (entities + typed relationships)
        # This makes the layer a closer structural match to Fabric IQ (entity types + relationship types
        # generated from the semantic model, queryable relationships, bindings to data).
        self._build_explicit_ontology()

    def _parse_role_matrix(self, raw_content: str):
        """Very lightweight parser for the Role → Certification matrix."""
        current_role = None
        for line in raw_content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current_role = line.replace("## ", "").strip()
                continue
            if current_role and line.startswith("- **Primary Certification**"):
                primary = line.split(":", 1)[1].strip().split()[0]
                self._role_alignments[current_role] = RoleCertificationAlignment(
                    role=current_role,
                    primary_certification=primary,
                    secondary_certifications=[],
                    key_skills=[],
                )
            if current_role and line.startswith("- **Secondary Certifications**"):
                secs = [x.strip() for x in line.split(":", 1)[1].strip().split(",")]
                if current_role in self._role_alignments:
                    self._role_alignments[current_role].secondary_certifications = secs
            if current_role and line.startswith("- **Key Skills**"):
                skills = [x.strip() for x in line.split(":", 1)[1].strip().split(",")]
                if current_role in self._role_alignments:
                    self._role_alignments[current_role].key_skills = skills

    # ------------------------------------------------------------------
    # Public Semantic API (what agents query)
    # ------------------------------------------------------------------
    def get_certification_requirements(self, cert_id: str) -> CertificationRequirements:
        """Return the semantic model for a certification.
        For unknown certs (not in our primary ontology), return a generic model so the full
        pipeline (plan, critic, RAG, adjustment, trace) still runs with reasonable defaults
        + whatever the search index provides. The rich trace will note limited ontology data.
        """
        if cert_id not in self._cert_models:
            # Graceful handling for unknown certificates (e.g. PL-300, AZ-500, SC-400, new DP-xxx etc.)
            return CertificationRequirements(
                id=cert_id,
                skills=[],
                recommended_hours=80,
                prerequisites=[],
                target_practice_score=80,
                pass_threshold=0.75,
                difficulty_level="Associate",
            )
        return self._cert_models[cert_id]

    def get_role_alignment(self, role: str) -> Optional[RoleCertificationAlignment]:
        """Return the semantic mapping of a role to certifications."""
        return self._role_alignments.get(role)

    def get_recommended_hours(self, cert_id: str) -> int:
        model = self.get_certification_requirements(cert_id)
        return model.recommended_hours if model else 80

    def get_pass_threshold(self, cert_id: str) -> float:
        model = self.get_certification_requirements(cert_id)
        return model.pass_threshold if model else 0.75

    def calculate_plan_feasibility(
        self,
        plan: StudyPlan,
        work_context: Dict[str, Any],
        learner: Optional[Learner] = None,
    ) -> Dict[str, Any]:
        """
        Core Fabric IQ reasoning: Is this study plan realistic given the person's
        actual work life? Uses richer signals (skill gaps, time estimates) when
        a learner is provided.
        """
        focus_hours = work_context.get("focus_hours_per_week", 10)
        meeting_hours = work_context.get("meeting_hours_per_week", 15)

        # Simple but effective capacity model
        available_focus = max(5, focus_hours - (meeting_hours * 0.25))
        total = max(0, getattr(plan, "total_hours", 0) or 0)
        weeks_needed = max(4, total / available_focus) if available_focus > 0 else 12

        is_feasible = total <= (available_focus * 10)  # ~10 week max reasonable

        capacity_util = round(total / (available_focus * 8), 2) if (available_focus * 8) > 0 else 1.0

        # Richer adjustment using skill gaps / time-to-readiness if learner available
        gap_penalty = 0.0
        time_factor = 1.0
        if learner is not None:
            try:
                cert_id = getattr(plan, "certification", None) or getattr(learner, "certification", "")
                if cert_id:
                    gaps = self.build_skill_gap_analysis(learner, cert_id)
                    gap_penalty = min(0.35, len(gaps) * 0.08)
                    time_est = self.estimate_time_to_readiness(learner, cert_id)
                    if time_est.get("estimated_weeks"):
                        # if time est much higher than weeks_needed, lower feas
                        if time_est["estimated_weeks"] > weeks_needed * 1.5:
                            time_factor = 0.85
            except Exception:
                pass

        adjusted_util = min(2.0, capacity_util + gap_penalty)
        feasibility_score = max(0.05, round(1.0 - min(1.0, (adjusted_util - 0.5) / 1.5), 2))
        # only hard-cap low on actual infeasibility (gaps lower via adjusted_util + show in issues)
        if not is_feasible:
            feasibility_score = min(feasibility_score, 0.45)

        risk_level = "high" if not is_feasible or adjusted_util > 1.3 else "medium" if weeks_needed > 8 or gap_penalty > 0.1 else "low"

        result = {
            "is_feasible": is_feasible,
            "estimated_weeks": round(weeks_needed, 1),
            "available_focus_per_week": round(available_focus, 1),
            "capacity_utilization": capacity_util,
            "risk_level": risk_level,
            "feasibility_score": feasibility_score,
            "gap_penalty": round(gap_penalty, 2),
            "time_adjusted": time_factor < 1.0,
        }
        return result

    def get_skill_gaps(self, learner: Learner, target_cert: str) -> List[str]:
        """Identify likely skill gaps for a learner pursuing a certification."""
        cert_model = self.get_certification_requirements(target_cert)
        if not cert_model:
            return []

        # Very simplistic gap detection for now (can be made much smarter)
        # In reality this would look at learner history + certification skills
        known_skills_lower = [s.lower() for s in cert_model.skills]

        # Placeholder: return a subset as "gaps" for demo purposes
        if learner.practice_score_avg < 70:
            return [s for s in cert_model.skills if "security" in s.lower() or "monitoring" in s.lower()]
        return []

    def role_certification_alignment(self, role: str, cert: str) -> Dict[str, Any]:
        """How well does this certification align with the person's role?"""
        alignment = self.get_role_alignment(role)
        if not alignment:
            return {
                "alignment_score": 0.5,
                "is_primary": False,
                "is_secondary": False,
                "recommended": False
            }

        is_primary = (alignment.primary_certification == cert)
        is_secondary = cert in alignment.secondary_certifications

        score = 1.0 if is_primary else 0.75 if is_secondary else 0.4

        return {
            "alignment_score": score,
            "is_primary": is_primary,
            "is_secondary": is_secondary,
            "recommended": is_primary or is_secondary,
        }

    def get_available_roles(self) -> List[str]:
        """Return list of roles that have alignment data in the ontology."""
        return list(self._role_alignments.keys())

    def get_all_certification_ids(self) -> List[str]:
        """Return list of known certifications."""
        return list(self._cert_models.keys())

    # ------------------------------------------------------------------
    # Expanded Ontology & Rules (more relationships)
    # ------------------------------------------------------------------
    def get_missing_prerequisites(self, learner: Learner, target_cert: str) -> List[str]:
        """Return certifications the learner should complete before targeting this one."""
        cert = self.get_certification_requirements(target_cert)
        if not cert:
            return []

        # In a real system we'd check learner history. For now, simple heuristic.
        if learner.certification == target_cert:
            return []

        return [p for p in cert.prerequisites if p != learner.certification]

    def estimate_time_to_readiness(self, learner: Learner, target_cert: str) -> Dict[str, Any]:
        """Rough estimate using current progress + certification requirements."""
        cert = self.get_certification_requirements(target_cert)
        if not cert:
            return {"estimated_weeks": None, "confidence": 0.0}

        remaining_hours = max(0, cert.recommended_hours - learner.hours_studied)
        weekly_capacity = max(5, 20 - (learner.practice_score_avg / 10))  # rough model

        weeks = remaining_hours / weekly_capacity

        return {
            "estimated_weeks": round(weeks),
            "remaining_hours": remaining_hours,
            "confidence": 0.6,  # This would be higher with real progress data
        }

    def get_skill_prerequisites(self, skill: str) -> List[str]:
        """Simple prerequisite graph for skills (expandable)."""
        prereqs = {
            "Azure Functions": ["App Service", "Azure Storage"],
            "Key Vault": ["Managed Identities"],
            "Synapse": ["Data Lake", "Data Factory"],
            "Managed Identities": ["Azure Active Directory"],
            "Azure Kubernetes Service": ["Azure Container Instances", "Networking"],
        }
        return prereqs.get(skill, [])

    def get_full_prerequisite_chain(self, skill: str, visited: set = None) -> List[str]:
        """Recursively get all prerequisites for a skill (transitive closure)."""
        if visited is None:
            visited = set()
        if skill in visited:
            return []
        visited.add(skill)

        direct = self.get_skill_prerequisites(skill)
        full_chain = direct[:]
        for prereq in direct:
            full_chain.extend(self.get_full_prerequisite_chain(prereq, visited))
        return list(dict.fromkeys(full_chain))  # dedupe preserving order

    def build_skill_gap_analysis(self, learner: Learner, target_cert: str) -> List[SkillGap]:
        """Produce a structured list of skill gaps."""
        cert = self.get_certification_requirements(target_cert)
        if not cert:
            return []

        gaps = []
        for skill in cert.skills:
            # Very naive current level estimation
            current = min(0.9, learner.practice_score_avg / 100 + 0.1)
            required = 0.75

            if current < required:
                gaps.append(SkillGap(
                    skill=skill,
                    current_level=round(current, 2),
                    required_level=required,
                    priority="high" if current < 0.5 else "medium"
                ))
        return gaps

    # ------------------------------------------------------------------
    # Explicit Ontology Model (closer to Fabric IQ: Entity Types + Relationship Types from semantic model)
    # See AI Skills Navigator / mslearn "Create an ontology with Fabric IQ" + "Build from semantic model".
    # The Role_certification_matrix + cert models act as our "semantic model".
    # Relationships (prereq_of, recommended_for, requires_skill, has_gap) are first-class and queryable.
    # ------------------------------------------------------------------
    def _build_explicit_ontology(self):
        """Construct explicit entity types and relationship types (Fabric IQ style)."""
        self._entity_types: Dict[str, EntityType] = {}
        self._relationship_types: List[RelationshipType] = []

        # Entity types (concepts) - analogous to tables becoming entity types
        for cert_id, model in self._cert_models.items():
            self._entity_types[f"Certification:{cert_id}"] = EntityType(
                name=f"Certification:{cert_id}",
                properties={
                    "recommended_hours": "int",
                    "pass_threshold": "float",
                    "difficulty_level": "string",
                    "skills": "list[string]",
                },
                key="id",
            )

        for role in self._role_alignments.keys():
            self._entity_types[f"Role:{role}"] = EntityType(
                name=f"Role:{role}",
                properties={"primary_certification": "string", "key_skills": "list[string]"},
                key="name",
            )

        self._entity_types["Learner"] = EntityType(
            name="Learner",
            properties={"practice_score_avg": "float", "hours_studied": "int", "role": "string"},
            key="learner_id",
        )

        # Relationship types (typed connections) - generated/derived from the "semantic model" (matrix + cert defs)
        # This mirrors "model relationships become relationship types in the ontology"
        for role, align in self._role_alignments.items():
            self._relationship_types.append(RelationshipType(
                name="recommended_for",
                from_entity=f"Role:{role}",
                to_entity=f"Certification:{align.primary_certification}",
                cardinality="many_to_one",
                description="Primary recommended certification for the role (from Role-Certification matrix / semantic model)",
            ))
            for sec in align.secondary_certifications:
                self._relationship_types.append(RelationshipType(
                    name="recommended_for",
                    from_entity=f"Role:{role}",
                    to_entity=f"Certification:{sec}",
                    cardinality="many_to_one",
                    description="Secondary recommended certification",
                ))

        for cert_id, model in self._cert_models.items():
            for pr in model.prerequisites:
                self._relationship_types.append(RelationshipType(
                    name="prereq_of",
                    from_entity=f"Certification:{pr}",
                    to_entity=f"Certification:{cert_id}",
                    cardinality="many_to_one",
                    description="Must be completed before targeting this certification (transitive chains supported)",
                ))
            for sk in model.skills:
                self._relationship_types.append(RelationshipType(
                    name="requires_skill",
                    from_entity=f"Certification:{cert_id}",
                    to_entity=f"Skill:{sk}",
                    cardinality="one_to_many",
                    description="Certification requires mastery of this skill (basis for gap analysis)",
                ))

    def list_entity_types(self) -> List[str]:
        """Return the concepts in the ontology (like listing entity types in Fabric IQ canvas)."""
        return list(self._entity_types.keys()) if hasattr(self, "_entity_types") else []

    def list_relationships(self) -> List[Dict[str, Any]]:
        """Return relationship types (analogous to configured relationships in the ontology / semantic model)."""
        if not hasattr(self, "_relationship_types"):
            return []
        return [
            {
                "name": r.name,
                "from": r.from_entity,
                "to": r.to_entity,
                "cardinality": r.cardinality,
                "description": r.description,
            }
            for r in self._relationship_types
        ]

    def get_related(self, entity: str, relationship_name: str = None) -> List[str]:
        """Simple graph query over the ontology relationships (grounding for agents)."""
        if not hasattr(self, "_relationship_types"):
            return []
        results = []
        for r in self._relationship_types:
            if relationship_name and r.name != relationship_name:
                continue
            if r.from_entity == entity or r.to_entity == entity:
                other = r.to_entity if r.from_entity == entity else r.from_entity
                results.append(f"{r.name}: {other}")
        return results

