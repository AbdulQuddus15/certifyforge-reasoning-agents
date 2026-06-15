# CertifyForge Reasoning Agents (New Architecture)

This is the **clean implementation** of the multi-agent system following the official "Reasoning Agents — Multi-Agent Architecture & Approach" document.

## Goals (Avoiding Old Mistakes from Creative_App_01)

- **No more monolithic ResponsesHostServer** with all agents jammed together (major source of 424s and unhealthy processes).
- **True Orchestrator** as Planner + Router (not just exposing one specialist).
- **Explicit Critic / Verifier** layer (missing in previous attempts).
- **Clean separation** of Foundry IQ / Fabric IQ / Work IQ.
- Proper **Planner–Executor** and self-reflection patterns.
- Built on the modern azd + Bicep foundation already present in this repo (`CREATIVE_APP_02`).

## Architecture (Directly from the Plan)

```
Learner/Manager Request
        ↓
   Orchestrator (Planner + Router + Critic integration)
        ↓
   Specialist Agents:
     - Learning Path Curator   → Foundry IQ (cited content)
     - Study Plan Generator    → Fabric IQ (semantics + capacity)
     - Engagement Agent        → Work IQ (work signals)
     - Assessment Agent        → Foundry IQ + Fabric IQ
     - Manager Insights Agent  → Work IQ + Fabric IQ

   Critic / Verifier (validates plans & scores before returning)
```

## Latest (post-demo "next key step")
- Feasibility math + richer Fabric methods (gaps, time-to-readiness) integrated; 0.0 bug fixed.
- Real grounding (AzureSearchFoundryIQ) now flows to agents when AZURE_AI_SEARCH_* present.
- Demo + Orchestrator + Critic surface internal Fabric IQ decisions (skill gaps, penalties, prereq chains, critic issues/suggestions).
- Low-alignment + capacity edge cases now produce observable, non-zero, critic-annotated results while completing full flow.

## Running the demo (PowerShell)

From the package directory:

```powershell
cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0
```

See the top of `demo_orchestration.py` for more variants (including `--random-request`).

## Real Grounding (Azure AI Search)

To switch from the local stub to real RAG citations:

1. Deploy the search resources (`azd up` in the CREATIVE_APP_02 folder).
2. Assign "Search Index Data Contributor" to yourself on the search service.
3. Run the populator (from CREATIVE_APP_02 root, venv activated):
   ```
   python scripts\populate_search_index.py
   ```
   (Or `.\venv\Scripts\python.exe scripts\populate_search_index.py` if not activated)
4. Re-run the demo. It will detect the env var and use real Azure AI Search for Learning Path + Assessment content + citations.

The `AzureSearchFoundryIQ` class + updated demo section [7] prove end-to-end real grounding.

## Folder Structure

- `orchestrator/` — Main Orchestrator Agent (Planner + Router + Critic integration + loop management)
- `agents/` — All five specialist agents + base class (Learning Path Curator, Study Plan Generator, Engagement, Assessment, Manager Insights)
- `grounding/` — Abstractions + LocalFoundryIQ implementation (ready to swap for real Azure AI Search)
- `data/` — Models + SyntheticDataLoader + SyntheticDataFactory (self-contained)
- `evaluation/` — Critic/Verifier (SimpleCriticVerifier implementation)

## Hosted Agent Deployment & Testing (Azure AI Foundry)

The multi-agent system is now deployed as a hosted container agent using `azd` + the `azure.ai.agent` host.

### Deploy
```powershell
azd deploy --service certifyforge-agents
```

This builds the container (using the updated Dockerfile + entrypoint with readiness server), pushes to ACR, and publishes the agent definition to your AI project (ProjectCert in this setup).

### Verify
```powershell
azd ai agent show certifyforge-agents
```
Expect `Status: active`, version incremented, Playground URL, and responses Endpoint.

### Test with Invoke (sample payload matching the local demo)
Use this standard request (from `demo_orchestration.py`):

```powershell
azd ai agent invoke certifyforge-agents '{
  "role": "Cloud Engineer",
  "certification": "AZ-204",
  "work_signals": {
    "meeting_hours_per_week": 22,
    "focus_hours_per_week": 10,
    "preferred_learning_slot": "Morning"
  }
}'
```

Observe rich output: LLM-synthesized modules/descriptions/milestones/questions (with "(LLM-synthesized...)" markers if implemented), citations from RAG, Fabric IQ gaps/feasibility, Critic decisions, LLM adjustment, usage tokens, etc.

For randomized: add the equivalent of `--random-request` by varying the JSON.

