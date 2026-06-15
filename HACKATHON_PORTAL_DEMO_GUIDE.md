# CertifyForge Reasoning Agents - Hackathon Demo & Portal Testing Guide
**Track**: Reasoning Agents (Microsoft Foundry / Azure AI Agents)
**Goal**: Presentable, observable, winning entry showcasing advanced multi-step reasoning (plan → RAG+FabricIQ → act (specialists) → critic/verifier → LLM adjust that mutates plan) + stateful multi-turn + skills + real grounding.
**Deadline**: June 14
**Status (post hosted-agent-dev-loop + re-reviews)**: 0 blocking issues. Code hardened (state/skill/trace/NL routing). Local demo --seed 0 reproduces full log. RBAC assigned + deploy in progress for hosted parity.

## 1. Local Replay (always works, matches user-provided live log)
From CREATIVE_APP_02 root (or src/certifyforge_agents):

```powershell
cd src\certifyforge_agents
..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0
```

**Expected output highlights (from provided successful run)**:
- [1] GROUNDING LAYERS: real Foundry LLM (gpt-4.1-mini), real AzureSearchFoundryIQ (srch-mn2jqe7dqgbxk / az204-certification-index with key_auth), FabricIQ active.
- [2] USER REQUEST: fixed AZ-400 DevOps Engineer, work_context={'meeting_hours_per_week': 30, 'focus_hours_per_week': 6, ...}
- [3] FABRIC IQ: Role-Cert Alignment 1.00, prereqs AZ-204/AZ-104, hours 100, threshold 0.75.
- [4] ORCHESTRATION + CRITIC/VERIFIER LOOP: iterations=1 (or 2 with critic), specialists: Orchestrator, LearningPathCurator, StudyPlanGenerator, EngagementAgent, AssessmentAgent, ManagerInsights.
  - Critic: ACCEPTED (confidence ~0.9-0.92 for study/assess).
  - Post-critic LLM Personalized Adjustment mutates: "Schedule regular hands-on labs..." appended to milestones + total_hours adjusted.
  - Final Status: completed_with_verification
  - LLM tokens cumulative ~2823.
- [5] DETAILED RESULTS: prereqs verified (none missing), learning path with citations (AZ-400_Guide.md), study plan (feasibility 0.67, weeks~6-8, capacity risk low, alignment 1.0), assessment readiness 0.83 Passed, LLM Judge score 7.
- [STATE] MULTI-TURN STATE RESUME: second handle(prior_state=...) shows Turn-2 state_resumed_from: True, skill_used: True, plan evolves.
- [6] DIRECT FABRIC IQ QUERIES: skill gaps, time to readiness ~5 weeks, prereq chains.
- [7] REAL FOUNDRY IQ (AZURE AI SEARCH) LIVE RETRIEVAL: 2 cert-tagged chunks from AZ-400_Guide.md, scores, hybrid search.
- Trace elements: reasoning_trace with plan_steps, iterations, critic_decisions, rag_citations_used, adjustment_applied, state_resumed_from, skill_context_used.

This is the exact "LIVE ARCHITECTURE DEMO" user pasted. Use for judges (local or after deploy parity).

## 2. Portal Testing (after azd deploy succeeds - new image with fixes)
**Target agent**: certifyforge-agents (hosted, kind:hosted, protocols:responses per agent.yaml)

### A. Live Logs (Foundry portal - primary observability for loops)
1. Go to Azure AI Foundry portal → your Project (ProjectCert) → Agents → certifyforge-agents (or the deployed one).
2. Open **Logs** (live stream / Log Stream tab).
3. Trigger requests (see below).
4. Watch for:
   - `[Server] POST /responses ...` (preview of body for every request - defensive).
   - Orchestration prints: "INFO: Orchestrator received request...", "Routing to specialist: ...", "Orchestration iteration X", "[Grounding] Using hybrid search...", "[FabricIQ] data_root resolved..."
   - Critic: "Critic Decision : ACCEPTED (confidence=...)"
   - State: "INFO: Resumed state from /tmp/certifyforge_learner_state.json..." or per-role file.
   - Skill: "INFO: Loaded certification skill from .../certification_skill.md"
   - RAG: "Retrieved X cert-tagged chunks from Azure AI Search", citations.
   - Adjustment: "LLM Personalized Adjustment: ..."
   - Full [1]-[7] sections when using demo path, or equivalent in hosted.
   - readiness_server always-200 + envelope logs.
5. This feeds the **meta review loop** (outer loop engineering): copy interesting traces/POSTs/errors into local files, re-run hosted-agent-dev-loop skill on any polish, or manual fix. Matches "how the foundry portal will be monitored for logs and chat responses for further review".

