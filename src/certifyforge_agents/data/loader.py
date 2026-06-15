"""
Synthetic data loaders for CertifyForge.

This replaces the scattered file loading from the old project with a clean,
centralized interface.
"""

import json
import os
from typing import Dict, Any, List, Optional


class SyntheticDataLoader:
    """
    Loads synthetic datasets used by the CertifyForge agents.
    All data uses fabricated identifiers only (L-XXXX, EMP-XXXX, etc.).
    """

    def __init__(self, data_root: Optional[str] = None):
        if data_root is None:
            base = os.path.dirname(__file__)

            # Container + package first (build context for azure.ai.agent is the certifyforge_agents/ dir;
            # we COPY the data/ subdir so it is always co-located with loader.py inside the image).
            # base here points at the data/ dir containing certification_guides/ + learners.json etc.
            pkg_data = base
            if os.path.isdir(os.path.join(pkg_data, "certification_guides")) or os.path.exists(os.path.join(pkg_data, "learners.json")):
                self.data_root = pkg_data
            else:
                # Dev / outer layout: src/data (sibling to src/certifyforge_agents/)
                # From .../certifyforge_agents/data/loader.py  up to src/ then sibling data/
                outer_data = os.path.abspath(os.path.join(base, "..", "..", "data"))
                if os.path.isdir(outer_data) and (os.path.isdir(os.path.join(outer_data, "certification_guides")) or os.path.exists(os.path.join(outer_data, "learners.json"))):
                    self.data_root = outer_data
                else:
                    # last resort (will surface clear FileNotFound on first load_*)
                    self.data_root = pkg_data
        else:
            self.data_root = data_root

    # ------------------------------------------------------------------
    # Core learner & work context data
    # ------------------------------------------------------------------
    def load_learners(self) -> List[Dict[str, Any]]:
        path = os.path.join(self.data_root, "learners.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def load_work_signals(self) -> List[Dict[str, Any]]:
        path = os.path.join(self.data_root, "work_signals.json")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_first_learner(self) -> Dict[str, Any]:
        return self.load_learners()[0]

    def get_first_work_signal(self) -> Dict[str, Any]:
        return self.load_work_signals()[0]

    # ------------------------------------------------------------------
    # Certification & skills data (Foundry IQ + Fabric IQ)
    # ------------------------------------------------------------------
    def load_certification_guide(self, cert_id: str) -> str:
        """
        Load the full markdown guide for a certification (e.g. 'AZ-204').
        Returns the raw markdown content.
        """
        filename = f"{cert_id}_Guide.md"
        path = os.path.join(self.data_root, "certification_guides", filename)
        if not os.path.exists(path):
            return (
                f"# {cert_id}: Study Guide (Synthetic placeholder)\n\n"
                f"No local guide file found for {cert_id}. "
                "Populate the search index or add certification_guides/{cert}_Guide.md.\n"
            )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def load_role_certification_matrix(self) -> Dict[str, Any]:
        """
        Load the mapping of roles to recommended certifications and skills.
        """
        path = os.path.join(self.data_root, "certification_guides", "Role_certification_matrix")
        with open(path, "r", encoding="utf-8") as f:
            return {"raw_content": f.read()}

    def get_skills_for_role_and_cert(self, role: str, cert: str) -> List[str]:
        """
        Convenience method: returns a list of key skills for a given role + certification.
        Currently parses the Role_certification_matrix file heuristically.
        """
        matrix = self.load_role_certification_matrix()["raw_content"]
        # Very simple parsing for now — can be improved later
        lines = matrix.splitlines()
        skills = []
        capture = False
        for line in lines:
            if role.lower() in line.lower():
                capture = True
                continue
            if capture:
                if line.strip().startswith("##") or not line.strip():
                    break
                if line.strip().startswith("- **Key Skills**"):
                    skills = [s.strip() for s in line.split(":", 1)[1].split(",")]
                    break
        return skills or ["Cloud fundamentals", "Azure services", "Security", "DevOps"]

    # ------------------------------------------------------------------
    # Team / organizational patterns (Work IQ + Fabric IQ)
    # ------------------------------------------------------------------
    def load_team_performance_patterns(self) -> List[Dict[str, Any]]:
        """
        Load patterns around team performance and certification outcomes.
        """
        path = os.path.join(self.data_root, "certification_guides", "Team_Performance_Patterns")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return [{"raw_content": f.read()}]
        return []

    def get_all_certification_guides(self) -> Dict[str, str]:
        """Return a dict of cert_id -> guide content for all available guides."""
        guides_dir = os.path.join(self.data_root, "certification_guides")
        guides = {}
        if os.path.isdir(guides_dir):
            for filename in os.listdir(guides_dir):
                if filename.endswith("_Guide.md"):
                    cert_id = filename.replace("_Guide.md", "")
                    with open(os.path.join(guides_dir, filename), "r", encoding="utf-8") as f:
                        guides[cert_id] = f.read()
        return guides

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------
    def get_certification_overview(self, cert_id: str) -> Dict[str, Any]:
        """Quick structured summary from the guide (very lightweight parsing)."""
        guide = self.load_certification_guide(cert_id)
        overview = {
            "certification": cert_id,
            "recommended_hours": 80,
            "target_practice_score": 80,
        }
        for line in guide.splitlines():
            if "Recommended Study Hours" in line:
                try:
                    overview["recommended_hours"] = int(line.split(":")[1].split("-")[0].strip())
                except Exception:
                    pass
            if "Target Practice Score" in line:
                try:
                    overview["target_practice_score"] = int(line.split(":")[1].replace("%", "").strip())
                except Exception:
                    pass
        return overview
