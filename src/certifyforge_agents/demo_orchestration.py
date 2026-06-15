r"""
CertifyForge Reasoning Agents - Live Architecture Demo

Usage (PowerShell, this Windows + venv setup):

    # Preferred: cd into the package dir and run the project's venv python directly
    cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
    ..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0

    # Fully random every time (no seed)
    ..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0

    # Different random request each run, but reproducible factory behavior
    ..\..\venv\Scripts\python.exe demo_orchestration.py --seed 42 --random-request

    # Using the module form (from the src/ directory)
    cd C:\Users\abdul\CREATIVE_APP_02\src
    $env:PYTHONPATH='.' ; ..\venv\Scripts\python.exe -m certifyforge_agents.demo_orchestration --seed 123

    # Or (if the venv python is on your PATH):
    python -m certifyforge_agents.demo_orchestration --seed 0
"""

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path

# ------------------------------------------------------------------
# Robust bootstrap so this file can be run *directly* as a script
# (common when using the project venv python).
#
# Supported ways (PowerShell examples on this repo):
#
#   # From inside the package directory (recommended for direct runs):
#   cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
#   ..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0
#
#   # Or from the src/ directory using the module entrypoint:
#   cd C:\Users\abdul\CREATIVE_APP_02\src
#   $env:PYTHONPATH='.' ; ..\venv\Scripts\python.exe -m certifyforge_agents.demo_orchestration --seed 0
#
# The code below makes the first style work reliably even though we use
# relative imports (from .orchestrator etc.). It puts the *parent* of the
# package on sys.path and sets __package__ so "from .xxx" succeeds.
# ------------------------------------------------------------------
if __name__ == "__main__" and (not __package__ or __package__ == ""):
    _this = Path(__file__).resolve()
    _pkg_dir = _this.parent  # .../certifyforge_agents
    _src_parent = (
        _pkg_dir.parent
    )  # .../src  (the directory that *contains* the top-level package folder)

    if str(_src_parent) not in sys.path:
        sys.path.insert(0, str(_src_parent))

    __package__ = "certifyforge_agents"

# ------------------------------------------------------------------
# Windows console robustness: force UTF-8 output so emojis / special chars
# (if any remain in future prints) don't crash on cp1252 consoles.
# Users can also do  $env:PYTHONIOENCODING='utf-8' before the python invocation.
# ------------------------------------------------------------------
try:
    import sys as _sys
    import os as _os

    if _sys.platform.startswith("win"):
        _os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        for _s in (_sys.stdout, _sys.stderr):
            if hasattr(_s, "reconfigure"):
                try:
                    _s.reconfigure(encoding="utf-8", errors="replace")
                except Exception:
                    pass
except Exception:
    pass

from .orchestrator.simple_orchestrator import SimpleOrchestrator
from .evaluation.simple_critic import SimpleCriticVerifier
from .grounding.foundry_iq import LocalFoundryIQ
from .grounding.azure_search_foundry_iq import _get_azd_value
from .grounding.foundry_llm import get_foundry_llm_client


def _get_azure_search_foundry_iq(
    search_service=None, index_name=None, endpoint=None, llm_client=None
):
    # Use the lazy getter from the package __init__
    from . import get_azure_search_foundry_iq
    from .grounding.azure_search_foundry_iq import get_azure_search_config

    cfg = get_azure_search_config()
    admin_key = cfg["admin_key"] or os.environ.get("AZURE_SEARCH_ADMIN_KEY")
    return get_azure_search_foundry_iq(
        search_service_name=search_service,
        index_name=index_name,
        endpoint=endpoint,
        admin_key=admin_key,
        llm_client=llm_client,
    )