**Exact order to see changes in full effect (after the chat fast-path fix):**
1. `azd deploy --service certifyforge-agents` (single clean deploy)
2. `azd ai agent show certifyforge-agents`
3. Portal: switch to ProjectCert, open agent from list → Logs (startup demo + readiness)
4. Chat tab → send "hi" → expect quick visible reply; download session log immediately after and capture the [Server] POST preview line
5. Call agent tab (or azd invoke with the JSON above) → full rich observable orchestration
6. (Optional but recommended) `python scripts\populate_search_index.py` (if you want fresh hybrid vectors) then re-invoke for [7] real RAG evidence.

### Playground / Portal (Chat vs Call + exact test order)
- **Primary recommendation**: Use the CLI `azd ai agent invoke` (see above) to test the *full rich path*. It exercises readiness_server + complete Orchestrator/LLM/RAG/Fabric/Critic/adjustment and produces clean session logs. It does not depend on web UI project scoping.
- The Playground URL printed by `azd ai agent show` / deploy can lead to "Agent not found" (see troubleshooting below). Instead:
  1. In the Azure AI Foundry portal, use the project switcher to select the project that matches your `AZURE_AI_PROJECT_ENDPOINT` (the one named/visible as **ProjectCert**, or whose URL contains `projectcert-resource.services.ai.azure.com/api/projects/ProjectCert`).
  2. Left sidebar → **Build** → **Agents** (or directly to the Agents section for that project).
  3. Search or scroll for **certifyforge-agents**. Click it from the list.
  4. Inside the agent details, use the tabs:
     - **Logs** first (after deploy): expect the startup demo burst with real RAG ("[Grounding] Using REAL...", "[OK] This is real RAG...", chunks + scores + citations), "[Server] Starting readiness server...", access tip for ProjectCert, etc.
     - **Chat** tab: type `hi` (or any short message) and send. With the fast-path fix it should show a visible assistant reply *immediately* (guidance text directing you to logs + the invoke command). This tab is lightweight conversational; it does *not* run the full multi-agent plan.
     - **Call agent** tab: paste the structured JSON payload (role + certification + work_signals) and invoke. This exercises the *full* rich path (same as azd invoke); expect the complete result with citations, plan, adjustment, etc. (may take 20-40s).

- After any Chat or Call interaction, download the session log for that run (it will now contain the diagnostic `[Server] POST received, body_len=..., preview: <exact JSON sent by the tab>` line). Paste the relevant POST/preview/response blocks when reporting.

- View Logs (for the agent or a specific session) to see container startup (demo for [1]-[7] observability + "Starting readiness server...") and per-request output from the defensive handler.

### Logs & Observability
- Portal: Agent > Logs or the specific session.
- Expect: demo orchestration output (for startup verification), readiness server messages, LLM calls (if visible), grounding queries.
- CLI: `azd ai agent monitor certifyforge-agents` (if available in your azd ai extension) or check the responses endpoint directly for traces.

