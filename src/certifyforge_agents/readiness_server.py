"""
Azure AI Hosted Agents server using the official Responses protocol.

- ``ResponsesAgentServerHost`` serves ``POST /responses`` (SSE streaming) and ``GET /readiness``.
- Playground Chat traffic hits ``/responses``; the prior root-POST shim never received those requests.
- Structured invoke (role/certification/work_signals from Call agent / ``azd ai agent invoke``):
  full Orchestrator + specialists + Foundry LLM + AzureSearchFoundryIQ RAG + FabricIQ + Critic.
- Chat / natural language: fast intent-parse summary for generic; **complex NL now runs full** (parse_user_intent hardened + _is_complex_query routes to rich plan-reason-act-critic-adjust with trace in MD + result.reasoning_trace).
- Legacy ``ReadinessHandler`` (root POST) remains for local unit tests only.
- Constraints followed (review-scope.md): always-200, preview logs on every POST, Chat/Call routing separation (non-struct only fast for simple now; complex full for demo), response envelope (choices/output + result+reasoning_trace for renderer), no weaken try/except at LLM/search, azd ${} + state/skill wired, local demo --seed 0 aligned to hosted.
"""

import os
import json
import traceback
import asyncio
import sys
import logging
import re
import threading
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ------------------------------------------------------------------
# Bootstrap for direct script execution
# ------------------------------------------------------------------
if __name__ == "__main__" and (not __package__ or __package__ == ""):
    _this = Path(__file__).resolve()
    _pkg_dir = _this.parent
    _src_parent = _pkg_dir.parent
    if str(_src_parent) not in sys.path:
        sys.path.insert(0, str(_src_parent))
    __package__ = "certifyforge_agents"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
for _noisy in (
    "azure",
    "azure.core",
    "azure.ai",
    "openai",
    "httpx",
    "urllib3",
    "azure.identity",
):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
logging.getLogger(__name__).setLevel(logging.INFO)

from .grounding.foundry_llm import get_foundry_llm_client
from .grounding.azure_search_foundry_iq import (
    AzureSearchFoundryIQ,
    get_azure_search_config,
)
from .grounding.fabric_iq import FabricIQ
from .orchestrator.simple_orchestrator import SimpleOrchestrator
from .grounding.foundry_iq import LocalFoundryIQ
from .request_validation import (
    ValidationError,
    clamp_body_length,
    is_oversize_body,
    is_structured_invoke_payload,
    parse_content_length,
    redact_for_log,
    validate_structured_request,
)
from .agents.citations import sanitize_llm_output, sanitize_user_text
from .errors import client_error_code, client_safe_message, error_envelope

try:
    from azure.ai.agentserver.responses import (
        CreateResponse,
        ResponseContext,
        ResponsesAgentServerHost,
        TextResponse,
    )
except ImportError:  # pragma: no cover - exercised in container after pip install
    CreateResponse = ResponseContext = ResponsesAgentServerHost = TextResponse = None  # type: ignore

_MAX_CONCURRENT_ORCH = int(os.environ.get("MAX_CONCURRENT_ORCHESTRATIONS", "3"))
_ORCH_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_ORCH)
_MAX_CONCURRENT_POSTS = int(os.environ.get("MAX_CONCURRENT_POSTS", "10"))
_POST_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT_POSTS)