from .data.factory import SyntheticDataFactory

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
# Quiet the verbose Azure SDK per-request URL logs (we already print the effective endpoint at construction).
# You will still see them if you set AZURE_LOG_LEVEL=DEBUG or similar.
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(
    logging.WARNING
)
# Quiet OpenAI SDK HTTP request logs (we already surface real calls via the [LLM] init and synthesis notes).
# The raw requests are still visible if you set logging level higher.
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def get_foundry_iq(llm_client=None):
    """
    Returns the appropriate Foundry IQ implementation.
    - If AZURE_AI_SEARCH_SERVICE_NAME present in azd env (or manual) → use real Azure AI Search (real grounding + citations)
    - Otherwise → use local stub (development, loads from local markdown guides)
    """
    # Central resolver does azd-first + stale ENDPOINT pop + build-from-service.
    from .grounding.azure_search_foundry_iq import get_azure_search_config

    cfg = get_azure_search_config()
    search_service = cfg["search_service_name"]
    index_name = cfg["index_name"]
    endpoint_azd = cfg["endpoint"]

    if search_service or endpoint_azd:
        label = search_service or endpoint_azd
        print(
            f"[Grounding] Using REAL Azure AI Search grounding: {label} / {index_name}"
        )
        # Pass endpoint only if azd supplied a full ENDPOINT value; else None so constructor builds from service.
        return _get_azure_search_foundry_iq(
            search_service,
            index_name,
            endpoint=endpoint_azd if endpoint_azd else None,
            llm_client=llm_client,
        )
    else:
        print("[Grounding] Using LocalFoundryIQ (development mode - local guides only)")
        return LocalFoundryIQ()


def parse_args():
    parser = argparse.ArgumentParser(description="CertifyForge Reasoning Agents Demo")
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (use 0 or negative for fully random behavior)",
    )
    parser.add_argument(
        "--random-request",
        action="store_true",
        help="Randomize the input request even when using a fixed seed",
    )
    return parser.parse_args()


async def run_demo_orchestration(
    request: dict | None = None,
    seed: int = 42,
    random_request: bool = False,
) -> dict:
    """Testable orchestration entry using offline LocalFoundryIQ (no live Azure required)."""
    from .grounding.fabric_iq import FabricIQ

    fabric_iq = FabricIQ()
    foundry_iq = LocalFoundryIQ()
    critic = SimpleCriticVerifier(fabric_iq=fabric_iq)
    internal_seed = seed if seed > 0 else None

    if request is None:
        if random_request or seed <= 0:
            available_roles = fabric_iq.get_available_roles() or ["Cloud Engineer"]
            available_certs = fabric_iq.get_all_certification_ids() or ["AZ-204"]
            request = {
                "role": random.choice(available_roles),
                "certification": random.choice(available_certs),
                "work_signals": {
                    "meeting_hours_per_week": random.randint(8, 28),
                    "focus_hours_per_week": random.randint(6, 20),
                    "preferred_learning_slot": random.choice(
                        ["Morning", "Afternoon", "Evening"]
                    ),
                },
            }
        else:
            request = {
                "role": "Cloud Engineer",
                "certification": "AZ-204",
                "work_signals": {
                    "meeting_hours_per_week": 22,
                    "focus_hours_per_week": 10,
                    "preferred_learning_slot": "Morning",
                },
            }

    # Wire state_path + skill_path (harden recent support for multi-turn stateful reasoning + domain skill).
    # Enables demo of resume (e.g. prior gaps closed) across "turns"; matches hosted behavior.
    # Use same alnum sanitize as readiness_server per-role/cert for demo/hosted state filename parity.
    import re as _re_demo

    _r = (
        _re_demo.sub(r"[^A-Za-z0-9]", "", request.get("role", "CloudEngineer"))[:16]
        or "demo"
    )
    _c = (
        _re_demo.sub(r"[^A-Za-z0-9]", "", request.get("certification", "AZ204"))[:8]
        or "AZ204"
    )
    state_path = f"/tmp/certifyforge_{_c}_{_r}_state.json"
    skill_path = str(
        Path(__file__).resolve().parent / "data" / "certification_skill.md"
    )
    # For mutate parity (review Issue 5): attempt real llm so --seed 0 local demo exercises LLM adjust + trace flag + milestone mutation like hosted/main (graceful None if offline).
    llm_client = None
    try:
        from .grounding.foundry_llm import get_foundry_llm_client

        llm_client = get_foundry_llm_client()
    except Exception:
        pass
    orchestrator = SimpleOrchestrator(
        critic=critic,
        fabric_iq=fabric_iq,
        foundry_iq=foundry_iq,
        llm_client=llm_client,
        seed=internal_seed,
        state_path=state_path,
        skill_path=skill_path,
    )
    return await orchestrator.handle_request(request)


