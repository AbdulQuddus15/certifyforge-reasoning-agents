---
name: hosted-agent-dev-loop
description: >-
  End-to-end coding, parallel review, and fix loop for the CREATIVE_APP_02
  certifyforge-agents hosted agent. Spawns a dedicated parallel reviewer panel
  (general + security + tests + hosted-deployment) while an implementer codes,
  then resumes the implementer to apply fixes until all reviewers report zero
  open issues. Use when asked to develop, review, or harden the hosted agent at
  creative_app_02, certifyforge-agents, or CREATIVE_APP_02. Triggers: "hosted
  agent dev loop", "review hosted agent", "code review creative_app_02",
  "/hosted-agent-dev-loop".
argument-hint: "[--effort N] <task description>"
---

# Hosted Agent Dev Loop (CREATIVE_APP_02)

You orchestrate an **implement → parallel review → fix → re-review** loop for the `certifyforge-agents` hosted agent in `CREATIVE_APP_02`. You coordinate only — all coding and review findings come from subagents.

## Project context

- Workspace root: `CREATIVE_APP_02/`
- Deployable package: `src/certifyforge_agents/`
- Hosted definition: `src/certifyforge_agents/agent.yaml` (`kind: hosted`, `protocols: responses`)
- Review scope reference: `<dirname of this SKILL.md>/references/review-scope.md`

Read the review-scope reference at setup and inject its checklist into every reviewer prompt.

## Persona injection

Load persona instructions from the bundled skills shared directory:

```
<user-home>/.grok/bundled/skills/shared/personas/implementer.md
<user-home>/.grok/bundled/skills/shared/personas/reviewer.md
<user-home>/.grok/bundled/skills/shared/personas/security-auditor.md
```

Resolve `<user-home>` from the environment (`$HOME` / `%USERPROFILE%`). Read each file once at setup.

When launching subagents, **prepend** the appropriate persona to the prompt. Prefix `description` with a bracketed role tag (`[implementer]`, `[reviewer]`, `[security]`, `[tests]`, `[hosted]`) so the pager shows the role. Do NOT pass a `persona` parameter to `spawn_subagent`.

## Invocation

```
/hosted-agent-dev-loop [--effort N] <task>
```

- `--effort N` (1–5, default **3**): controls parallel reviewer count.
- `<task>`: what to implement, fix, or harden (feature, bug, deploy issue, portal UX, etc.).

Extract effort from the argument string; treat the remainder as the task description.

## Reviewer panel (always parallel after implement)

Unlike generic `/implement`, this skill **always** uses parallel reviewers after the implementer finishes. Default composition by effort:

| Effort | Panel |
|--------|-------|
| 1 | general reviewer only |
| 2 | general + security |
| 3 | general + security + tests (default) |
| 4 | general + general-2 + security + tests |
| 5 | general + general-2 + security + tests + hosted-deployment |

**Hosted-deployment specialist** (prompt-only, no persona): reviews `agent.yaml`, `Dockerfile`, `entrypoint.sh`, `readiness_server.py`, `azure.yaml`, azd env wiring, container paths, portal Chat/Call behavior, and deploy observability. Uses the review-scope reference as its checklist.

**Tests specialist** (prompt-only): focuses on `test_*.py`, demo parity (local vs hosted startup logs), edge cases in orchestrator/grounding, and missing coverage for error paths.

**Security specialist**: inject `security-auditor` persona; map severities to `bug`/`suggestion`/`nit` in the merged review (critical/high → bug, medium → suggestion, low/info → nit).

**General reviewer(s)**: inject `reviewer` persona; full code quality pass across `src/certifyforge_agents/`.

## Setup

Generate a run ID:

```bash
python3 -c "import uuid; print(uuid.uuid4().hex[:8])"
```

Store as `LOOP_ID`. Set restrictive umask (`umask 077` on Unix). Define paths (fixed for the entire loop):

- `summary_file`: `/tmp/grok-hosted-impl-summary-${LOOP_ID}.md`
- `review_file`: `/tmp/grok-hosted-review-${LOOP_ID}.md` (merged review for implementer)
- Per-reviewer files (effort ≥ 2): `/tmp/grok-hosted-review-${LOOP_ID}-<tag>.md` where tag is `general`, `general-2`, `security`, `tests`, `hosted`

Initialize state: `round_count=0`, `implementer_subagent_id=null`, `reviewer_configs=[]`, `total_issues_by_severity={}`, `previous_review_snapshot=""`.

Open a todo scaffold (merge: false):

- `setup`
- `implement`
- `review-round-1`
- `fix-round-1`
- `rereview-round-1`
- `final-report`