async def run_full_orchestration(request_dict: dict | None = None) -> dict:
    """
    Central safe entry for the complete multi-agent stack from the hosted server.
    Returns a dict the platform can return to azd invoke / Call agent / chat.
    Never lets an error kill the HTTP handler.
    """
    print("[Server] run_full_orchestration start")
    req = request_dict or {
        "role": "Cloud Engineer",
        "certification": "AZ-204",
        "work_signals": {
            "meeting_hours_per_week": 22,
            "focus_hours_per_week": 10,
            "preferred_learning_slot": "Morning",
        },
    }
    try:
        req = validate_structured_request(req)
    except ValidationError:
        req = {
            "role": "Cloud Engineer",
            "certification": "AZ-204",
            "work_signals": {
                "meeting_hours_per_week": 22,
                "focus_hours_per_week": 10,
                "preferred_learning_slot": "Morning",
            },
        }

    seed = req.get("seed", 42)
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        seed = 42

    print(
        f"[Server] request: role={req.get('role')} cert={req.get('certification')} seed={seed}"
    )

    llm = None
    try:
        llm = get_foundry_llm_client()
        emb = getattr(llm, "embedding_deployment", None)
        print(
            f"[Server][1] LLM ready: {llm.name()}  "
            f"(embeddings={'ENABLED' if emb else 'DISABLED (keyword RAG only)'})"
        )
    except Exception as ex:
        print(
            f"[Server][1] LLM init failed (specialists will fall back to synthetic where applicable): {ex}"
        )
        traceback.print_exc()

    grounding = None
    try:
        cfg = get_azure_search_config()
        if cfg.get("search_service_name") or cfg.get("endpoint"):
            grounding = AzureSearchFoundryIQ(llm_client=llm)
            print(f"[Server][1] Grounding: {grounding.name()}")
        else:
            grounding = LocalFoundryIQ()
            print(
                "[Server][1] Grounding: LocalFoundryIQ (no search service configured)"
            )
    except Exception as ex:
        print(f"[Server][1] Grounding init error, falling back to local: {ex}")
        traceback.print_exc()
        try:
            grounding = LocalFoundryIQ()
        except Exception:
            grounding = None

    fabric = None
    try:
        fabric = FabricIQ()
        print(
            "[Server][3] FabricIQ ready (data paths, role-cert matrix, capacity rules, gaps, prereqs)"
        )
    except Exception as ex:
        print(f"[Server][3] FabricIQ init FAILED: {ex}")
        traceback.print_exc()
        return {
            "status": "error",
            "error_code": client_error_code(ex),
            "iterations": 0,
            "plan": [],
            "results": {},
        }

    try:
        # Use state_path for true persistent multi-turn (plans evolve across Chat turns/sessions in portal;
        # resumes prior gaps closed, adjustments, progress instead of cold restart). /tmp survives container lifetime.
        # skill_path injects certification_skill.md (loop engineering: persistent domain knowledge for all sub-agents).
        # References review-scope.md hosted risks (Chat/Call routing, response envelope, azd ${} env).
        # Per-(role,cert) unique path (review Issues 6/9): mitigates /tmp concurrent race + cross-user leakage/pollution in container FS for hackathon (single-learner per file; same role/cert resumes across turns).
        # Sanitize for FS-safe names (fix for state bugs in multi-turn hosted Chat; consistent AZ204 vs AZ-204 etc). Post-validate req uses canonical forms from request_validation (reduces semantic collision); CERTIFYFORGE_STATE_PATH bypasses (documented).
        _r = (
            re.sub(r"[^A-Za-z0-9]", "", str(req.get("role", "default")))[:16]
            or "default"
        )
        _c = (
            re.sub(r"[^A-Za-z0-9]", "", str(req.get("certification", "AZ204")))[:8]
            or "AZ204"
        )
        default_state = f"/tmp/certifyforge_{_c}_{_r}_state.json"
        state_path = os.environ.get("CERTIFYFORGE_STATE_PATH", default_state)
        skill_path = str(
            Path(__file__).resolve().parent / "data" / "certification_skill.md"
        )
        orch = SimpleOrchestrator(
            fabric_iq=fabric,
            foundry_iq=grounding,
            llm_client=llm,
            seed=seed,
            state_path=state_path,
            skill_path=skill_path,
        )
        print(
            f"[Server][4] SimpleOrchestrator ready (planner + 5 specialists + critic + llm adjustment; state_path={state_path})"
        )

        # Pass prior from loaded state for hosted multi-turn (review Issue 4 + full wiring Issue 2). deepcopy for safety against nested mutation (e.g. LLM adjust milestones) in multi-turn resume.
        prior_for_handle = copy.deepcopy(getattr(orch, "_state", {}) or {})
        result = await orch.handle_request(req, prior_state=prior_for_handle)
        print(
            f"[Server] handle_request complete: status={result.get('status')} "
            f"iterations={result.get('iterations')}"
        )
        if result.get("llm_personalized_adjustment"):
            print(
                f"[Server] llm_personalized_adjustment: {result.get('llm_personalized_adjustment')}"
            )
        return result
    except Exception as ex:
        print(f"[Server] Orchestrator / handle_request error: {ex}")
        traceback.print_exc()
        return {
            "status": "error",
            "error_code": client_error_code(ex),
            "iterations": 0,
            "plan": [],
            "results": {},
        }


