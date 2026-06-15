# CertifyForge – Reasoning Agents

This project implements a multi-agent system for enterprise certification management, following the official architecture defined in:

**`Reasoning_Agents__Multi-Agent_Architecture__Approach.pdf`**

## Current Status (as of June 2026)

**Hosted deployment is complete and observable.**

The clean multi-agent implementation in `src/certifyforge_agents/` is fully deployed as a **hosted Azure AI Agent** (`certifyforge-agents`) on Azure AI Foundry (ProjectCert project) using `azd` + `azure.ai.agent`.

### Key Delivered Capabilities
- **Orchestrator + 5 Specialists + Explicit Critic** with self-reflection loop.
- **Real LLM synthesis** (gpt-4.1-mini via FoundryLLMClient + ProjectCert, DefaultAzureCredential in hosted).
- **Real RAG** (AzureSearchFoundryIQ with hybrid keyword + vector search on the provisioned index; admin key for reliable key_auth in container).
- **FabricIQ** (in-process semantic ontology/rules engine using bundled certification matrix, learners, work signals, guides — provides gaps, feasibility, time-to-readiness, prereqs, role alignment).
- **Post-critic LLM personalized adjustment** that actually mutates study plan milestones and hours.
- **Full observability** in container logs: rich `[1]–[7]` sections, LLM usage (cumulative), judge scores + justifications, real citation chunks, Fabric IQ details, adjustment notes.
- **Portal UX**:
  - **Chat tab** ("hi" etc.): fast lightweight path (immediate reply, no heavy run). The rich demo already ran at container startup.
  - **Call agent tab** + `azd ai agent invoke`: full rich orchestration (structured payload → complete result with citations, plan, adjustment, etc.).
- **Defensive readiness server** (always 200, body preview logging on every POST for diagnosis, try/except everywhere, no "processing your request" errors).
- Self-contained data (everything the container needs is inside the package under `data/`).
- azd is the single source of truth for all configuration (environment variables via `${}` substitution in agent.yaml).

The startup demo (triggered by `RUN_DEMO_ON_START`) + per-request handler produce the exact rich logs the user asked for. Real RAG, hybrid, citations, Fabric decisions, LLM markers, judge, and plan mutation are all visible without any local synthetic fallback when the index is populated.

**No Microsoft Fabric (the platform) is involved.** "FabricIQ" is the internal name (from the architecture PDF) for the semantic/rules layer implemented in pure Python + bundled data files. The external retrieval/knowledge store is Azure AI Search (vector index). See the "Provisioned Azure Resources" section below.

## Project Structure

```
CREATIVE_APP_02/
├── azure.yaml                          # azd single source of truth (service + deployments list)
├── infra/                              # Bicep (AI project/existing, search, ACR, roles, monitor)
├── src/
│   └── certifyforge_agents/            # The deployable unit (package + container context)
│       ├── orchestrator/               # SimpleOrchestrator (planner + router + critic loop + adjustment)
│       ├── agents/                     # 5 specialists
│       ├── grounding/
│       │   ├── foundry_llm.py          # FoundryLLMClient (real gpt-4.1-mini + embeddings)
│       │   ├── azure_search_foundry_iq.py  # Real hybrid RAG (key_auth + admin key)
│       │   └── fabric_iq.py            # Internal FabricIQ (semantic rules + gaps + feasibility from bundled data)
│       ├── evaluation/                 # Critic / Verifier
│       ├── data/                       # Self-contained (Role_certification_matrix, guides, learners.json, work_signals.json)
│       ├── readiness_server.py         # Responses protocol shim (chat fast-path vs full structured, always-preview, always-200)
│       ├── entrypoint.sh               # bg demo (rich logs) + exec server (healthy agent)
│       ├── Dockerfile + agent.yaml     # Hosted container definition
│       ├── demo_orchestration.py       # Local rich demo (matches hosted startup logs)
│       └── STATUS.md                   # Exhaustive history + commands
├── scripts/populate_search_index.py    # Creates vector index + embeds + uploads (hybrid RAG)
└── README.md, REVIEW_AND_DEMO.py
```

## Current Architecture (Local + Hosted)

### Layered View (from the PDF + current implementation)