Mark exactly one `in_progress` at a time.

## Step 1: Implement

Launch implementer via `spawn_subagent` (`subagent_type: general-purpose`, `description: "[implementer] <short task>"`).

Prompt template:

```
<implementer_persona_instructions>

---

Implement the following for the CREATIVE_APP_02 hosted agent (certifyforge-agents):

<full task description + conversation context>

Project constraints:
- Package root: src/certifyforge_agents/
- azd is single source of truth for env vars (agent.yaml uses ${VAR})
- Keep local demo (demo_orchestration.py) and hosted behavior aligned
- Defensive error handling at every external boundary (LLM, search, HTTP)
- readiness_server must always return HTTP 200 with usable JSON

When done, write an implementation summary to: <summary_file>
Include: files changed, design decisions, deploy/test commands run.
```

Wait for completion. Save `implementer_subagent_id`.

Read `summary_file` and derive 3–5 `reviewer_focus_areas` from it (e.g., "verify chat fast-path still returns direct assistant text", "check embedding env resolution after azd deploy").

## Step 2: Parallel review

Launch **all** reviewers in parallel with `background: true`. Emit every `spawn_subagent` call before any launch narration.

For each reviewer, include in the prompt:
- The review-scope reference path and instruction to read it
- `summary_file` path
- `reviewer_focus_areas`
- Instruction to read source files beyond the summary (not just the summary)
- Output path for that reviewer's individual file

Structured issue format (all reviewers):

```markdown
## Summary
<2-4 sentence assessment>

## Issues

### Issue 1 — Severity: bug
- File: path/to/file.py:LINE
- Description: ...
- Suggestion: ...
- Status: open
```

Severity must be `bug`, `suggestion`, or `nit`. Every issue needs `Status: open`.

Wait for all reviewers. If the general reviewer fails, stop. Specialist failures are non-fatal (warn and continue).

## Step 3: Merge and decide

Read each individual review file. Merge into `review_file` with source tags: `[General]`, `[General-2]`, `[Security]`, `[Tests]`, `[Hosted]`. Consolidate obvious duplicates; when in doubt, keep both.

Count open issues by severity. Increment `round_count`.

- **0 open issues** → Final report (Step 6)
- **Any open issues** → Step 4 (fix)
- **Stalemate** (wontfix re-opened) → ask user to decide, then resume implementer with user ruling

## Step 4: Fix (resume implementer)

Resume implementer (`resume_from: implementer_subagent_id`, `description: "[implementer] Fix review issues"`).

```
The parallel review panel found issues. Merged review at: <review_file>

Read the review_file. Address ALL issues with Status: open.

For each issue:
- Implement the fix
- Update Status: open → Status: fixed (or wontfix with technical justification)
- Add a Response field

Append an updated Implementation Summary at the bottom of review_file.
```

## Step 5: Re-review (parallel)

Resume all reviewers in parallel (`resume_from` each `reviewer_configs` entry, `background: true`). Each rewrites its individual review file:
- Do not re-list properly fixed issues
- Re-list inadequately fixed issues as open
- Flag regressions as new open issues

Merge again (Step 3). Repeat until 0 open issues. No iteration cap.

## Step 6: Final report

Present:

1. What was implemented (from `summary_file`)
2. Reviewer panel used (effort + specializations)
3. Review rounds (`round_count`)
4. Total issues fixed by severity
5. Files changed
6. Recommended verification commands:

```powershell
# Local demo
cd C:\Users\abdul\CREATIVE_APP_02\src\certifyforge_agents
..\..\venv\Scripts\python.exe demo_orchestration.py --seed 0

# Deploy + invoke
cd C:\Users\abdul\CREATIVE_APP_02
azd deploy --service certifyforge-agents
azd ai agent invoke certifyforge-agents '{"role":"Cloud Engineer","certification":"AZ-204","work_signals":{"meeting_hours_per_week":22,"focus_hours_per_week":10,"preferred_learning_slot":"Morning"}}'
```

## Tool-call discipline

- Emit `spawn_subagent` before narrating any launch
- Never modify source files yourself — only subagents do
- Never end a turn claiming a subagent started without the tool call in the same response
- Reviewers are read-only; only the implementer edits code

## Rules

- Scope changes to `src/certifyforge_agents/`, `scripts/`, `agent.yaml`, `Dockerfile`, `azure.yaml`, and infra only when the task requires it
- Do not delete or weaken defensive try/except at external boundaries without strong justification
- Prefer `azd env set` + `${}` substitution over hardcoded secrets or endpoints
- Keep Chat fast-path and structured invoke path separate in `readiness_server.py`
- Thread the same `LOOP_ID` file paths across all rounds