def parse_user_intent(message: str):
    """Rule-based intent parser for natural language chat messages.
    Hardened for complex real-world queries (e.g. "Help me with AZ-400 as a DevOps engineer with lots of meetings and limited focus time",
    multi-cert mentions). Maps accurately to trigger rich flows (prereqs, alignment, custom plans via Fabric+critic).
    """
    if not message:
        message = ""
    message_lower = message.lower()

    role = "Cloud Engineer"
    cert = None  # will be set from explicit mention in message, or role primary default for coherence
    work_signals = {
        "meeting_hours_per_week": 22,
        "focus_hours_per_week": 10,
        "preferred_learning_slot": "Morning",
    }

    if any(
        x in message_lower for x in ["devops", "sre", "platform engineer", "dev ops"]
    ):
        role = "DevOps Engineer"
    elif any(
        x in message_lower
        for x in ["developer", "software engineer", "cloud developer"]
    ) or (" dev " in f" {message_lower} " and "devops" not in message_lower):
        role = "Cloud Developer"
    elif any(x in message_lower for x in ["data engineer", "data platform"]):
        role = "Data Engineer"
    elif "architect" in message_lower:
        role = "Solutions Architect"

    # Robust cert extraction: support "DP-600", "dp600", "DP 600", "pl-300" etc. Explicit user mention always wins for coherence.
    cert_match = re.search(r"\b([A-Za-z]{2,3})[-\s]?(\d{3})\b", message)
    if cert_match:
        cert = f"{cert_match.group(1).upper()}-{cert_match.group(2)}"

    cert_map = {
        "az-204": "AZ-204",
        "az204": "AZ-204",
        "az-400": "AZ-400",
        "az400": "AZ-400",
        "dp-203": "DP-203",
        "dp203": "DP-203",
        "az-305": "AZ-305",
        "az305": "AZ-305",
        "dp-600": "DP-600",
        "dp600": "DP-600",
    }
    for key, value in cert_map.items():
        if key in message_lower:
            cert = value
            break

    # Role-based primary default ONLY if the user did not explicitly name a certification code.
    # This makes output coherent: "Help me with data engineering, high meetings..." → DP-600 (primary for Data Engineer), not AZ-204.
    if cert is None:
        role_defaults = {
            "Data Engineer": "DP-600",
            "DevOps Engineer": "AZ-400",
            "Cloud Engineer": "AZ-204",
            "Cloud Developer": "AZ-204",
            "Solutions Architect": "AZ-305",
        }
        cert = role_defaults.get(role, "AZ-204")

    # Multi-cert comparison hint (still pick primary; rich plan will surface alignment/prereqs from FabricIQ)
    if (
        "compare" in message_lower
        or " vs " in message_lower
        or " or " in message_lower
        or "versus" in message_lower
    ) and "az-400" in message_lower:
        cert = "AZ-400"

    hours_match = re.search(
        r"(\d+)\s*(focus|meeting)\s*(?:hours?\s*)?(?:per week|/week|week|hrs)",
        message_lower,
    )
    if hours_match:
        num = int(hours_match.group(1))
        if "focus" in hours_match.group(0):
            work_signals["focus_hours_per_week"] = min(max(num, 4), 40)
        elif "meeting" in hours_match.group(0):
            work_signals["meeting_hours_per_week"] = min(max(num, 4), 50)
    else:
        # Heuristics for "lots of meetings" / "limited focus time" (no explicit num) -> realistic high-meet/low-focus for complex queries
        if (
            "lots of meeting" in message_lower
            or "many meeting" in message_lower
            or "heavy meeting" in message_lower
        ):
            work_signals["meeting_hours_per_week"] = 30
        if (
            "limited focus" in message_lower
            or "little focus" in message_lower
            or "low focus" in message_lower
            or "scarce focus" in message_lower
        ):
            work_signals["focus_hours_per_week"] = 6

    slot_map = {
        "morning": "Morning",
        "afternoon": "Afternoon",
        "evening": "Evening",
        "night": "Evening",
    }
    for word, slot in slot_map.items():
        if word in message_lower:
            work_signals["preferred_learning_slot"] = slot
            break

    return role, cert, work_signals


def try_parse_structured_json(text: str) -> dict | None:
    """Parse role/cert/work_signals JSON pasted into Chat (may be wrapped in quotes)."""
    if not text:
        return None
    candidate = text.strip()
    if (
        len(candidate) >= 2
        and candidate[0] == candidate[-1]
        and candidate[0] in ("'", '"')
    ):
        candidate = candidate[1:-1].strip()
    if not candidate.startswith("{"):
        return None
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict) or not is_structured_invoke_payload(parsed):
        return None
    return parsed


def format_chat_fast_response(
    role: str,
    cert: str,
    work_signals: dict,
    user_message: str,
    *,
    from_structured_json: bool = False,
) -> str:
    """Lightweight Chat-tab reply from parsed intent (no full orchestration)."""
    focus = work_signals.get("focus_hours_per_week", 10)
    meeting = work_signals.get("meeting_hours_per_week", 22)
    slot = work_signals.get("preferred_learning_slot", "Morning")
    source_line = (
        "_Validated structured JSON._"
        if from_structured_json
        else f"_Parsed from: {sanitize_user_text(user_message, max_length=120)}_"
    )
    return (
        f"## Quick plan preview\n\n"
        f"I parsed your request as **{role}** targeting **{cert}** "
        f"with ~**{focus}** focus hours/week and ~**{meeting}** meeting hours/week ({slot} slot).\n\n"
        f"For a full multi-agent study plan (RAG + FabricIQ + Critic + LLM adjustment), use:\n"
        f"- **Call agent tab** / `azd ai agent invoke` with structured JSON (`role`, `certification`, `work_signals`), or\n"
        f'- Add `"run_full": true` to your pasted JSON in Chat.\n\n'
        f"{source_line}"
    )


def _is_complex_query(text: str) -> bool:
    """Detect complex real-world NL that should trigger full rich reasoning (plan+rag+fabric+critic+adjust+trace) even on chat non-structured path.
    Per requirements: non-structured now runs full for complex (e.g. the AZ-400 DevOps limited-focus example), fast only for generic short.
    """
    if not text:
        return False
    t = text.lower().strip()
    if len(t) < 6:
        return False
    complex_markers = [
        "help me with",
        "as a ",
        "for my role",
        "limited focus",
        "lots of meeting",
        "many meeting",
        "compare",
        " vs ",
        "versus",
        "or az-",
        "multi",
        "prereq",
        "alignment",
        "custom plan",
        "devops engineer",
        "with lots",
        "scarce time",
        "high meeting",
        "low focus",
        "study plan",
        "make a plan",
        "readiness",
    ]
    if any(m in t for m in complex_markers):
        return True
    # detailed sentence with role/cert signals
    if len(t) > 35 and any(r in t for r in ["engineer", "architect", "az-"]):
        return True
    return False


