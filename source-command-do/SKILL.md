---
name: "source-command-do"
description: "VibeCoding/AlphaMate canonical front door. Routes natural-language requests through the shared work_router (Vibe Coding/tools/work_router.py) using the canonical routing table (Vibe Coding/tools/router/routing.yaml). Absorbs /work, /auto, and the legacy /gsd:do — the user no longer chooses which skill to run; intent → route → engine → save handoff is automatic. Use whenever the user types /do, says \"다음 작업\", \"계속 진행\", or hands you a freeform request that hasn't already been pinned to a specific skill."
---

# source-command-do

Use this skill when the user asks to run the migrated source command `do`.

## Command Template

<objective>
You are the **canonical front door** for VibeCoding / AlphaMate work across 4 agents
(Codex, Codex, Hermes, OpenClaw) and 3 machines (Desktop, A8, G3).

The pain point this command solves: "the user doesn't know which skill to invoke."
You absorb that decision. The user gives a natural-language request; you call the
shared router, surface the chosen route, and (after preflight clearance) execute it
and hand off to the save pipeline.

Do NOT reinvent routing logic in this prompt. The actual classifier lives in
`Vibe Coding/tools/work_router.py` (1223 LOC, already battle-tested). The policy
lives in `Vibe Coding/tools/router/routing.yaml`. This command is a thin orchestrator.
</objective>

<bootstrap>
Always read in this exact order before classifying:

1. `C:/Users/sudol/Vibe Coding/RULES.md` — workspace-wide canonical rules
2. `C:/Users/sudol/Vibe Coding/AlphaMate/docs/shared-work-surface.md` — 4-agent shared surface
3. `C:/Users/sudol/Vibe Coding/tools/router/routing.yaml` — canonical routing policy
4. Active project `HANDOFF.md` (if a project is in scope)

Run `hostname` once to identify the active machine:
- `DESKTOP-1BM18KD` → Desktop, root `D:\Vibe Coding`
- `A8_Max` → A8, root `C:\Users\sudol\Vibe Coding`
- `NucBoxG3` → G3, root `D:\VibeCoding-root` (production — extra care)
</bootstrap>

<routing>
For the user's request, run the shared router in **plan-only** mode first:

```bash
python "C:/Users/sudol/Vibe Coding/tools/work_router.py" "<request verbatim>" --plan-only
```

This writes `.planning/harness/PLAN.md` + `WORK_PLAN.json` and prints a summary.
Surface to the user (in Korean, compact):

- Chosen route (login / discover / review / patch / deliver / deliver-deep / release)
- Decision source (router-llm / keyword-fallback / assistant-led)
- 난이도 / 라우팅 확신도
- preflight: auto-proceed | confirmation required (+ reason)

If preflight is `confirmation required` (low confidence, conflicting intents,
plan-only guard, broad-scope override) — ask once, briefly. Otherwise proceed.

Execute the saved plan after clearance:

```bash
python "C:/Users/sudol/Vibe Coding/tools/work_router.py" --execute-plan
```

If the user explicitly chose a route up front (e.g. "이거 deliver-deep으로"), pass
`--route deliver-deep` instead of relying on the LLM router.
</routing>

<post_actions>
After the route's engine completes, **automatically hand off to alphamate-save**:

- Run xrev-style strict review on the implementation diff (RULES.md "Code Phase End")
- Update `WORKLOG.md` (prepend) and `HANDOFF.md` (current state)
- Promote durable context to Obsidian raw/
- Stage only relevant files; commit with Korean message; push current branch
- Generate the branch/mainline/pull table via
  `tools/save/collect_save_record.ps1`
- SSH pull-sync the other two machines via
  `tools/save/sync_vibecoding_root.ps1` (A8 → Desktop+G3, etc.)
- Do NOT restart G3 services unless the user explicitly approved restart/deploy
- Do NOT auto-merge to mainline; if asked, run `tools/save/plan_mainline_integration.ps1`
  first and only proceed on `fast-forward` / `merge-clean`