### B. Chat Tab (NL complex queries → full rich reasoning, fast for generic)
- Use the **Chat** interface (hosted Responses protocol).
- **Complex NL prompt** (exact from hackathon target + user demo log — this one reliably triggers the *full bespoke multi-step reasoning* with critic loop, Fabric IQ ontology facts, RAG (or fallback), and rich MD trace):
  ```
  Help me with AZ-400 as a DevOps Engineer. I have lots of meetings (30 hours/week) and limited focus time (6 hours/week). Preferred slot: Evening.
  ```
  (After the recent trace enrichment, the response will start with a prominent **Bespoke Multi-Step Reasoning Highlights (Fabric IQ Ontology + Critic Loop)** section showing alignment, prereq chains, feasibility breakdown from the ontology rules, gap penalty, iterations, etc. This is the "actual bespoke reasoning" visible for judges.)
  (Or shorter: "Help me prepare for AZ-400 DevOps with high meetings and limited focus")
- Expected:
  - No spinner for simple "hi" (fast path preserved).
  - For this: full orchestration (rich), then **beautiful Markdown response** including:
    - The plan (prereqs, learning_path, study_plan with capacity-aware weeks/hours, engagement, assessment readiness score 0.83, manager_insights).
    - ## Multi-Step Reasoning Trace section (from format_certification_response + reasoning_trace):
      - Enumerated plan steps.
      - RAG citations list (AZ-400_Guide.md etc.).
      - Critic decisions (ACCEPTED/REJECTED + issues).
      - Adjustment applied note (the hands-on labs mutation).
      - State/skill flags (state_resumed_from, skill_context_used).
  - Dynamic hands-on reinforcement milestone.
- **Multi-turn demo** (stateful):
  - Turn 1: the above prompt.
  - Turn 2: "Update the plan for even less focus time" or "What are the prereqs again?" or "Add more labs".
  - Watch Logs for "state_resumed_from: True", "skill_used: True", prior_state influencing (capacity/gaps carried, plan evolves).
  - Matches the [STATE] MULTI-TURN STATE RESUME DEMO in the pasted log.
- Download session (if available) for judges: shows full conversation + responses.

### C. Call / Invoke / Structured (full data + reasoning_trace for judges)
Use the **Call** tab, or CLI:
```powershell
# From project root (after azd up/deploy, azd env ready)
azd ai agent invoke certifyforge-agents '{
  "role": "DevOps Engineer",
  "certification": "AZ-400",
  "work_context": {
    "meeting_hours_per_week": 30,
    "focus_hours_per_week": 6,
    "preferred_learning_slot": "Evening"
  }
}'
```
- Or via portal Call: paste the structured JSON.
- Expected response envelope:
  - "result" with full orchestration output (prereqs, learning_path sample with citations, study_plan with feasibility/alignment/critic, assessment score, manager insights, LLM adjust).
  - "reasoning_trace": {
      "plan_steps": [...],
      "iterations": 1,
      "critic_decisions": [{"step": "study_plan", "decision": "ACCEPTED", "confidence": 0.92, ...}],
      "rag_citations_used": ["AZ-400_Guide.md", ...],
      "adjustment_applied": "Schedule regular hands-on labs...",
      "state_resumed_from": true/false,
      "skill_context_used": true,
      "multi_step_reasoning": "..."
    }
  - Also "choices"/"output" for Responses protocol compatibility.
- This is the "full rich" vs Chat's rendered MD. Perfect for demoing the internal critic/loop/RAG/Fabric without UI sugar.

### D. /readiness and other
- Agent exposes /readiness (always 200 "OK" even if demo running in bg per entrypoint).
- Fast vs full: generic/short queries stay fast (preview); complex role+cert signals → full run_full_orchestration (state+skill+critic+trace).

## 3. Hackathon Presentation Tips (Reasoning Agents track)
- **Show loops**: Local demo --seed 0 (full printed [1-7] + [STATE]) + portal Logs (live [Server] + orchestration steps + critic + RAG + state resume) + Chat (visible MD trace) + Call (structured trace + data).
- **Emphasize loop engineering** (per addyosmani + 0xCodez posts):
  - Inner agent loops: Orchestrator iterations + explicit CriticVerifier (Fabric-enriched) + post-critic LLM adjust that *mutates* the actual plan/milestones/hours (not just comment).
  - State/memory: persistent /tmp/..._state.json (per role/cert), prior_state passed, multi-turn resume (plans remember prereqs/gaps/adjusts). "Agent forgets, repo/state does not."
  - Skills: certification_skill.md (principles: faithful citations, capacity-aware, maker+checker, observable, anti-patterns) loaded/attached, reduces re-derive, compounds across turns.
  - Sub-agents + gates: 5 specialists (makers) + Critic (checker) + LLM adjust + Orchestrator planner. Verifier loop until accept.
  - Outer/meta: this dev loop (hosted-agent-dev-loop skill with parallel reviewers until 0 issues), portal logs feeding review/fix cycles.
  - Observable: reasoning_trace + rich MD + logs (no black box).