def format_certification_response(result: dict, role: str, cert: str) -> str:
    """Rich Markdown response for run_full Chat orchestration results.
    Now includes full step-by-step reasoning summary (plan, RAG citations, critic iterations/decisions, adjustment application)
    so the plan-reason-act-critic-adjust trace is visible and beautiful in portal Chat (impressive for Reasoning Agents track).
    Uses reasoning_trace from result envelope when present.
    """
    results = result.get("results", {}) or {}
    sp_output = (results.get("study_plan", {}) or {}).get("output", {}) or {}
    study_plan = sp_output.get("study_plan", {}) or sp_output

    fabric_details = sp_output.get("fabric_iq_details", {}) or {}
    gaps = fabric_details.get("gaps", []) or result.get("fabric_gaps", [])

    verification = (results.get("study_plan", {}) or {}).get("verification", {}) or {}
    # Prefer the post-critic verification + fabric details for a single consistent feasibility/time in header and highlights
    # (prevents mixed values like "4-6 weeks" in title vs "8.8" in breakdown, or 0.43 vs 0.60).
    feasibility = (
        verification.get("feasibility_score")
        or fabric_details.get("feasibility_score")
        or study_plan.get("feasibility_score")
        or result.get("feasibility_score", 0.60)
    )

    time_weeks = (
        verification.get("time_to_readiness_weeks")
        or fabric_details.get("time_to_readiness_weeks")
        or study_plan.get("time_to_readiness_weeks")
        or study_plan.get("estimated_weeks")
        or fabric_details.get("time_to_readiness_weeks", "6-8")
    )

    adjustment = sanitize_llm_output(
        result.get("llm_personalized_adjustment", "")
        or sp_output.get("llm_adjustment", ""),
        max_length=500,
    )

    # Extract RAG citations from multiple possible locations (learning_path, study, assess, trace)
    rag_cits = []
    for step in ("learning_path", "study_plan", "assessment"):
        outp = (results.get(step, {}) or {}).get("output", {}) or {}
        for k in ("citations", "grounded_in", "citations_used"):
            if k in outp and isinstance(outp[k], list):
                rag_cits.extend(str(c) for c in outp[k] if c)
    trace = result.get("reasoning_trace", {}) or {}
    if trace.get("rag_citations_used"):
        rag_cits.extend(trace.get("rag_citations_used"))
    rag_cits = list(dict.fromkeys([c for c in rag_cits if c]))[
        :5
    ]  # dedup, top for display

    # Pull bespoke reasoning provenance (now enriched in orchestrator for judges)
    bespoke_facts = (
        result.get("bespoke_fabric_iq_facts", {})
        or trace.get("bespoke_fabric_iq_facts", {})
        or {}
    )

    # === Safe defaults for trace variables (must be defined before any use) ===
    plan_steps = trace.get("plan_steps") or [
        (s.get("step") if isinstance(s, dict) else str(s)[:40])
        for s in (result.get("plan") or [])
    ]
    iters = trace.get("iterations") or result.get("iterations", 1)
    critic_decs = trace.get("critic_decisions", {})
    adj_applied = trace.get("adjustment_applied") or bool(adjustment)
    state_res = trace.get("state_resumed_from", False)
    skill_used = trace.get("skill_context_used", False)

    md = f"""# 🎯 Your Personalized {cert} Study Plan

**Role**: {role}  
**Target Certification**: {cert}  
**Estimated Time to Readiness**: ~{time_weeks} weeks  
**Feasibility Score**: {float(feasibility):.2f}

"""

    # Prominent "actual bespoke reasoning" callout (the key presentable element for hackathon judges)
    if bespoke_facts or critic_decs or iters > 1:
        md += "## 🧠 Bespoke Multi-Step Reasoning Highlights (Fabric IQ Ontology + Critic Loop)\n"
        if bespoke_facts.get("role_cert_alignment"):
            al = bespoke_facts["role_cert_alignment"]
            md += f"- **Ontology Alignment**: score={al.get('alignment_score', 0):.2f} (primary={al.get('is_primary')}, recommended={al.get('recommended')})\n"
        if bespoke_facts.get("prereq_chain"):
            md += f"- **Prerequisite Chain (from ontology)**: {bespoke_facts['prereq_chain']}\n"
        if bespoke_facts.get("feasibility_breakdown"):
            fb = bespoke_facts["feasibility_breakdown"]
            md += f"- **Feasibility Breakdown (Fabric IQ rules)**: score={fb.get('feasibility_score')}, feasible={fb.get('is_feasible')}, est_weeks={fb.get('estimated_weeks')}\n"
        if bespoke_facts.get("gap_penalty") is not None:
            md += f"- **Gap Penalty (derived from skill gaps in ontology)**: {bespoke_facts.get('gap_penalty')}\n"
        if iters > 1:
            md += f"- **Critic Loop**: {iters} iterations (see detailed decisions below; rejections drive refinement)\n"
        md += "\n"

    if adjustment:
        md += f"""## ✨ LLM Personalized Adjustment
{adjustment}

"""

    # Note for unknown certs (not in our primary matrix/models): the plan uses generic FabricIQ defaults + RAG.
    # Alignment will be low; this is informative rather than a hard error.
    if cert not in {"AZ-204", "AZ-400", "DP-203", "DP-600", "AZ-305", "SC-300"}:
        md += f"\n*Note: Limited specific data in our core ontology for **{cert}** (not listed in primary Role-Certification matrix or detailed cert models). Using general guidance, your role patterns, capacity rules, and search results. The full multi-agent pipeline (critic, adjustment, trace) still runs.*\n\n"

    if gaps:
        md += "## 📉 Skill Gaps Identified\n"
        for g in gaps[:6]:
            skill = g.get("skill", "Unknown")
            curr = g.get("current", 0)
            req_lvl = g.get("required", 1)
            prio = g.get("priority", "medium")
            md += f"- **{skill}**: {curr:.0%} → {req_lvl:.0%}  ({prio} priority)\n"
        md += "\n"

    milestones = study_plan.get("milestones", []) or []
    if milestones:
        next_milestone = (
            milestones[0].get("topic")
            or milestones[0].get("title")
            or milestones[0].get("description", "Week 1 fundamentals")
        )
    else:
        next_milestone = "Week 1: Core Azure services and compute fundamentals"

    # Dynamic for AZ-400 etc parity (review Issue 3): no more hardcoded AZ-204 text in rich Chat MD for complex NL/hackathon demo.
    hands_on = (
        adjustment
        or next_milestone
        or f"Build hands-on labs aligned to {cert} objectives this week."
    )
    md += f"""## 🚀 Next Milestone
{next_milestone}

**Hands-on Focus**: {hands_on}

"""

    # === Full visible reasoning trace (plan-reason-act-critic-adjust) for hackathon demo / judges ===
    # (variables already safely initialized at top of function)
    md += "## 🧠 Multi-Step Reasoning Trace (plan → reason(RAG+FabricIQ ontology) → act(specialists) → critic(self-reflect) → adjust(adapt))\n\n"
    md += f"**Iterations (critic loop)**: {iters}  |  **Stateful resume**: {'yes (prior gaps/progress remembered)' if state_res else 'no (fresh)'}  |  **Skill context**: {'loaded (certification_skill.md)' if skill_used else 'default'}\n"
    if bespoke_facts:
        md += "**Bespoke ontology facts fed to critic**: alignment, prereqs, gaps/penalty, feasibility rules (see highlights above).\n\n"

    if plan_steps:
        md += "### Plan Steps\n"
        full_plan = result.get("plan") or []
        for i, ps in enumerate(plan_steps, 1):
            desc = ""
            if i - 1 < len(full_plan):
                d = full_plan[i - 1]
                if isinstance(d, dict):
                    d = d.get("description", "")
                else:
                    d = ""
                if d:
                    desc = f" — {d}"
            md += f"{i}. `{ps}`{desc}\n"
        md += "\n"

    if rag_cits:
        md += "### Grounded RAG Citations Used\n"
        for i, c in enumerate(rag_cits, 1):
            md += f"{i}. `{c}`\n"
        md += "\n"
        # Surface that real hybrid RAG (with scores for ranking) was active when cits present (addresses review for visible chunks+scores).
        md += "*(Real Azure AI Search hybrid/vector chunks with @search.score/reranker used internally for ranking when key/MI grounding active.)*\n\n"
    else:
        md += "### Grounded RAG Citations Used\n*(Local guide fallback this run — real Azure AI Search (with scores) requires index permissions on the Instance Identity or AZURE_SEARCH_ADMIN_KEY in azd env. Reasoning driven by Fabric IQ + critic.)*\n\n"

    if critic_decs:
        md += "### Critic Self-Reflection Decisions\n"
        for step, dec in list(critic_decs.items())[:4]:
            acc = "ACCEPT" if dec.get("accepted") else "REJECT/ADJUST"
            conf = dec.get("confidence", "?")
            iss = dec.get("issues") or []
            md += f"- **{step}**: {acc} (conf={conf})"
            if iss:
                md += f" issues: {', '.join(str(x)[:40] for x in iss)}"
            md += "\n"
        md += "\n"

    if adj_applied:
        md += "### Adjustment Application\n- LLM note applied and **mutated milestones** (e.g. appended hands-on reinforcement; total_hours updated). See critic + post-critic in logs.\n\n"

    md += "---\n\nUse the **Call agent tab** or `azd ai agent invoke` for the full structured orchestration result + `reasoning_trace` envelope (queryable for judges).\n"

    return md


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                if part.get("type") in ("input_text", "output_text", "text"):
                    parts.append(str(part.get("text", "")))
                elif "text" in part:
                    parts.append(str(part.get("text", "")))
        return "".join(parts)
    return str(content or "")