### Notes / Limitations
- The container now passes readiness (via `readiness_server.py` shim returning 200 on /readiness and /health) so the session becomes active without `session_not_ready` timeouts.
- **Defensive POST handler + smart Chat support + loop engineering** (key for portal UX and self-improvement): 
  - *Always* prints `[Server] POST received, body_len=..., preview: ...` (first thing) for diagnosis — raw natural language chat prompts and structured JSON are visible.
  - Structured bodies (role + certification + work_signals from Call agent / `azd ai agent invoke`): full rich stack (Orchestrator + 5 specialists + real RAG + FabricIQ + Critic + adjustment that mutates the plan). The orchestrator itself is an explicit iteration + critic loop with maker/checker sub-agents.
  - Natural language / Chat tab (`{"messages": [...]}`): Extracts the user message → lightweight intent parser (role, target cert, time constraints) → runs the *full* multi-agent pipeline (now with optional persistent state + explicit skill loading per loop engineering) → returns a beautifully formatted Markdown study plan (with gaps, adjustment, next milestones, suggested actions) that renders nicely in the Playground chat. Your existing specialists, RAG citations, FabricIQ, Critic and LLM judge all run unchanged. The startup demo still provides the rich [1]-[7] logs.
  - **Loop engineering application**: The inner certification loops (orchestrator iterations + critic verifier + sub-specialists + adjustment that mutates) are being enhanced with explicit state resumption (multi-turn learner plans don't cold-start), loadable skills (e.g. `certification_skill.md` for persistent domain principles/maker-checker rules/monitoring signals), and clearer sub-agent maker/checker separation. The outer improvement loop for the agent's code and these inner loops is the `hosted-agent-dev-loop` skill (parallel implementer + reviewers: general/security/tests/hosted-deployment, using state via LOOP_ID files, already set up with composer 2.5 for the reviewer composition). Real portal usage (chat prompts, returned plans, feasibility scores, RAG citations from logs) becomes high-signal input to that dev loop.
- Environment variables (PROJECT_ENDPOINT, MODEL_DEPLOYMENT_NAME + AZURE_AI_ alias, EMBEDDING_*, SEARCH_*, RUN_DEMO_ON_START) are injected from azd env + agent.yaml (azd is single source; no hardcodes).
- For full "responses" protocol support (proper invocation of the Orchestrator + specialists with citations/grounding in every call), the `readiness_server.py` is a minimal HTTP shim. Upgrade it to a full protocol handler (see comments in Dockerfile and agent.yaml for agent-framework-foundry-hosting or custom responses server) if invoke/playground calls don't yet exercise the full multi-agent logic.
- Real RAG (hybrid/vector) requires the index populated (see below).

### Troubleshooting: "Agent not found" (or 404) when clicking the Playground URL from azd / deploy output
The URL generated by `azd ai agent show` and deploy often embeds the azd-tracked *resource* project path (e.g. `rg-creative-app-02-dev` / `ai-project-creative-app-02-dev` + `/build/agents/.../build?version=N`).

If you have overridden `AZURE_AI_PROJECT_ENDPOINT` (via `azd env set`) to point at a different project (your **ProjectCert** on the `projectcert-resource` account), that deep link resolves in the wrong UI context and shows "Agent not found. The agent you're looking for might have been deleted or is no longer available."

**The agent is active** (confirmed by `azd ai agent show certifyforge-agents` showing Status: active, version 4+, responses endpoint, etc.). The backend registration succeeded; only the generated web link is confused by the mixed azd-dev vs manual-ProjectCert setup that has existed throughout this project.

**Fix / workaround (always works):**
1. In https://ai.azure.com (or the Foundry portal), locate the project selector / header and switch to the project whose endpoint is your `AZURE_AI_PROJECT_ENDPOINT` value (look for **ProjectCert** or the full URL containing `projectcert-resource.services.ai.azure.com/api/projects/ProjectCert`).
2. Once inside *that* project, go to **Build > Agents** (or the Agents list in the sidebar).
3. Find `certifyforge-agents` in the list and open it.
4. Use the Playground/Chat/Call tabs *inside* the agent page.

If it still doesn't appear after switching projects:
- Wait 30-60s after deploy and refresh.
- In the portal agent page (if visible), look for a **Publish** button (top right) and use it to sync the definition from your local `agent.yaml`.
- Re-run `azd deploy --service certifyforge-agents` (or `azd ai agent show` to confirm active).
- As a last resort, the agent is fully usable via the CLI invoke above and the raw responses endpoint from `azd ai agent show` (no web UI needed to validate the full stack).

This mismatch is why the docs and hardening pass emphasize using `azd ai agent invoke` + manual navigation to the ProjectCert project for the web Playground.

See the top-level PDF for the full architecture.

## Current Status

This is the fresh start. We are following the PDF roadmap:
- Phase 0–1: Structure + synthetic data
- Phase 2+: Grounding layers + agents + Critic
- Hosted deployment: Complete via `azure.ai.agent` (container with readiness, active in ProjectCert, tested via invoke/playground)

See the top-level PDF (`Reasoning_Agents__Multi-Agent_Architecture__Approach.pdf`) for full details.

**MCP + Architecture PNG Alignment (per starter guidelines):** The implementation (Orchestrator planner + 5 specialists + explicit Critic loop + LLM adjust that mutates + FabricIQ ontology + real RAG + state/skills + traces) directly maps the grounded multi-step flow from reasoning-agents-architecture.png / reasoning-agents-challenge-architecture.png (https://github.com/carlotta94c/agentsleague/starter-kits/2-reasoning-agents): plan → reason with ontology/RAG (FabricIQ + FoundryIQ) → act via 5 specialists → critic/self-reflect/verifier loop → adjust (post-critic mutates plan) + state/skills for memory + observable traces/logs/portal Chat&Call parity. Matches "grounded multi-step reasoning agents" track starter (cert prep scenario, planner-executor + critic patterns). Reasoning is grounded (Fabric IQ + Azure AI Search RAG); per MCP guidelines (https://github.com/microsoftdocs/mcp and https://learn.microsoft.com/en-us/training/support/mcp) can be extended w/ Microsoft Learn MCP Server (`https://learn.microsoft.com/api/mcp`; tools `microsoft_docs_search`/`fetch`/`code_sample_search`) for live official MS cert docs/samples to eliminate hallucinations. Suggest future `/plugin` or MCP client integration. See root README + HACKATHON_PORTAL_DEMO_GUIDE.md for detailed mapping + checklist. (Smallest doc updates; demo prints updated for labels.)

**For the latest overall architecture diagram (Mermaid + ASCII), provisioned Azure resources (including explicit note on Microsoft Fabric / FabricIQ), and current hosted status, see the root [README.md](../../README.md) in CREATIVE_APP_02/.**
