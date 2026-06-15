# Data Layer

This package is responsible for all synthetic data used by the CertifyForge agents.

## Principles (from the Architecture Document)

- All data is **synthetic** (L-1001, EMP-001, TEAM-A style identifiers).
- No real PII is ever used.
- Data models are strongly typed using dataclasses (see `models.py`).
- Loading logic is centralized here (see `loader.py`) instead of being scattered across agent files (as was done in the previous project).

## Current Contents

- `models.py` — Core domain entities (Learner, WorkSignal, StudyPlan, AssessmentResult, etc.)
- `loader.py` — Expanded centralized loader with methods for:
  - `load_learners()` / `load_work_signals()`
  - `load_certification_guide(cert_id)`
  - `load_role_certification_matrix()`
  - `get_skills_for_role_and_cert(role, cert)`
  - `get_certification_overview(cert_id)`
  - `load_team_performance_patterns()`
  - `get_all_certification_guides()`

## Next Steps (Priority B continuation)

- Create a **data factory** for generating synthetic test cases on the fly.
- Add richer structured parsing for certification guides (instead of raw markdown).
- Support both file-based and in-memory datasets.
- Possibly move/copy key datasets into this repo for self-containment.