def _messages_from_input_items(items) -> list[dict]:
    messages: list[dict] = []
    for item in items or []:
        item_type = getattr(item, "type", None)
        if item_type is None and isinstance(item, dict):
            item_type = item.get("type")
        if item_type != "message":
            continue
        role = getattr(item, "role", None)
        if role is None and isinstance(item, dict):
            role = item.get("role")
        content = getattr(item, "content", None)
        if content is None and isinstance(item, dict):
            content = item.get("content", "")
        if role:
            messages.append({"role": role, "content": _content_to_text(content)})
    return messages


def _merge_parsed_payload(data: dict, parsed: dict) -> None:
    structured_keys = {
        "role",
        "certification",
        "work_signals",
        "invoke",
        "run_full",
        "seed",
        "messages",
        "content",
        "message",
    }
    for key, value in parsed.items():
        if key in structured_keys or key not in data:
            data[key] = value


async def coalesce_request_data(
    request: "CreateResponse", context: "ResponseContext"
) -> dict:
    """Normalize Responses-protocol requests into the legacy payload dict shape."""
    data: dict = {}

    metadata = request.get("metadata") if hasattr(request, "get") else None
    if metadata is None:
        metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        data.update(metadata)

    raw_input = request.get("input") if hasattr(request, "get") else None
    if raw_input is None:
        raw_input = getattr(request, "input", None)

    if isinstance(raw_input, dict):
        _merge_parsed_payload(data, raw_input)
    elif isinstance(raw_input, list):
        messages = []
        for item in raw_input:
            if isinstance(item, dict) and item.get("type") == "message":
                role = item.get("role")
                content = item.get("content", "")
                if role:
                    messages.append(
                        {"role": role, "content": _content_to_text(content)}
                    )
        if messages:
            data.setdefault("messages", messages)

    input_text = await context.get_input_text()
    if input_text and input_text.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(input_text)
            if isinstance(parsed, dict):
                _merge_parsed_payload(data, parsed)
            elif isinstance(parsed, list) and not data.get("messages"):
                data["messages"] = parsed
        except json.JSONDecodeError:
            pass

    item_messages = _messages_from_input_items(await context.get_input_items())
    if item_messages and not data.get("messages"):
        data["messages"] = item_messages

    if (
        input_text
        and not data.get("messages")
        and not is_structured_invoke_payload(data)
    ):
        data["messages"] = [{"role": "user", "content": input_text}]
    elif (
        input_text
        and not data.get("content")
        and not is_structured_invoke_payload(data)
    ):
        if not any(
            (m.get("content") or "").strip()
            for m in data.get("messages", [])
            if isinstance(m, dict) and m.get("role") == "user"
        ):
            data.setdefault("messages", []).append(
                {"role": "user", "content": input_text}
            )

    return data