- **Foundry specifics**: real RAG (Azure AI Search hybrid + admin key via azd), real LLM (Foundry gpt-4.1-mini via ProjectCert), FabricIQ (bundled semantic ontology for prereqs/gaps/feasibility from Role_certification_matrix + signals), azd single source (envs, deployments), hosted (Responses, readiness_server shim, agent.yaml with ${} + RUN_DEMO_ON_START for parity).
- **Demo script**:
  1. Play local --seed 0 (or show pasted log) → point out critic accept, mutate, real RAG [7], state [STATE].
  2. Portal: trigger the NL prompt in Chat → show live Logs filling with steps + MD trace appearing.
  3. Multi-turn in Chat → Logs show resume.
  4. Call/structured invoke → expand reasoning_trace.
  5. Mention: "All via Microsoft Foundry hosted agent, observable in portal, hardened via loop engineering + parallel review (0 blocking)."
- **Evidence artifacts** (include in submission or deck):
  - This HACKATHON_PORTAL_DEMO_GUIDE.md + the user-provided full demo log.
  - /tmp/grok-hosted-impl-summary-4d31e1c1.md (design, why winning).
  - /tmp/grok-hosted-review-4d31e1c1.md (0 blocking, all reviewers).
  - Screenshots: Logs with [1-7], Chat MD trace, Call envelope+trace, multi-turn.
  - Local command output + azd invoke post-deploy.
- **Why winning**: Directly demonstrates "multi-step plan/reason/act" with self-reflection (critic), adaptation (mutating adjust), grounding (real RAG+Fabric), memory (state+skill), full observability on the platform. Matches track + posts on loop engineering. Presentable, reproducible, no hidden magic.

## 4. Monitoring → Improvement Meta-Loop (post-demo)
- During/after hackathon sessions: use portal Logs + downloaded Call/Chat sessions as input.
- Feed to hosted-agent-dev-loop skill (or manual) for targeted polish (e.g., deeper skill text injection if residuals).
- Re-deploy via azd, re-test.
- Signals in skill (certification_skill.md): "monitoring signals for outer loops".
- This is the full "use loop skill where necessary" + "how foundry portal will be monitored".

## 5. Quick Reference Commands (post-deploy)
```powershell
# Local full demo (reproducible hackathon case)
cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0

# Structured invoke (azd)
cd C:\Users\abdul\CREATIVE_APP_02
azd ai agent invoke certifyforge-agents '{ "role":"DevOps Engineer", "certification":"AZ-400", "work_context":{"meeting_hours_per_week":30,"focus_hours_per_week":6,"preferred_learning_slot":"Evening"} }'

# Check deployed agent
azd ai agent show certifyforge-agents

# Env / readiness (if local server)
azd env get-values
# (hosted: portal shows status)
```

## 6. Notes / Constraints Met
- azd single source of truth (envs, no hardcoded keys/endpoints).
- Demo/hosted parity (same orch paths, --seed 0 exercises the rich case, hosted uses state/skill too).
- readiness_server: always 200, preview logs, complex NL → full (for demo value of visible reasoning), fast generic.
- No try/except weakening.
- Real RAG + Fabric + LLM synthesis + critic mutate all active.
- review-scope.md risks addressed (envelope shape, routing, /tmp unique per-learner, trace post-mutate, etc.).

**Next after deploy success**: Re-run azd ai agent invoke or portal Chat with the complex prompt. Capture new logs/screenshots showing the same rich [1-7] elements + trace in hosted. Update this guide with any new outputs. Re-apply skill loop only on residuals.

This + the live demo log = complete, presentable, loop-engineering-powered Reasoning Agents submission.

## 7. MCP Alignment (Microsoft Learn MCP Server + Guidelines)
Reasoning is **grounded** (Fabric IQ ontology + real Azure AI Search RAG/FoundryIQ) per the implementation. This aligns with MCP guidelines: https://github.com/microsoftdocs/mcp and https://learn.microsoft.com/en-us/training/support/mcp . The system can be extended with the Microsoft Learn MCP Server (endpoint `https://learn.microsoft.com/api/mcp`, tools: `microsoft_docs_search` / `microsoft_docs_fetch` / `microsoft_code_sample_search`) to pull live official MS certification docs + code samples at runtime. This further eliminates hallucinations on cert content (e.g. exact syllabus, APIs, samples for AZ-400/DP-600 etc). Suggested for future: integrate via MCP client (VS Code / Claude / Foundry) or `/plugin install` (e.g. `/plugin install microsoftdocs/mcp` or `microsoft-docs@claude-plugins-official`) + agent skills (microsoft-docs / microsoft-code-reference). See starter-kit tip on using Learn MCP for cert prep architectures.