```
Request (role + certification + work_signals)
          │
          ▼
   SimpleOrchestrator (Planner + Router + Critic loop + post-critic adjustment)
          │
          ├─► Specialists (each does grounding.retrieve first for "Allowed Citations")
          │     • Learning Path Curator   → Foundry IQ (LLM + RAG citations)
          │     • Study Plan Generator    → Fabric IQ (gaps, feasibility, hours, prereqs)
          │     • Engagement Agent        → Work signals
          │     • Assessment Agent        → Foundry + Fabric IQ
          │     • Manager Insights Agent  → Work + Fabric IQ
          │
          ├─► Critic / Verifier (enriched with Fabric IQ details)
          │
          └─► LLM personalized adjustment (mutates actual study_plan milestones + total_hours)
                    │
                    ▼
              Rich result (status, plan, results, citations, llm_personalized_adjustment, usage, judge)
```

**Grounding layers (wired to specialists + orchestrator):**
- **Foundry IQ** = `FoundryLLMClient` (synthesis + judge) + `AzureSearchFoundryIQ` (hybrid search on real index, citations, "EXACT match only" faithfulness).
- **Fabric IQ** = `FabricIQ` (local bundled data: Role_certification_matrix + JSONs → role alignment, skill gaps, capacity rules, time estimates, prereqs). Pure Python, no external service.
- Work signals come from the request payload (light but present).