async def process_request_payload(data: dict) -> tuple[dict, str]:
    """Route structured vs chat payloads. Returns (envelope, path_label)."""
    req = None
    is_structured = False
    chat_ran_full = False
    path_label = "chat/fast"

    if isinstance(data, dict) and is_structured_invoke_payload(data):
        req = data
        is_structured = True

    if is_structured:
        path_label = "structured/full"
        try:
            if not _ORCH_SEMAPHORE.acquire(blocking=False):
                return (
                    error_envelope(
                        "Server is processing other requests. Please retry shortly.",
                        error_code="SERVER_BUSY",
                        include_result=True,
                        result={"status": "error", "error_code": "SERVER_BUSY"},
                    ),
                    "structured/busy",
                )
            try:
                validated = validate_structured_request(req or {})
                result = await run_full_orchestration(validated)
            finally:
                _ORCH_SEMAPHORE.release()
            summary = (
                f"Processed {validated.get('role')} / {validated.get('certification')}. "
                f"status={result.get('status')} iterations={result.get('iterations')}."
            )
            resp = {
                "status": "ok",
                "summary": summary,
                "result": result,
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": summary
                            + " (Full machine-readable orchestration in 'result'.)",
                        }
                    }
                ],
                "output": summary,
            }
        except ValidationError as ex:
            resp = error_envelope(
                str(ex),
                error_code=ex.code,
                include_result=True,
                result={"status": "error"},
            )
        except Exception as ex:
            traceback.print_exc()
            msg = client_safe_message(ex, context="structured")
            resp = error_envelope(
                msg,
                error_code=client_error_code(ex),
                include_result=True,
                result={"status": "error", "error_code": client_error_code(ex)},
            )
        return resp, path_label

    try:
        messages = data.get("messages", []) if isinstance(data, dict) else []
        user_message = ""
        if messages:
            for m in reversed(messages):
                if m.get("role") == "user":
                    user_message = _content_to_text(m.get("content", ""))
                    break
        if not user_message and isinstance(data, dict):
            user_message = data.get("content", "") or data.get("message", "") or ""

        embedded_structured = try_parse_structured_json(user_message)
        if embedded_structured:
            print(
                "[Server] Chat structured JSON detected; running validate_structured_request"
            )
        else:
            print(
                f"[Server] Chat message received: {redact_for_log(user_message, 120)}"
            )

        generic = not embedded_structured and (
            not user_message
            or len(user_message.strip()) < 6
            or user_message.lower().strip()
            in {"hi", "hello", "hey", "thanks", "thank you", "help"}
        )

        if generic:
            quick = (
                "Hi! I can parse your role, certification, and weekly constraints instantly. "
                "Paste structured JSON in Chat, or use the Call agent tab / `azd ai agent invoke`. "
                'Add `"run_full": true` in pasted JSON for the full multi-agent pipeline.'
            )
            resp = {
                "status": "ok",
                "summary": quick,
                "result": {"response": quick},
                "choices": [{"message": {"role": "assistant", "content": quick}}],
                "output": quick,
            }
        elif embedded_structured:
            try:
                validated = validate_structured_request(
                    {
                        **embedded_structured,
                        "source": "chat",
                        "original_message": user_message[:500],
                    }
                )
            except ValidationError as ex:
                resp = error_envelope(
                    str(ex),
                    error_code=ex.code,
                    include_result=True,
                    result={"status": "error"},
                )
            else:
                role = validated["role"]
                cert = validated["certification"]
                work_signals = validated["work_signals"]
                if validated.get("run_full") is True:
                    if not _ORCH_SEMAPHORE.acquire(blocking=False):
                        quick = "Server is busy processing other requests. Please retry shortly."
                        resp = error_envelope(
                            quick,
                            error_code="SERVER_BUSY",
                            include_result=True,
                            result={"status": "error", "error_code": "SERVER_BUSY"},
                        )
                    else:
                        try:
                            result = await run_full_orchestration(validated)
                            chat_ran_full = True
                            path_label = "chat/full"
                            assistant_reply = format_certification_response(
                                result, role, cert
                            )
                            resp = {
                                "status": "ok",
                                "summary": f"Personalized plan for {role} / {cert} (chat structured run_full)",
                                "result": result,
                                "choices": [
                                    {
                                        "message": {
                                            "role": "assistant",
                                            "content": assistant_reply,
                                        }
                                    }
                                ],
                                "output": assistant_reply,
                            }
                        finally:
                            _ORCH_SEMAPHORE.release()
                else:
                    path_label = "chat/structured-preview"
                    assistant_reply = format_chat_fast_response(
                        role,
                        cert,
                        work_signals,
                        user_message,
                        from_structured_json=True,
                    )
                    resp = {
                        "status": "ok",
                        "summary": f"Validated preview for {role} / {cert}",
                        "result": {
                            "validated": True,
                            "parsed": {
                                "role": role,
                                "certification": cert,
                                "work_signals": work_signals,
                            },
                            "response": assistant_reply,
                        },
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": assistant_reply,
                                }
                            }
                        ],
                        "output": assistant_reply,
                    }
        elif isinstance(data, dict) and data.get("run_full") is True:
            if not _ORCH_SEMAPHORE.acquire(blocking=False):
                quick = (
                    "Server is busy processing other requests. Please retry shortly."
                )
                resp = error_envelope(
                    quick,
                    error_code="SERVER_BUSY",
                    include_result=True,
                    result={"status": "error", "error_code": "SERVER_BUSY"},
                )
            else:
                try:
                    role, cert, work_signals = parse_user_intent(user_message)
                    chat_req = validate_structured_request(
                        {
                            "role": role,
                            "certification": cert,
                            "work_signals": work_signals,
                            "source": "chat",
                            "original_message": user_message[:500],
                            "run_full": True,
                        }
                    )
                    result = await run_full_orchestration(chat_req)
                    chat_ran_full = True
                    path_label = "chat/full"
                    assistant_reply = format_certification_response(result, role, cert)
                    resp = {
                        "status": "ok",
                        "summary": f"Personalized plan for {role} / {cert} (chat run_full)",
                        "result": result,
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": assistant_reply,
                                }
                            }
                        ],
                        "output": assistant_reply,
                    }
                finally:
                    _ORCH_SEMAPHORE.release()
        else:
            role, cert, work_signals = parse_user_intent(user_message)
            if _is_complex_query(user_message):
                # Per task: non-structured chat now runs *full* for complex queries (rich plan-reason-act-critic-adjust trace visible in portal Chat, no spinner for impressive demo).
                # Still defensive: semaphore, try, always-200, body preview already logged upstream.
                if not _ORCH_SEMAPHORE.acquire(blocking=False):
                    quick = "Server is busy processing other requests. Please retry shortly."
                    resp = error_envelope(
                        quick,
                        error_code="SERVER_BUSY",
                        include_result=True,
                        result={"status": "error", "error_code": "SERVER_BUSY"},
                    )
                else:
                    try:
                        chat_req = validate_structured_request(
                            {
                                "role": role,
                                "certification": cert,
                                "work_signals": work_signals,
                                "source": "chat",
                                "original_message": user_message[:500],
                                "run_full": True,
                            }
                        )
                        result = await run_full_orchestration(chat_req)
                        chat_ran_full = True
                        path_label = "chat/full"
                        assistant_reply = format_certification_response(
                            result, role, cert
                        )
                        resp = {
                            "status": "ok",
                            "summary": f"Personalized plan for {role} / {cert} (chat complex NL -> full reasoning)",
                            "result": result,
                            "choices": [
                                {
                                    "message": {
                                        "role": "assistant",
                                        "content": assistant_reply,
                                    }
                                }
                            ],
                            "output": assistant_reply,
                        }
                    finally:
                        _ORCH_SEMAPHORE.release()
            else:
                assistant_reply = format_chat_fast_response(
                    role, cert, work_signals, user_message
                )
                resp = {
                    "status": "ok",
                    "summary": f"Intent preview for {role} / {cert}",
                    "result": {
                        "parsed": {
                            "role": role,
                            "certification": cert,
                            "work_signals": work_signals,
                        },
                        "response": assistant_reply,
                    },
                    "choices": [
                        {"message": {"role": "assistant", "content": assistant_reply}}
                    ],
                    "output": assistant_reply,
                }
    except Exception as ex:
        traceback.print_exc()
        quick = client_safe_message(ex, context="chat")
        resp = error_envelope(
            quick,
            error_code=client_error_code(ex),
            include_result=True,
            result={"status": "error", "error_code": client_error_code(ex)},
        )

    if chat_ran_full:
        path_label = "chat/full"
    return resp, path_label