Skip the save handoff only if the user wrote a plan-only guard
("계획만", "수정하지 마", "승인 전", "plan only") or the route itself is
plan-only (e.g. discover/review producing only a Decision Packet).
</post_actions>

<absorbed_commands>
- `/work <req>` — alias of `/do`. Same router, same flow.
- `/auto <req>` — alias of `/do`. Same router, same flow.
- `/gsd:do <req>` — **legacy/deprecated**. Kept as GSD-internal phase alias only.
  New work uses `/do`. The existing `~/.Codex/commands/gsd/do.md` remains
  callable for backward compat but should display its LEGACY banner.
- Direct `/gsd:debug`, `/gsd:execute-phase`, `/bug-hunt`, `/feature-add`, etc. —
  still callable. `/do` will route into them automatically when intent matches.
</absorbed_commands>

<output_shape>
Compact. The user is busy.

For routing-only turns:
- Chosen route + 1-line reason
- Where artifacts landed (`.planning/harness/PLAN.md`, `WORK_PLAN.json`)
- Preflight verdict
- One-line "다음 단계" preview

For full execution turns:
- Same routing summary
- Execution highlights (errors only; let logs carry the rest)
- Save table (branch / mainline / pull / parent pointer / machine sync)
- Residual risk if any
</output_shape>

<canonical_vs_mirror>
Per `RULES.md`:

- **Canonical** (changes happen here):
  - `Vibe Coding/RULES.md`
  - `Vibe Coding/tools/router/routing.yaml`
  - `Vibe Coding/tools/work_router.py`
  - `Vibe Coding/AlphaMate/docs/shared-work-surface.md`
- **Mirrors** (read-only references; do not edit through this command):
  - `~/.codex/skills/work-router/SKILL.md`
  - `~/.codex/skills/alphamate-save/SKILL.md`
  - `~/.Codex/AGENTS.md`
  - `LLM Wiki/` and Obsidian `raw/`
</canonical_vs_mirror>

<machine_aware>
Per `RULES.md` "Cross-Machine Sync":

| machine | hostname | primary root | role |
|---|---|---|---|
| Desktop | `DESKTOP-1BM18KD` | `D:\Vibe Coding` | 주 개발 |
| A8 | `A8_Max` | `C:\Users\sudol\Vibe Coding` | 원격 허브 |
| G3 | `NucBoxG3` | `D:\VibeCoding-root` (root clone), `D:\Vibe Coding` (operational) | 상시 서버 |

After save, SSH pull-sync the other two machines. If Desktop is powered off, record
it as skipped; do not block G3 sync. Never call vague "sync" — say which machine
pulled, skipped, or failed. Service restarts on G3 are approval-gated.
</machine_aware>

<when_in_doubt>
- If the user's request is ambiguous between two routes, prefer the **broader lane**
  (`work_router.py` already does this in `_merge_route_decisions`). Surface the
  ambiguity but don't stall.
- If the request is clearly out-of-scope of routing (e.g. "이 파일 읽어봐"),
  fall back to direct tool use. `/do` is for *work*, not lookups.
- If `python` or `work_router.py` is unreachable, fall back to `classify_request`
  logic by manually mapping the request through `routing.yaml` keywords and call
  the chosen engine's CLI directly. Record the fallback in HANDOFF.
</when_in_doubt>

<reference>
- routing impl: `Vibe Coding/tools/work_router.py`
- routing policy: `Vibe Coding/tools/router/routing.yaml` (+ README.md)
- save pipeline: `~/.codex/skills/alphamate-save/SKILL.md` (mirror) ← `RULES.md` (canonical)
- shared surface: `Vibe Coding/AlphaMate/docs/shared-work-surface.md`
- mainline planner: `Vibe Coding/tools/save/plan_mainline_integration.ps1`
- root sync: `Vibe Coding/tools/save/sync_vibecoding_root.ps1`
- save record: `Vibe Coding/tools/save/collect_save_record.ps1`
- deeper orchestrator (deliver-deep optional): `AlphaMate/orchestrator/ultrathink.py`
- legacy GSD do: `~/.Codex/commands/gsd/do.md` (kept as alias)
</reference>