**MCP + Starter Alignment (grounded reasoning per track guidelines):** Reasoning here is grounded via Fabric IQ (ontology/semantic rules) + real Azure AI Search RAG (FoundryIQ). Per MCP guidelines (https://github.com/microsoftdocs/mcp , https://learn.microsoft.com/en-us/training/support/mcp), this can be extended with Microsoft Learn MCP Server at `https://learn.microsoft.com/api/mcp` (tools `microsoft_docs_search` / `microsoft_docs_fetch` / `microsoft_code_sample_search`) to fetch live official MS cert docs/code samples, further eliminating hallucinations on certification content. Future: MCP client integration or `/plugin install microsoftdocs/mcp` (or microsoft-docs@claude-plugins-official) + skills. Matches https://github.com/carlotta94c/agentsleague starter-kits/2-reasoning-agents (reasoning-agents-architecture.png + challenge PNG): explicit `plan` (orchestrator.create_plan w/ Fabric prereqs) → `reason(ontology/RAG like FabricIQ + FoundryIQ)` → `act(5 specialists)` → `critic/self-reflect/verifier loop` (iterations + enriched critic) → `adjust` (post-critic LLM mutates plan milestones/hours) + state/skills (memory/resume + persistent domain) + observable traces/logs + portal Chat&Call parity. Emphasizes grounded multi-step reasoning agents track starter (planner-executor + critic patterns + MCP path for cert prep scenario). See HACKATHON_PORTAL_DEMO_GUIDE.md for full mapping + submission checklist.

**Runtime modes:**
- **Local demo** (`demo_orchestration.py --seed N`): direct Python, full prints.
- **Hosted container**:
  - Startup (bg via entrypoint): runs the exact same demo logic → rich `[1]–[7]` logs visible in portal Log stream.
  - Per-request (readiness_server.py):
    - Structured payload (role/cert present) → full orchestration (Call agent tab / `azd ai agent invoke`).
    - Chat-style (`{"messages":[...]}` or plain) → fast path (immediate helpful reply pointing at the startup demo logs). No 20-40s delay.

### Deployment & Azure Flow (ASCII)

```
Local source (src/certifyforge_agents)
          │ azd deploy --service certifyforge-agents
          ▼
   Dockerfile → build → push to ACR
          │
          ▼
   agent.yaml (kind:hosted, protocols:responses, ${AZURE_...} envs)
          │
          ▼
   Azure AI Agent "certifyforge-agents" (active in ProjectCert)
          │
   Container (MI identity)
     • entrypoint.sh (demo bg + exec readiness_server)
     • readiness_server (HTTP on PORT, /readiness 200, POST dispatch)
          │
   Azure resources (see detailed list below)
     • AI Project (ProjectCert) + gpt-4.1-mini + text-embedding-3-small
     • AI Search (srch-mn2...) + populated vector index
     • ACR + AcrPull
     • MI + OpenAI User + Search roles (or injected admin key)
```

### Mermaid Diagram (recommended – renders on GitHub)

```mermaid
flowchart TD
    subgraph User["User / CLI / Portal"]
        Invoke[azd ai agent invoke\nstructured JSON]
        Chat[Portal Chat tab\n'hi' / messages]
        Call[Portal Call agent tab\nstructured]
    end

    subgraph Agent["Azure AI Agent (hosted, responses protocol)"]
        AgentDef[certifyforge-agents\nProjectCert]
    end

    subgraph Container["Container (readiness + demo)"]
        EP[entrypoint.sh\nRUN_DEMO_ON_START=0]
        DemoBg[Background\nDemo Orchestration\n[1]-[7] rich logs]
        Server[readiness_server.py]
        Fast[Fast path\nChat 'hi']
        Full[Full path\nCall / invoke]
    end

    subgraph Core["Multi-Agent Core"]
        Orch[SimpleOrchestrator\n+ Critic + Adjustment\n(mutates plan)]
        Specs[5 Specialists]
        LLM[FoundryLLMClient\ngpt-4.1-mini + embeddings]
        RAG[AzureSearchFoundryIQ\nhybrid + citations]
        Fabric[FabricIQ\nlocal bundled rules/gaps/feasibility]
    end

    subgraph Azure["Provisioned Azure"]
        AIProj[AI Project\nProjectCert\n(existing)]
        Models[Model Deployments\ngpt-4.1-mini\ntext-embedding-3-small]
        Search[AI Search\nsrch-mn2jqe7dqgbxk\n+ az204-certification-index\n(vector + content)]
        ACR[ACR\nimage]
        MI[Managed Identity\n+ RBAC / Admin Key]
    end

    Invoke --> AgentDef
    Call --> AgentDef
    Chat --> AgentDef

    AgentDef --> Server
    EP --> DemoBg
    EP --> Server
    Server -->|non-structured| Fast
    Server -->|role + cert| Full

    Full --> Orch
    Orch --> Specs
    Specs -->|first| RAG
    Specs -->|rules| Fabric
    Specs --> LLM
    RAG --> Search
    LLM --> Models
    Orch -->|post-critic| LLM

    DemoBg --> Orch
    DemoBg --> RAG
    DemoBg --> Fabric
    DemoBg --> LLM

    AgentDef -.-> ACR
    AgentDef -.-> MI
    MI --> ACR
    MI --> AIProj
    AIProj --> Models
    Search -. populated by .-> scripts/populate_search_index.py
```

(ASCII version above + the Mermaid for rich rendering.)

## Applying Loop Engineering (from Addy Osmani / 0xCodez patterns)

"Loop engineering" (per the June 2026 posts) shifts leverage from hand-typing prompts to **designing small systems that repeatedly prompt agents**, with built-in discovery, execution, verification, state, and decision-making. You build the loop once; it runs (and improves) the work.

The five core building blocks + state (the "agent forgets, the repo/state does not"):

1. **Automations** — heartbeat/schedule or event-driven discovery & triage (e.g., the portal Chat/invoke as trigger; internal critic iterations; bg demo on start; potential GitHub Actions or /loop for scheduled re-planning).
2. **Worktrees / Parallel isolation** — safe concurrent agents (dev process uses subagent isolation; runtime specialists run with retry_context + seeds to avoid collision).
3. **Skills** — persistent project/domain knowledge (we formalized `data/certification_skill.md` as SKILL.md-style: principles, rules, anti-patterns, monitoring signals. Loaded in orchestrator and available to sub-agents/specialists so they don't re-derive from zero).
4. **Connectors / MCP** — touch real tools (FoundryLLM + AzureSearchFoundryIQ as RAG/LLM connectors; readiness_server as portal interaction connector; FabricIQ as semantic "database" connector over bundled data. Future: GitHub for examples, storage for state).
5. **Sub-agents (maker vs checker)** — split writing from verification. Already core: 5 specialists (makers/generators with RAG) + explicit Critic/Verifier (checker, enriched with FabricIQ for objective feasibility/gaps). Post-critic LLM adjustment is a refinement step. The parallel code review agent (see below) applies the same split at the meta level for the agent's own code.

Plus **state**: the orchestrator now accepts `state_path` (and `skill_path`) and does load/resume + save of key outputs (plan, results summary, adjustment, status). Multi-turn learner plans or scheduled runs can resume instead of cold-starting. For hosted, wire to Azure Storage via a future connector.

**Current mapping in certifyforge-agents (strong foundation already present):**
- Orchestrator `handle_request` + max_iterations + critic on critical steps (study_plan, assessment) + should_retry = a running loop with objective gates.
- Specialists as sub-agents; separate evaluation/critic as verifier (maker/checker split; "the model that wrote the code is too nice grading its own homework").
- FabricIQ + data/ + RAG = skills + connectors (semantic rules, gaps, prereqs, citations).
- `llm_personalized_adjustment` that *mutates* the actual plan (not just annotates) + rich per-request logs = observable refinement loop.
- readiness_server chat path: parses natural language → structured → full pipeline (intent → execution → verify → format) with state/skill hooks.
- Demo + per-request observability = the "review" signal for outer loops.

**Enhancements added for explicit loop engineering:**
- Optional `state_path` + `skill_path` on SimpleOrchestrator (with load/save, attach to specialist context).
- Example `data/certification_skill.md` (principles, maker/checker, anti-patterns, monitoring signals for the outer improvement loop).
- Context passing so sub-agents can use the skill + prior state without re-deriving.

**The parallel code review agent (already created with composer 2.5):**
The `.grok/skills/hosted-agent-dev-loop` skill is itself a production-grade loop engineering implementation for hardening the hosted agent:
- Automation: the implement → parallel-review → fix → re-review rounds (until 0 open issues).
- Sub-agents: implementer (maker) + parallel reviewer panel (general + security + tests + hosted-deployment checkers). Uses personas + review-scope.md checklist.
- State: LOOP_ID + summary/review files (the agent/subagents forget between rounds; the files remember).
- Worktrees/parallel isolation: subagent background execution (no file collisions).
- Skills: injected personas + review-scope as persistent checklist; full source reads beyond summaries.
- Connectors: spawn_subagent + file IO + (implicit) the project's own grounding for any code analysis.

This is how we (and you) will iteratively improve the loops *inside* the certification system and the agent's own code/resilience, using real observations.

## Monitoring the Foundry Portal (logs + chat responses) for further review & loop improvement

The Azure AI Foundry portal (ProjectCert project) + container instrumentation give excellent signals to feed back into improvement loops (the dev loop skill above, or a new meta "response reviewer" sub-agent/automation).

**Primary mechanism — Live Logs + session logs (container stdout):**
- In the agent details page (after switching to the correct ProjectCert project): **Logs** tab = live stream of the container.
- Every interaction (Chat natural language or structured Call/invoke) hits `readiness_server.do_POST`:
  - Always: `[Server] POST received, body_len=..., preview: <raw body>` — for Chat you see the exact natural language prompt (e.g. "Help me with AZ-400 as a DevOps engineer, I have lots of meetings"); for invoke the structured JSON.
  - Chat path: "Chat message received", intent parse results (role/cert/work_signals), decision to run full pipeline.
  - Structured: the request echo.
  - Then: `run_full_orchestration start`, `[Server][1] LLM/Grounding`, `[Server][3] FabricIQ`, `[Server][4] SimpleOrchestrator`, per-iteration routing, critic decisions/rejects/retries, `[Server] handle_request complete`, `llm_personalized_adjustment`, RAG details if enabled.
  - The exact assistant content returned (the formatted MD plan for chat; summary for structured) is visible in the "responding" line + the choices/output in the envelope.
- Background demo (on start) gives the baseline rich `[1]–[7]` run with real RAG/hybrid, Fabric gaps, judge, adjustment, etc.
- Downloadable session logs (per the ones you've shared) capture the same for post-hoc review; live stream is best for real-time during a Chat turn or invoke.

**Chat responses specifically:**
- In the Playground **Chat** tab you see the direct assistant reply (the loop-produced MD plan with role, estimated weeks, feasibility, gaps, adjustment, suggested actions, and the "would you like me to..." follow-ups).
- The full machine result (plan, results per specialist, citations, verification, adjustment) travels in the envelope and is available in the **Call agent** tab or `azd ai agent invoke` output.
- Because the chat path now does full orchestration + formatting (with state/skill), observed quality (e.g., feasibility scores, citation faithfulness from the RAG chunks in logs, whether adjustment actually mutated milestones) is directly reviewable.

**Aggregated / production monitoring (infra):**
- The bicep infra includes Application Insights + Log Analytics (monitor modules). Query for invocation volume (chat vs structured via the "source" or POST preview), error rates in handler, average iterations/feasibility, RAG latency, etc.
- Readiness/health probes surface in the platform; uncaught errors or low 200s would show here.
- Container resource metrics (CPU/mem from the hosted agent spec).

**Feeding observations back into improvement loops (closing the meta-loop):**
- Raw material: portal Logs (or exported App Insights) contain the exact user prompts (natural lang or JSON), parsed intent, internal loop iterations/critic accepts/rejects, final plan metrics (feasibility, gaps surfaced, adjustment applied, RAG citations used), returned content, and any errors.
- Example review signals for a "response reviewer" sub-agent or the parallel dev loop:
  - Low feasibility or high gap_penalty on real AZ-400 DevOps "high meetings" cases → tighten FabricIQ rules or add data to the matrix/skill.
  - Weak citation match rate in [7] sections for certain certs → improve populate script, embedding, or specialist prompts (the certification_skill.md).
  - Chat parses incorrectly for edge language → enhance parse_user_intent (or make it LLM-assisted sub-step with objective verification).
  - Adjustment not mutating milestones in observed plans → bug in post-processing.
- Process: (1) Run real usage in Chat/Call in the portal. (2) Capture via live logs or session download (or query App Insights). (3) Feed excerpts + metrics to the parallel reviewer panel (the hosted-agent-dev-loop skill, composed with composer 2.5 for the reviewer personas/checklists) or a dedicated sub-agent. (4) The panel produces structured issues (bug/suggestion/nit with file:line). (5) Resume implementer to fix. (6) Re-review until clean. (7) Deploy. (8) Observe the next round of portal behavior.
- This is exactly loop engineering applied at the meta level: the portal (automation/trigger) + logs (connectors + state) + sub-agents (maker/checker reviewers) + persistent review files (state) + the dev loop skill (the automation) produce better skills, better critic thresholds, better formatting, etc., which make the inner certification planning loops (orchestrator + specialists + critic + adjustment) higher quality on the next user chat.

**Practical commands / tips:**
- Live stream while testing: portal agent → Logs (keep open) + Chat or `azd ai agent invoke ...` in terminal. Search the stream for "AZ-400", "DevOps", your prompt text, "chat/full", feasibility numbers, or specific citations.
- After a turn: download the latest session log and grep for the POST preview body + "Orchestrator received request".
- To confirm a specific request hit the new paths: look for the exact role/cert in the preview or request log line (demo will always be the default AZ-204).
- For systematic review: script pulling recent logs or App Insights queries into a review queue that the parallel reviewer skill consumes.

The combination of (a) the inner loops in the certification agents (now with explicit state + skills) and (b) the outer dev/ improvement loop (the hosted-agent-dev-loop with its parallel reviewers, already set up via composer 2.5) + rich portal observability gives a self-reinforcing system: real user chats and invokes in the Foundry portal become high-signal training data for making the next version of the loops better. Build the loops. Stay the engineer (and the reviewer of what the loops produce).

## Provisioned Azure Resources (as of June 2026)

All core infrastructure is managed via `azd` + Bicep (see `azure.yaml` deployments list and `infra/`).

### Core Resources for the Agent
- **Azure AI Foundry Project**: `ProjectCert` (existing/manual project under the `projectcert-resource` AI Services account).  
  Provisioned/connected via `infra/core/ai/existing-ai-project.bicep` + connections.  
  This is the **target** for the hosted agent and model deployments (different from the azd-tracked dev project `ai-project-creative-app-02-dev` — this is why "Agent not found" appears on raw azd Playground URLs).

- **Model Deployments** (inside the AI Project / parent AI Services account):
  - `gpt-4.1-mini` (2025-04-14, GlobalStandard, capacity via azd)
  - `text-embedding-3-small`
  Declared in `azure.yaml` under `services.certifyforge-agents.config.container.deployments` and applied during `azd up` / provision / deploy.

- **Azure AI Search**:
  - Service: `srch-mn2jqe7dqgbxk` (SKU via `infra/core/search/azure_ai_search.bicep`).
  - Index: `az204-certification-index` (created/updated by `scripts/populate_search_index.py`).
  - Schema includes `content` + `content_vector` (1536 dimensions, HNSW vector search config for hybrid).
  - Populated client-side (embeddings via the same FoundryLLMClient path + upload). The index is the external knowledge store that powers real RAG citations for the specialists.
  - Auth in container: `AZURE_SEARCH_ADMIN_KEY` injected (key auth = reliable; `key_auth=True` in AzureSearchFoundryIQ). RBAC (Search Index Data Reader) is also supported as fallback.

- **Azure Container Registry (ACR)**:
  - Image: `certifyforge-agents` (pushed on `azd deploy`).
  - Connection from the AI Project to ACR (see `acr-connection*.json` artifacts and `infra/core/ai/connection.bicep` + role assignments).
  - Agent Managed Identity has `AcrPull`.

- **Hosted Agent Identity & Permissions**:
  - System-assigned (or user-assigned) Managed Identity created for the agent instance.
  - Required roles (granted via bicep or explicit `az role assignment create`):
    - AcrPull (on the ACR)
    - Cognitive Services OpenAI User (on the AI Services account for LLM/embeddings calls)
    - Search Index Data Reader (on the search service) — or the admin key as the robust bypass used in practice.

- **Other / Supporting**:
  - Log Analytics + Application Insights (monitor bicep modules) for logs/metrics.
  - Storage (if used by broader templates).
  - The agent definition itself (registered via azd + `agent.yaml` with environment variables substituted from azd env).

### Microsoft Fabric (the platform) Connection
**None provisioned or used for this agent.**

- "Fabric IQ" (see `grounding/fabric_iq.py`) is an **internal** semantic/rules layer implemented entirely in Python.
- It loads self-contained data bundled inside the container image (`src/certifyforge_agents/data/` + the package copy):
  - `Role_certification_matrix`
  - `learners.json`, `work_signals.json`
  - `certification_guides/*.md`
- Responsibilities: role-to-cert alignment, skill gap analysis, feasibility scoring, recommended hours, prerequisite chains, capacity rules.
- No lakehouse, no Microsoft Fabric workspace, no pipelines, no Direct Lake, no Fabric runtime.
- The **external** knowledge/retrieval for citations is provided exclusively by the Azure AI Search vector index (see above). FabricIQ and the RAG layer are complementary and both wired into the specialists and critic.

If a future phase adds Microsoft Fabric for data ingestion, governance, or as a source for the matrix, it would be added via new bicep + connections and would be documented here.

## Portal "Agent not found" (404) — operational footgun

`USE_EXISTING_AI_PROJECT=true` (default) points the hosted agent at an **existing** Foundry project (e.g. **ProjectCert**), while Bicep still emits `AZURE_AI_PROJECT_NAME=ai-project-<env>` for the azd-managed name. Portal and azd deep links that embed the azd project name in the URL therefore **404** with "Agent not found" even when `azd ai agent show` reports the agent as active.

**Workaround (recommended):**
1. Open Azure AI Foundry and switch to the project matching `AZURE_AI_PROJECT_ENDPOINT` (e.g. **ProjectCert**).
2. Navigate **Build → Agents** and open `certifyforge-agents` from the **list** — do not use the auto-generated Playground deep link.
3. Prefer `azd ai agent invoke certifyforge-agents '{...}'` for testing.

Align `.azure/<env>/.env` so `AZURE_AI_PROJECT_NAME` matches the live project when you need portal deep links, or set `EXISTING_SEARCH_SERVICE_NAME` / `AZURE_AI_PROJECT_ENDPOINT` explicitly before `azd provision`.

## Azure AI Search provisioning (existing-project default)

With `USE_EXISTING_AI_PROJECT=true`, Bicep auto-provisions Search + Storage when `EXISTING_SEARCH_SERVICE_NAME` is unset and `ENABLE_HOSTED_AGENTS=true`. To reuse an existing search service instead, set it **before** first provision:

```powershell
azd env set EXISTING_SEARCH_SERVICE_NAME <your-search-service-name>
azd provision
```

After provision, populate the vector index (required for hybrid RAG — not automated in the deploy pipeline):

```powershell
python scripts\populate_search_index.py
```

## How to Run & Test (Current Recommended Order)

See the detailed steps in `src/certifyforge_agents/README.md` (Hosted Agent Deployment & Testing section) and `STATUS.md`.

Quick local:
```powershell
cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0
```

Hosted (after `azd deploy --service certifyforge-agents`):
1. `azd ai agent show certifyforge-agents`
2. Portal: switch to **ProjectCert** → Agents list → `certifyforge-agents`
3. Logs (see startup demo with real RAG)
4. Chat tab (fast path) vs Call agent tab (full rich path)
5. `azd ai agent invoke certifyforge-agents '{ ... structured JSON ... }'`

Always populate the index first if you want the richest `[7] real RAG` evidence:
```powershell
python scripts\populate_search_index.py
```

## Useful Files & References
- `src/certifyforge_agents/README.md` — Detailed hosted testing, troubleshooting, Chat vs Call
- `src/certifyforge_agents/STATUS.md` — Exhaustive change log, exact commands, log analysis
- `src/certifyforge_agents/demo_orchestration.py` — The observable demo
- `src/certifyforge_agents/grounding/fabric_iq.py` + `data/` — The internal FabricIQ implementation
- `scripts/populate_search_index.py` — Vector index creation + population
- `infra/` + `azure.yaml` — What gets provisioned

---

*This project deliberately avoids the anti-patterns and technical debt that accumulated in previous attempts. azd is the single source of truth; everything is defensive and observable.*
