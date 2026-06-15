# CREATIVE_APP_02 Hosted Agent Review Scope

Use this checklist when reviewing the `certifyforge-agents` hosted agent implementation.

## Primary code paths

- `src/certifyforge_agents/readiness_server.py` — responses protocol shim, chat fast-path vs structured invoke, always-200 envelope
- `src/certifyforge_agents/entrypoint.sh` — background demo + readiness server startup
- `src/certifyforge_agents/orchestrator/simple_orchestrator.py` — planner, critic loop, post-critic adjustment
- `src/certifyforge_agents/grounding/foundry_llm.py` — Foundry LLM + embeddings, azd-first env resolution
- `src/certifyforge_agents/grounding/azure_search_foundry_iq.py` — hybrid RAG, key auth fallback
- `src/certifyforge_agents/grounding/fabric_iq.py` — bundled semantic rules, feasibility, gaps
- `src/certifyforge_agents/agents/` — five specialists + citation faithfulness
- `src/certifyforge_agents/evaluation/` — critic / verifier
- `src/certifyforge_agents/demo_orchestration.py` — local observable demo (must match hosted startup logs)
- `src/certifyforge_agents/Dockerfile` + `agent.yaml` — container + hosted agent definition
- `azure.yaml` + `infra/` — azd provisioning, env substitution, RBAC
- `scripts/populate_search_index.py` — vector index population

## Hosted-agent-specific risks

- Chat vs Call tab payload routing (non-structured must not run full orchestration)
- Readiness probe must return 200 before platform marks agent healthy
- azd `${VAR}` substitution vs hardcoded/manual ProjectCert endpoint mismatches
- Embedding deployment resolution (never silent ada-002 default when azd active)
- Container data paths (`/app/certifyforge_agents/data`) vs local dev paths
- Admin key injection for search vs MI RBAC propagation delays
- Uncaught exceptions in POST handler causing "processing your request" portal errors
- Response envelope shape for Chat renderer (`choices`, `output`, `message.content`)
- `RUN_DEMO_ON_START` blocking or delaying readiness
- Secrets in logs, error bodies, or committed config artifacts

## Architecture alignment

- Orchestrator + 5 specialists + explicit critic (per architecture PDF)
- Foundry IQ = LLM + Azure AI Search RAG
- Fabric IQ = internal Python rules over bundled data (not Microsoft Fabric platform)
- Real citations only (faithful `_match_citation`, no hallucinated sources)
- Post-critic adjustment must mutate actual study plan milestones/hours

## Test expectations

- Local: `demo_orchestration.py --seed 0` shows [1]-[7], real RAG when index populated
- Hosted: `azd ai agent invoke certifyforge-agents` with structured JSON payload
- Chat tab: fast path reply without 20-40s spinner
- Call tab / invoke: full rich orchestration result