async def main():
    args = parse_args()

    print("=" * 75)
    print("CERTIFYFORGE REASONING AGENTS - LIVE ARCHITECTURE DEMO")
    print("=" * 75)

    # ============================================================
    # 0. RANDOMNESS CONTROL
    # ============================================================
    if args.seed > 0:
        random.seed(args.seed)
        print(f"[Randomness] Using fixed seed = {args.seed}")
    else:
        print("[Randomness] Using fully random behavior (no seed)")

    # ============================================================
    # 1. GROUNDING LAYERS SETUP
    # ============================================================
    print("\n[1] GROUNDING LAYERS")

    # Create LLM first (provides embeddings for vector search in grounding + synthesis for specialists)
    foundry_llm = None
    try:
        foundry_llm = get_foundry_llm_client()
        print(
            f"   Foundry LLM : {foundry_llm.name()}  (real model calls for synthesis in specialists)"
        )
    except Exception as ex:
        print(
            f"   Foundry LLM : disabled ({ex})  (configure AZURE_AI_PROJECT_ENDPOINT + AZURE_AI_MODEL_DEPLOYMENT_NAME for real LLM)"
        )

    foundry_iq = get_foundry_iq(llm_client=foundry_llm)

    from .grounding.fabric_iq import FabricIQ

    fabric_iq = FabricIQ()  # Real semantic layer (Fabric IQ)

    print(
        f"   Foundry IQ : {foundry_iq.name()}  (wired into specialists for citations)"
    )
    print(
        "   Fabric IQ  : Active (semantic ontology + rules + feasibility + gaps + prereqs)"
    )
    if foundry_llm:
        print(
            "   LLM synthesis      : Active (specialists use real model + citations for generated content)"
        )

    # Show the actual resolved Azure endpoints (they come from azd env after provision,
    # are injected via agent.yaml environment_variables for containers, and read here via os.environ)
    # You set them with `azd env set AZURE_AI_PROJECT_ENDPOINT "..."` (no need to hardcode in files).
    # The _get_azd_value helper allows seeing them even when running the demo directly (not via azd shell).
    project_ep = (
        _get_azd_value("AZURE_AI_PROJECT_ENDPOINT")
        or _get_azd_value("FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
    )
    if project_ep:
        print(f"   Azure AI Project Endpoint : {project_ep}")
    project_key = _get_azd_value("AZURE_AI_PROJECT_KEY") or os.environ.get(
        "AZURE_AI_PROJECT_KEY"
    )
    if project_key:
        print(f"   Azure AI Project Key      : {project_key[:8]}... (masked)")
    model_dep = (
        _get_azd_value("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        or _get_azd_value("MODEL_DEPLOYMENT_NAME")
        or os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        or os.environ.get("MODEL_DEPLOYMENT_NAME")
    )
    if model_dep:
        print(f"   Model Deployment          : {model_dep}")
    embed_dep = _get_azd_value("AZURE_AI_EMBEDDING_DEPLOYMENT_NAME") or os.environ.get(
        "AZURE_AI_EMBEDDING_DEPLOYMENT_NAME"
    )
    if embed_dep:
        print(f"   Embedding Deployment      : {embed_dep}")
    aoai_ep = _get_azd_value("AZURE_OPENAI_ENDPOINT") or os.environ.get(
        "AZURE_OPENAI_ENDPOINT"
    )
    if foundry_llm and getattr(foundry_llm, "aoai_endpoint", None):
        print(
            f"   Account OpenAI (embeddings): {foundry_llm.aoai_endpoint}  (derived or from azd)"
        )
    elif aoai_ep:
        print(f"   Azure OpenAI Endpoint     : {aoai_ep}")
    search_svc = _get_azd_value("AZURE_AI_SEARCH_SERVICE_NAME") or os.environ.get(
        "AZURE_AI_SEARCH_SERVICE_NAME"
    )
    search_ep = (
        _get_azd_value("AZURE_AI_SEARCH_ENDPOINT")
        or _get_azd_value("AZURE_SEARCH_SERVICE_ENDPOINT")
        or os.environ.get("AZURE_AI_SEARCH_ENDPOINT")
        or os.environ.get("AZURE_SEARCH_SERVICE_ENDPOINT")
    )
    if search_svc or search_ep:
        print(f"   Azure AI Search           : {search_svc or search_ep}")

    # ============================================================
    # 2. REQUEST
    # ============================================================
    if args.random_request or args.seed < 0:
        # Generate a randomized request, but only use roles that have alignment data in Fabric IQ
        available_roles = fabric_iq.get_available_roles() or [
            "Cloud Engineer",
            "DevOps Engineer",
            "Data Engineer",
        ]
        available_certs = fabric_iq.get_all_certification_ids() or [
            "AZ-204",
            "AZ-400",
            "DP-203",
            "AZ-305",
        ]

        role = random.choice(available_roles)
        cert = random.choice(available_certs)

        request = {
            "role": role,
            "certification": cert,
            "work_signals": {
                "meeting_hours_per_week": random.randint(8, 28),
                "focus_hours_per_week": random.randint(6, 20),
                "preferred_learning_slot": random.choice(
                    ["Morning", "Afternoon", "Evening"]
                ),
            },
        }
        print("\n[2] USER REQUEST (randomized)")
    else:
        # Hackathon Reasoning Agents showcase (used for --seed 0 and positive seeds): complex real-world query mapped to AZ-400 for DevOps (high meetings, limited focus).
        # Exercises: NL intent (in server), role-align (low for some), prereqs, Fabric capacity for high-meet/low-focus, RAG, full critic+adjust mutating plan, stateful resume, rich trace.
        request = {
            "role": "DevOps Engineer",
            "certification": "AZ-400",
            "work_signals": {
                "meeting_hours_per_week": 30,
                "focus_hours_per_week": 6,
                "preferred_learning_slot": "Evening",
            },
        }
        print(
            "\n[2] USER REQUEST (fixed for reproducibility --seed 0 hackathon demo: AZ-400 DevOps high-meetings limited-focus)"
        )

    print(f"   Role: {request['role']}")
    print(f"   Certification: {request['certification']}")
    print(f"   Work Context: {request['work_signals']}")

    # ============================================================
    # 3. FABRIC IQ SEMANTIC ANALYSIS (before orchestration)
    # ============================================================
    print("\n[3] FABRIC IQ PRE-ORCHESTRATION ANALYSIS")
    alignment = fabric_iq.role_certification_alignment(
        request["role"], request["certification"]
    )
    print(
        f"   Role-Cert Alignment: {alignment.get('alignment_score', 0):.2f} "
        f"(primary={alignment.get('is_primary', False)}, recommended={alignment.get('recommended', False)})"
    )

    cert_reqs = fabric_iq.get_certification_requirements(request["certification"])
    if cert_reqs:
        print(f"   {request['certification']} Requirements:")
        print(f"     - Recommended hours : {cert_reqs.recommended_hours}")
        print(f"     - Pass threshold    : {cert_reqs.pass_threshold}")
        print(f"     - Difficulty        : {cert_reqs.difficulty_level}")

    # ============================================================
    # 4. ORCHESTRATION WITH CRITIC (using Fabric IQ)
    # ============================================================
    print(
        "\n[4] ORCHESTRATION + CRITIC/VERIFIER LOOP (plan → reason(ontology/RAG) → act(5 specialists) → critic/self-reflect → adjust)"
    )

    critic = SimpleCriticVerifier(fabric_iq=fabric_iq)

    # Determine the seed for internal components (learners, gaps, feasibility adjustments, etc.)
    # - Positive seed → fully reproducible run (including printed gaps, critic details, etc.)
    # - None (from --seed 0 or negative) → truly varying behavior on every run for the "live demo" feel.
    internal_seed = args.seed if args.seed > 0 else None
    # Wire state_path + skill_path for persistent multi-turn + skill-loaded reasoning (see run_demo too).
    # For --seed 0 hackathon demo: produces state resume logs + reasoning_trace in output.
    # Use same alnum sanitize as readiness_server per-role/cert for demo/hosted state filename parity.
    import re as _re_demo

    _r = (
        _re_demo.sub(r"[^A-Za-z0-9]", "", request.get("role", "CloudEngineer"))[:16]
        or "demo"
    )
    _c = (
        _re_demo.sub(r"[^A-Za-z0-9]", "", request.get("certification", "AZ204"))[:8]
        or "AZ204"
    )
    state_path = f"/tmp/certifyforge_{_c}_{_r}_state.json"
    skill_path = str(
        Path(__file__).resolve().parent / "data" / "certification_skill.md"
    )
    orchestrator = SimpleOrchestrator(
        critic=critic,
        fabric_iq=fabric_iq,
        foundry_iq=foundry_iq,
        llm_client=foundry_llm,
        seed=internal_seed,
        state_path=state_path,
        skill_path=skill_path,
    )

    result = await orchestrator.handle_request(request)

    print(f"\n   Final Status   : {result['status']}")
    print(f"   Iterations     : {result['iterations']}")

    print("\n   Generated Plan:")
    for i, step in enumerate(result["plan"], 1):
        print(f"     {i}. {step['step']}: {step['description']}")

    # Polish: surface LLM token usage from last call + cumulative (via the shared foundry_llm instance)
    if foundry_llm and getattr(foundry_llm, "last_usage", None):
        u = foundry_llm.last_usage
        tot = getattr(foundry_llm, "total_usage", {}) or {}
        print(
            f"   LLM usage (last call): prompt={u.get('prompt_tokens', 0)}, completion={u.get('completion_tokens', 0)}, total={u.get('total_tokens', 0)}"
        )
        if tot.get("total_tokens", 0) > u.get("total_tokens", 0):
            print(
                f"   LLM usage (cumulative): prompt={tot.get('prompt_tokens', 0)}, completion={tot.get('completion_tokens', 0)}, total={tot.get('total_tokens', 0)}"
            )

    if result.get("llm_personalized_adjustment"):
        print(
            f"\n   LLM Personalized Adjustment: {result['llm_personalized_adjustment']}"
        )

    # ============================================================
    # 5. DETAILED RESULTS + CRITIC REASONING
    # ============================================================
    print(
        "\n[5] DETAILED RESULTS + CRITIC REASONING (bespoke multi-step with Fabric IQ ontology facts + critic loop — matches the rich portal MD judges will see)"
    )

    for step_name, step_data in result["results"].items():
        agent_name = step_data.get("agent", step_name)
        status = step_data.get("status", "unknown")
        output = step_data.get("output", {})
        verification = step_data.get("verification", {})

        print(f"\n   > {step_name.upper()} ({agent_name})")
        print(f"     Status: {status}")

        if verification:
            accepted = verification.get(
                "accepted",
                verification.get("is_feasible", verification.get("is_valid", "N/A")),
            )
            confidence = verification.get("confidence", "N/A")
            print(
                f"     Critic Decision : {'ACCEPTED' if accepted else 'REJECTED'} (confidence={confidence})"
            )

            if verification.get("issues"):
                print(f"     Critic Issues   : {verification['issues']}")
            if verification.get("suggestions"):
                print(f"     Suggestions     : {verification['suggestions']}")

            # Surface rich Fabric IQ fields from verification when present (feasibility, gaps, etc)
            for rich_key in (
                "estimated_weeks",
                "available_focus_per_week",
                "capacity_utilization",
                "risk_level",
                "gap_penalty",
                "feasibility_score",
            ):
                if rich_key in verification and verification[rich_key] is not None:
                    print(
                        f"     {rich_key.replace('_', ' ').title()}: {verification[rich_key]}"
                    )

        # Show key output fields + deeper Fabric IQ internals
        if isinstance(output, dict):
            if "study_plan" in output:
                sp = output["study_plan"]
                print(f"     Total Hours     : {sp.get('total_hours')}")
                # Feasibility Score already printed from critic verification (enriched Fabric calc); avoid dup/conflict here
                # Show sample milestones (especially richer ones from LLM)
                if output.get("milestones"):
                    m0 = output["milestones"][0] if output["milestones"] else None
                    if m0:
                        print(
                            f"     Sample milestone: Week {m0.get('week')}: {str(m0.get('topic', ''))[:60]}..."
                        )
                    # If adjustment affected the plan (appended reinforcement), show the last milestone for visibility
                    if output.get("llm_adjustment") and len(output["milestones"]) > 1:
                        m_last = output["milestones"][-1]
                        print(
                            f"     Adjusted milestone: Week {m_last.get('week')}: {str(m_last.get('topic', ''))[:60]}..."
                        )
                if (
                    output.get("milestones")
                    and len(str(output.get("milestones", [{}])[0].get("topic", "")))
                    > 20
                    or output.get("llm_synthesized")
                ):
                    print("     (LLM-synthesized milestones from learning path)")
                if output.get("llm_adjustment"):
                    print(
                        f"     LLM Adjustment : {str(output.get('llm_adjustment'))[:100]}..."
                    )
            if "semantic_analysis" in output:
                sa = output["semantic_analysis"]
                print(f"     Alignment Score : {sa.get('alignment_score')}")
                print(f"     Capacity Risk   : {sa.get('capacity_risk')}")
                if sa.get("gap_count") is not None:
                    print(f"     Skill Gap Count : {sa.get('gap_count')}")
                if sa.get("time_to_readiness_weeks") is not None:
                    print(
                        f"     Time to Readiness: ~{sa.get('time_to_readiness_weeks')} weeks"
                    )
            if "assessment" in output:
                ass = output["assessment"]
                print(
                    f"     Readiness Score : {ass.get('readiness_score')} | Passed: {ass.get('passed')}"
                )
                questions = ass.get("questions", [])
                if questions:
                    q0 = questions[0]
                    # Show actual generated question when LLM synthesis used
                    if q0.get("question"):
                        qtext = str(q0.get("question"))[:120]
                        print(f"     Sample question : {qtext}...")
                    if q0.get("citation"):
                        print(f"     Sample citation : {q0.get('citation')[:80]}...")
                    # Show LLM indicator only for true LLM-synthesized (flag) or non-obvious fallback templates
                    _qtext0 = str(q0.get("question", ""))
                    if ass.get("degraded"):
                        print(
                            "     (Degraded — no cert-tagged index content for assessment questions)"
                        )
                    elif output.get("llm_synthesized"):
                        print("     (LLM-synthesized questions from grounded content)")

            if "learning_path" in output:
                lp = output["learning_path"]
                modules = lp.get("modules", [])
                if modules:
                    m0 = modules[0]
                    # Show richer LLM-generated fields when present
                    title = m0.get("title") or m0.get("source", "")
                    print(f"     Sample module   : {str(title)[:80]}...")
                    if m0.get("description"):
                        desc = str(m0.get("description"))[:100]
                        print(f"     Description     : {desc}...")
                    if m0.get("citation") or m0.get("source"):
                        cit = m0.get("citation") or m0.get("source")
                        print(f"     Sample citation : {str(cit)[:80]}...")
                    if lp.get("llm_synthesized"):
                        print("     (LLM-synthesized learning path from RAG + model)")
                    elif lp.get("degraded"):
                        print(
                            f"     (Local guide fallback — {lp.get('certification', 'cert')}_Guide.md; no cert-tagged index chunks)"
                        )

            # New: print richer details emitted by generator using build/estimate
            if "fabric_iq_details" in output:
                fid = output["fabric_iq_details"]
                if fid.get("gaps"):
                    print(f"     Fabric Gaps     : {fid['gaps']}")
                if fid.get("time_estimate"):
                    print(f"     Fabric Time Est : {fid['time_estimate']}")
            # Show outputs from Fabric-driven orchestration steps (prereqs, alignment)
            if output.get("step") == "prerequisite_check":
                print(f"     Prerequisites   : {output.get('prerequisites')}")
                print(f"     Missing (learner): {output.get('missing_for_learner')}")
                print(f"     Note            : {output.get('fabric_iq_note')}")
            if output.get("step") == "role_alignment_check":
                al = output.get("alignment", {})
                print(
                    f"     Alignment       : score={al.get('alignment_score')}, recommended={al.get('recommended')}"
                )
                print(f"     Warning Issued  : {output.get('warning')}")
                print(f"     Note            : {output.get('fabric_iq_note')}")

    # Simple LLM-as-judge evaluation (step 4) - rates the final plan using the same Foundry LLM + grounding context
    if foundry_llm:
        try:
            sp = (
                (result.get("results", {}).get("study_plan", {}) or {})
                .get("output", {})
                .get("study_plan", {})
            )
            judge_obj = foundry_llm.generate_structured(
                "You are a strict but fair Azure certification evaluator. Return ONLY a JSON object with keys: score (int 1-10), justification (one short sentence).",
                f"Request: role={request.get('role')}, cert={request.get('certification')}. Generated plan total_hours={sp.get('total_hours')}, feasibility={sp.get('feasibility_score')}. Rate relevance + practicality for the role.",
                temperature=0.3,
                max_tokens=80,
            )
            if isinstance(judge_obj, dict):
                sc = judge_obj.get("score", "?")
                just = judge_obj.get("justification", str(judge_obj))
                print(f"\n   LLM Judge (plan quality): Score: {sc}")
                print(f"     Justification: {just}")
            else:
                print(f"\n   LLM Judge (plan quality): {judge_obj}")
        except Exception:
            pass
        # Re-surface cumulative after judge (which also called the LLM)
        if foundry_llm and getattr(foundry_llm, "total_usage", None):
            tot = foundry_llm.total_usage
            if tot.get("total_tokens"):
                print(
                    f"   LLM usage (final cumulative incl. judge): total={tot.get('total_tokens', 0)} tokens"
                )

    print("\n" + "=" * 75)
    print("DEMO COMPLETE")
    print("Key Fabric IQ + Critic decisions are now visible in the flow above.")
    print("=" * 75)

    # ============================================================
    # STATEFUL MULTI-TURN DEMO (loop engineering: state_path resume for hackathon)
    # ============================================================
    # Simulates portal multi-chat sessions: second turn resumes prior_state (last plan/gaps/adjust),
    # can reflect "progress" (e.g. closed gaps -> adjusted plan). Visible in logs + reasoning_trace["state_resumed_from"].
    print("\n[STATE] MULTI-TURN STATE RESUME DEMO (persistent across turns/sessions)")
    try:
        follow_up = dict(request)
        follow_up["work_signals"] = {
            **follow_up.get("work_signals", {}),
            "focus_hours_per_week": 8,
        }  # e.g. user reports more focus time now
        # prior_state passed explicitly + state file has last_ from first turn
        prior = result.get("reasoning_trace") or {"last_plan": result.get("plan")}
        result2 = await orchestrator.handle_request(follow_up, prior_state=prior)
        print(
            f"   Turn-2 status: {result2.get('status')} iterations={result2.get('iterations')}"
        )
        tr2 = result2.get("reasoning_trace", {})
        print(
            f"   Turn-2 state_resumed_from: {tr2.get('state_resumed_from')} skill_used: {tr2.get('skill_context_used')}"
        )
        print(f"   Turn-2 plan steps: {tr2.get('plan_steps')}")
        print(
            "   (Plan evolves; critic/adjust can build on prior progress. Matches hosted Chat multi-turn.)"
        )
    except Exception as _ex:
        print(f"   (state demo skipped: {_ex})")

    # ============================================================
    # 6. BONUS: Direct Fabric IQ Queries (to show its reasoning power)
    # ============================================================
    print("\n[6] DIRECT FABRIC IQ SEMANTIC QUERIES (for transparency)")
    print("-" * 75)

    # Use the factory for realistic demo data in the bonus section
    demo_factory = SyntheticDataFactory(seed=args.seed if args.seed > 0 else None)

    demo_learner = demo_factory.create_learner(
        role=request["role"], certification=request["certification"]
    )

    # Skill gaps using real factory-generated learner
    gaps = fabric_iq.build_skill_gap_analysis(demo_learner, request["certification"])
    print(f"   Skill Gaps for generated learner ({demo_learner.learner_id}):")
    if gaps:
        for g in gaps[:3]:
            print(
                f"     - {g.skill}: current={g.current_level}, required={g.required_level}, priority={g.priority}"
            )
    else:
        print("     No significant skill gaps detected.")

    # Time to readiness using the generated learner
    time_est = fabric_iq.estimate_time_to_readiness(
        demo_learner, request["certification"]
    )
    print(
        f"\n   Estimated time to readiness for {demo_learner.learner_id}: ~{time_est.get('estimated_weeks')} weeks"
    )

    # Full prerequisite chain example
    prereqs = fabric_iq.get_full_prerequisite_chain("Azure Kubernetes Service")
    print(f"\n   Prerequisite chain for 'Azure Kubernetes Service': {prereqs}")

    print("\n" + "=" * 75)
    print("This demonstrates how Fabric IQ provides rich semantic reasoning")
    print("that the Orchestrator, Specialists, and Critic can all consult.")
    print("=" * 75)

    # ============================================================
    # 7. REAL GROUNDING DEMO (Azure AI Search) - when active
    # ============================================================
    if "Azure AI Search" in str(foundry_iq.name()):
        print("\n[7] REAL FOUNDRY IQ (AZURE AI SEARCH) - LIVE RETRIEVAL DEMO")
        print("-" * 75)
        try:
            # Force a real retrieve to prove end-to-end citations are coming from the cloud index
            cert = request["certification"]
            real_hits = await foundry_iq.retrieve_with_citations(
                f"key skills and best practices for {cert}",
                top_k=2,
                certification=cert,
            )
            if not real_hits:
                print(f"   No cert-tagged chunks for {cert} in the search index.")
                print(
                    f"   Orchestration used local {cert}_Guide.md fallback during [4]-[5]."
                )
                print(
                    f"   To enable index-backed RAG for {cert}: add the guide, then run:"
                )
                print("     python scripts\\populate_search_index.py")
            else:
                print(
                    f"   Retrieved {len(real_hits)} cert-tagged chunks from Azure AI Search:"
                )
                for i, hit in enumerate(real_hits, 1):
                    content_preview = str(hit.get("content", ""))[:160].replace(
                        "\n", " "
                    )
                    print(f"   [{i}] Citation: {hit.get('citation')}")
                    print(f"       Content : {content_preview}...")
                    print(f"       Score   : {hit.get('score')}")
                    if hit.get("vector_score") is not None:
                        print(f"       Vector similarity: {hit.get('vector_score')}")
                print(
                    "\n   [OK] This is real RAG grounding (cert-specific cited content from the index)."
                )
        except Exception as ex:
            print(f"   [WARN] Real retrieval attempt failed: {ex}")
            print(
                "      (Index may be empty — run the populate script, or check RBAC/endpoint.)"
            )
    else:
        print("\n[7] REAL GROUNDING")
        print(
            "   (Currently using LocalFoundryIQ stub. Set AZURE_AI_SEARCH_SERVICE_NAME"
        )
        print(
            "    and run scripts/populate_search_index.py to switch to real Azure AI Search RAG.)"
        )


if __name__ == "__main__":
    asyncio.run(main())
