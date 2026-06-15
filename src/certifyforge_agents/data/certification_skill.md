---
name: certification-domain
description: >
  Core domain knowledge and conventions for the CertifyForge multi-agent system.
  Used by specialists and orchestrator for consistent, high-quality personalized
  certification study planning. Load this skill to avoid re-deriving context.
version: "1.0"
tags: [certification, azure, fabric-iq, study-plan]
---

# Certification Domain Skill (CertifyForge)

## Purpose
Provide shared instructions, conventions, and rules for generating faithful, 
capacity-aware, personalized study plans for Azure certifications (AZ-204, AZ-400, 
DP-203, etc.). This skill embodies "Fabric IQ" semantic ontology + best practices 
so every agent run starts with the same high-quality context instead of guessing.

## Core Principles
- **Faithful citations only**: All recommendations must be grounded in retrieved 
  content from Azure AI Search (RAG) or the bundled certification guides and 
  Role_certification_matrix. Never hallucinate sources or steps. Use 
  `_match_citation` or equivalent validation.
- **Capacity-aware (Fabric IQ)**: Always consult work_signals (meeting_hours, 
  focus_hours, preferred slot) and learner data. Produce realistic total_hours, 
  weekly milestones, and feasibility scores. Factor gaps, prereqs, and risk.
- **Maker + Checker separation**: Generation specialists (e.g. StudyPlanGenerator) 
  propose; the Critic/Verifier (and any sub-verifier) checks with objective gates 
  (feasibility > threshold, prerequisites met, test-like validation where possible). 
  The writer does not grade its own homework.
- **Adjustment mutates the plan**: LLM personalization (from critic signals or 
  direct) must result in concrete changes to milestones (e.g. append 
  "Hands-on reinforcement: ...") and total_hours, not just annotations.
- **Observable & reviewable**: Every run must produce rich logs ([1] grounding/LLM, 
  [3] Fabric details/gaps, [4] orch iterations, [5] critic + judge, [7] RAG chunks 
  with scores/citations, adjustment notes). This enables monitoring and loop 
  improvement from real usage.
- **Chat vs Structured**: Natural language chat inputs are parsed to structured 
  (role/cert/work_signals) then run the full pipeline; the UI receives formatted 
  Markdown. Structured invoke/Call receives the full machine result + citations.

## Fabric IQ Ontology Structure (aligned to Microsoft Fabric / AI Skills Navigator)
Per the referenced labs ("Create an ontology with Fabric IQ", "Build an ontology from a semantic model in Fabric IQ", "Configure ontology relationships", "Generate from Power BI semantic model") and grounding video context:

- **Semantic Model source** (our analogue of Power BI / Direct Lake semantic model): Role_certification_matrix (roles as "tables", primary/secondary/key-skills as relationships + attributes) + certification guides + learners/work_signals.
- **Entity Types** (concepts on the ontology canvas): Role, Certification (with props: skills list, recommended_hours, pass_threshold, difficulty, prerequisites), Skill, Learner (practice_score, hours_studied, role). Keys = ids/names.
- **Relationship Types** (typed connections, generated from the semantic model relationships): 
  - recommended_for (Role → Certification, primary vs secondary, cardinality many-to-one)
  - prereq_of (Certification → Certification, transitive chains e.g. AKS requires Container Instances + Networking)
  - requires_skill (Certification → Skill)
  - has_gap (derived: Learner to required skills with current/required levels + priority)
- **Bindings / Grounding**: Data loader binds abstract entities to concrete sources (lakehouse-style local data_root tables/json + guides). Static facts (cert reqs) vs signals (work context / progress, hinting at time-series).
- **Inference / Rules** (the "reasoning" over the ontology for agents): calculate_plan_feasibility (capacity + gap_penalty + time), estimate_time_to_readiness, build_skill_gap_analysis, role_certification_alignment, get_full_prerequisite_chain. These produce objective derived facts used by Orchestrator (plan steps), Specialists, and especially the Critic (accept/reject with confidence).
- **Preview / Observability**: reasoning_trace + demo [3][6] sections + rich Chat MD "Ontology facts" + Call result act as the graph preview. Agents query the ontology for grounding (exactly "Ground AI Apps with Fabric IQ’s Semantic Foundation").

The multi-reasoning agent plan follows this: FabricIQ = the ontology layer (entities + relationships + inference per Fabric pattern) providing the semantic foundation. Specialists + RAG (FoundryIQ) + LLM provide generative content on top. Critic is the objective checker over ontology-derived signals. Full trace makes the ontology usage reviewable for the Reasoning Agents track.
- **Real RAG when available**: Prefer hybrid search (AzureSearchFoundryIQ with 
  admin key or MI) over local stubs. Index must be populated with vectors for 
  embeddings. Fall back gracefully but log clearly.

## Key Data & Rules (from Role_certification_matrix + guides)
- Role-to-cert alignment: Cloud Engineer → AZ-204 primary; DevOps → AZ-400; 
  Data Engineer → DP-203, etc. Low alignment (<0.6) triggers prerequisite or 
  alignment_check step.
- Feasibility: Combine plan hours, learner current skills vs required, 
  work_signals capacity, gap_penalty. Objective: accepted only if is_feasible 
  and critic passes.
- Milestones: Week-based, with topics, hours, prerequisites. Must be actionable 
  and hands-on heavy where signals allow.
- Gaps & prereqs: Always surface explicit skill gaps and missing prereqs from 
  FabricIQ. Plans must address them.
- LLM synthesis: Use for module descriptions, questions, adjustments. Always 
  validate citations post-generation. Allowed citations provided to specialists.

## Usage in Agents / Orchestrator
- Load at init or per-request via FabricIQ + data loaders.
- Pass as context to specialists: learning_path, study_plan, assessment, etc.
- Critic uses it for enriched verification (gaps, time estimates, feasibility).
- For loops: a long-running or multi-turn learner plan should resume from 
  persisted state (see state management) and re-apply this skill + latest RAG.

## Monitoring & Improvement Signals (for outer loops)
When this skill is active in production (hosted agent):
- Raw chat natural language and parsed structured requests appear in container 
  logs via readiness_server POST preview.
- Per-request: iterations, critic accept/reject, feasibility scores, RAG 
  citations used, adjustment applied, final plan quality.
- Use these to feed review loops: low feasibility, poor citation match rate, 
  repeated prereq issues → candidate for skill update, more data in matrix, 
  tighter critic thresholds, or new sub-agent verifier.

## Anti-Patterns (do not)
- Free-text invention without RAG or matrix backing.
- Ignoring work_signals (over-optimistic hours).
- Writer = checker (no separate verification).
- No state across turns (restarts from zero, loses learner progress).
- Silent fallbacks that hide real RAG or LLM problems.

This skill, combined with the orchestrator's critic loop, sub-agents (specialists), 
RAG connectors, and persistent state, embodies loop engineering for reliable, 
observable, self-improving certification planning.