## 8. Architecture PNG Mapping (from https://github.com/carlotta94c/agentsleague starter-kits/2-reasoning-agents)
Explicitly matches the "grounded multi-step reasoning agents" track starter (reasoning-agents-architecture.png + reasoning-agents-challenge-architecture.png):
- **plan**: SimpleOrchestrator.create_plan (consults FabricIQ for prereqs/alignment; dynamic steps incl. prerequisite_check, role_alignment_check + 5 specialist steps).
- **reason with ontology/RAG like FabricIQ + FoundryIQ**: FabricIQ (Role_certification_matrix + rules → gaps, feasibility, prereq chains, role alignment, time-to-readiness as semantic ontology/inference) + AzureSearchFoundryIQ (hybrid RAG on real index for citations in specialists) + FoundryLLMClient.
- **act via 5 specialists**: LearningPathCurator (FoundryIQ/RAG + MS Learn-aligned), StudyPlanGenerator (FabricIQ capacity), EngagementAgent (work signals), AssessmentAgent (readiness + Fabric/Foundry), ManagerInsightsAgent (team patterns + Fabric).
- **critic/self-reflect/verifier loop**: SimpleOrchestrator iterations + _run_critic on study_plan/assessment (SimpleCriticVerifier enriched w/ FabricIQ feasibility/gaps/penalty; accept/reject/retry until gates or max iters; self-reflection in trace).
- **adjust (post-critic LLM mutates plan)**: LLM Personalized Adjustment (after critic) that *mutates* actual study_plan milestones (e.g. append hands-on) + total_hours; post-mutate trace + state save.
- **state/skills for memory**: Optional state_path (load/resume prior_plan/gaps/adjust/progress per-learner/cert; multi-turn in Chat/Call), skill_path (certification_skill.md loaded/attached for persistent domain principles/maker-checker/anti-patterns; reduces re-derive).
- **observable traces/logs/portal Chat&Call parity**: reasoning_trace (plan_steps, iterations, critic_decisions, rag_citations_used, adjustment_applied, state_resumed_from, skill_context_used, bespoke_fabric_iq_facts, multi_step_reasoning); rich [1-7] prints + MD "Bespoke Multi-Step Reasoning Highlights" + "Multi-Step Reasoning Trace (plan → reason... → adjust)"; startup demo (entrypoint) + per-request in Logs; Chat (NL→full rich MD w/ trace for complex), Call/invoke (full envelope w/ result + reasoning_trace); local demo --seed 0 parity.
This implements the starter's cert-exam student prep scenario (learning path curator, study plan gen, engagement, assessment, cert planning/feedback) using advanced patterns (planner-executor, critic/verifier, self-reflect/iteration, role specialization) + MCP extension path for official docs. Matches submission reqs for multi-step reasoning (25% criteria), MCP integration note, docs on flow/roles.

## 9. Final Submission Package Checklist
- Logs: local demo --seed 0 full output; portal Logs (startup [1-7] + per Chat/Call [Server] POST + orch/critic/RAG/adjust/state); session downloads from Chat/Call.
- Screenshots: rich Chat (Bespoke Multi-Step Reasoning Highlights + Multi-Step Reasoning Trace w/ plan/reason/act/critic/adjust + citations + adjustment mutation); Call agent tab (envelope w/ result + full reasoning_trace); Logs stream during demo; azd ai agent show + invoke output.
- Local demo: `demo_orchestration.py --seed 0` (reproducible [1-7] + [STATE] + trace labels); captured summary snippet.
- azd: `azd ai agent show certifyforge-agents`, `azd env get-values`, post-deploy invoke; azure.yaml + agent.yaml (azd ${VAR} single source); infra status.
- Cost/compliance notes: Real grounding uses provisioned Azure AI Search + Foundry models (pay for tokens/search); no Fabric platform; admin key/RBAC as noted; defensive boundaries + always-200 readiness; self-contained data (no external PII leak); MCP future path for trusted MS content (no halluc on certs).
- Cleanup performed: temp state files (/tmp/certifyforge_*_state.json), pycache where needed, no hardcoded keys (all azd-driven); index pop script optional post-provision.
- Other: This HACKATHON guide + root/README/src README updates; 103+ tests pass; parser broad-cert support (DP-600 etc no default regression); fmt/clippy clean. All via hosted certifyforge-agents on ProjectCert.