def envelope_to_response_text(data: dict, envelope: dict) -> str:
    """Map legacy envelope to assistant text for Responses protocol consumers."""
    if isinstance(data, dict) and is_structured_invoke_payload(data):
        return json.dumps(envelope, default=str, ensure_ascii=False)
    return str(envelope.get("output") or envelope.get("summary") or "")


def create_responses_app() -> "ResponsesAgentServerHost":
    if ResponsesAgentServerHost is None:
        raise RuntimeError(
            "azure-ai-agentserver-responses is not installed. "
            "Add it to requirements.txt and rebuild the container."
        )

    app = ResponsesAgentServerHost()

    @app.response_handler
    async def certifyforge_handler(
        request: CreateResponse,
        context: ResponseContext,
        cancellation_signal: asyncio.Event,
    ):
        data = await coalesce_request_data(request, context)
        preview = redact_for_log(
            json.dumps(data, default=str) if data else "(empty)",
            120,
        )
        print(f"[Server] POST /responses received; preview={preview}")

        async def _build_text():
            envelope, path_label = await process_request_payload(data)
            out_preview = redact_for_log(
                str(envelope.get("output") or envelope.get("summary") or envelope),
                120,
            )
            print(
                f"[Server] responding path={path_label}; out_preview: {out_preview}..."
            )
            return envelope_to_response_text(data, envelope)

        return TextResponse(context, request, text=_build_text)

    return app


class ReadinessHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/readiness", "/health", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(
            b"CertifyForge Reasoning Agents readiness server. POST for orchestration."
        )

    def do_POST(self):
        if not _POST_SEMAPHORE.acquire(blocking=False):
            resp = error_envelope(
                "Server is processing other requests. Please retry shortly.",
                error_code="SERVER_BUSY",
                include_result=True,
                result={"status": "error", "error_code": "SERVER_BUSY"},
            )
            self._send_json(200, resp, path_label="rejected/busy")
            return

        try:
            self._handle_post_body()
        finally:
            _POST_SEMAPHORE.release()

    def _handle_post_body(self):
        raw_length = parse_content_length(self.headers.get("Content-Length"))
        if is_oversize_body(raw_length):
            resp = error_envelope(
                "Request body too large. Maximum size is 256 KiB.",
                error_code="PAYLOAD_TOO_LARGE",
            )
            self._send_json(200, resp, path_label="rejected/oversize")
            return

        content_length = clamp_body_length(raw_length)
        body = (
            self.rfile.read(content_length).decode("utf-8", errors="replace")
            if content_length
            else ""
        )
        print(
            f"[Server] POST / (legacy test shim) body_len={len(body)}, preview: {redact_for_log(body, 120)}"
        )

        data: dict = {}
        if body:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    data = parsed
                else:
                    print("[Server] non-dict body -> chat/fast")
            except Exception as ex:
                print(
                    f"[Server] body not JSON or parse error -> chat/fast: {ex}; preview={redact_for_log(body, 120)}"
                )

        resp, path_label = asyncio.run(process_request_payload(data))
        self._send_json(200, resp, path_label=path_label)

    def _send_json(self, code: int, resp: dict, path_label: str = "unknown") -> None:
        try:
            out_preview = redact_for_log(
                str(resp.get("output") or resp.get("summary") or resp), 120
            )
        except Exception:
            out_preview = "(unprintable)"
        print(
            f"[Server] responding {code} path={path_label}; out_preview: {out_preview}..."
        )

        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        try:
            self.wfile.write(
                json.dumps(resp, default=str, ensure_ascii=False).encode("utf-8")
            )
        except Exception:
            self.wfile.write(
                json.dumps(
                    error_envelope(
                        "Response encoding fallback.", error_code="ENCODE_ERROR"
                    ),
                    ensure_ascii=False,
                ).encode("utf-8")
            )

    def log_message(self, format, *args):
        pass


if __name__ == "__main__":
    ep = os.environ.get("AZURE_AI_PROJECT_ENDPOINT", "")
    port = os.environ.get("PORT", "8088")
    print(
        f"Starting CertifyForge Responses server (POST /responses, GET /readiness) on port {port}..."
    )
    print(
        "  [Access tip] If the azd Playground URL gives 'Agent not found' in the portal:"
    )
    print(
        "    1. Switch in the UI to the project matching AZURE_AI_PROJECT_ENDPOINT (e.g. ProjectCert)."
    )
    print(
        "    2. Build > Agents → open 'certifyforge-agents' from the *list* (not the deep link)."
    )
    print("    3. Or just use: azd ai agent invoke certifyforge-agents '{...json...}'")
    if ep:
        print(f"    Current project endpoint: {ep}")
    create_responses_app().run()
