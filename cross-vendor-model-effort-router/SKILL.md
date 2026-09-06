---
name: cross-vendor-model-effort-router
description: >-
  Use this skill before multi-file, multi-step, batch/repeated, architecture, or
  high-failure-cost work when no model, effort, or execution route has been deliberately
  selected. Also recommends a model/effort or delegate worker when asked directly, judges
  direct-vs-delegate, and handles cost cuts, post-failure escalation, and outcome recording.
  Sole owner of model/effort/worker routing (supersedes gpt-model-effort-advisor); returns
  DIRECT, PLAN_FIRST, DELEGATE, NEEDS_SURFACE, or NEEDS_PREFERENCE. 한국어의 모델·effort·워커 라우팅,
  직접·위임 판단, 비용 절감, 실패 에스컬레이션, 결과 기록 요청에도 사용한다. Do not use for
  trivial execution requests needing no route selection, incidental model names in code,
  logs, or config, or informational explanations/comparisons of model commands,
  capabilities, prices, or benchmarks. Do not reconsider an already fixed or normally
  progressing route unless troubleshooting, rerouting, or recording.
---

# Cross-Vendor Model & Effort Router

Pick the cheapest route that still passes a real check, escalate only on verified failure, and learn
from recorded outcomes. **This skill recommends and records. The operator decides and switches.**

## What this skill is NOT

It does **not** modify the dispatcher (`call_worker.sh`), `backends.json`, or any hook. It creates no
second dispatcher or authority path and never executes a worker. It may read and validate
`backends.json` to produce a fixed-loadout execution plan; this is advisory only. It never approves
its own results.

## Legacy advisor replacement contract

This skill **supersedes `gpt-model-effort-advisor`** and is the **sole automatic owner** of model
recommendation, effort recommendation, implicit pre-task routing, direct-vs-delegate decisions,
worker selection, cost/latency/context trade-offs, failure escalation, and **new outcome recording**.
The legacy skill stays installed for rollback but must **not** be a competing automatic trigger.

For DIRECT OpenAI/Codex routes it preserves the legacy behaviour: Luna/Terra/Sol tier
recommendation, native effort recommendation, the original four axes, High as the normal ceiling,
tier escalation after High, spec/DoD correction instead of blind effort escalation, legacy registry
lookup, and `session` reporting where observable.

The legacy `registry.jsonl` is **read-only**. All new outcomes — including GPT DIRECT outcomes —
are written only to this skill's registry.

## The asymmetry you must understand first

Two routes, and they are **not** symmetric:

| | What you actually choose | Ladder available? |
|---|---|---|
| **DELEGATE** | **Which worker/role fits the current flavor** — nothing else | ❌ Model/effort are a **property of the worker**, fixed in `backends.json`. This skill does not change them. |
| **DIRECT** | **Your own model and effort** | ✅ Real 2-axis ladder via `/model` and `/effort` |

So: **never "recommend a model/effort for a worker"** — that is not a dial you can turn. Load the
worker's fixed values from the current backend contract and return
`model_selectable=false, effort_selectable=false`. A missing trusted writer profile is a hard
contract mismatch, not permission to invent write capability.

## Engine: `router.py`

Standard library only. Always use the CLI — never hand-edit the JSONL.

```
python3 router.py recommend "<task>" --surface codex --axes "..." --axes-ext "..."
python3 router.py recommend "<task>" --surface claude --backends <path> --axes "..." --axes-ext "..."
python3 router.py recommend "<task>" --surface claude --candidate-model fable-5 --rollout-stage v2 ...
python3 router.py query "<task>" --surface codex --model-family gpt-6 --task-family implementation
python3 router.py record --task "..." --worker ... --outcome ... --attempt-id ...
python3 router.py invalidate --target-attempt-id ... --reason-code ... \
  --verification-evidence ... --event-id ...
python3 router.py stats
python3 router.py validate                                           # malformed/duplicate lines
```

Registry: this skill owns `registry.jsonl` next to `router.py`. The GPT advisor's registry
(`~/.agents/skills/gpt-model-effort-advisor/registry.jsonl`) is read **read-only** as legacy evidence
and is **never written to** — writing non-GPT records there would surface Claude/Grok/Gemini combos in
that advisor's GPT recommendations, because its loader and query have no vendor filter.

## Workflow

### 0. Lock the direct surface

Pass `--surface codex` or `--surface claude` whenever DIRECT is possible. Missing or unknown
surface returns `NEEDS_SURFACE`; the router never guesses.

- Codex recommendation allowlist: `gpt-5.6-luna`, `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra`
  (2026-09-06 라이브 프로브: 넷 다 응답. 없는 id 는 provider 400 — 통과가 무의미하지 않다)
- Claude recommendation allowlist: `haiku-4.5`, `sonnet-5`, `opus-5`
- Other visible models remain inventory, not automatic recommendations:
  Codex `gpt-5.3-codex-spark`, `gpt-5.4-mini`, `gpt-5.4`, `gpt-5.5`;
  Claude `sonnet-4.6`, `opus-4.6`, `opus-4.7`, `opus-4.8`
- `fable-5` is experimental shadow only; it is not in the production ladder.

### 1. Classify

Four core axes (same vocabulary as the GPT advisor):
`--axes "verifiable=yes|partial|no,failcost=low|mid|high,volume=high|low,depth=shallow|mid|deep"`

Four extended axes that drive the break-even gate:
`--axes-ext "handoff_cost=low|high,spec_readiness=executable|vague,decomposability=independent|single,context_dependency=low|high,verifier_available=yes|no"`

- **handoff_cost** — how much spec-writing and context transfer does delegation require?
- **spec_readiness** — is the goal, scope, DoD and verifier settled enough to hand over?
- **decomposability** — does it split into independent units?
- **context_dependency** — how much does it rely on the current conversation's implicit context?

### 2. Gate (in this order)

1. **`spec_readiness != executable` → `PLAN_FIRST`.** Settle the spec first. Do not spend an expensive
   run exploring an unclear goal — that is the single largest waste.
2. **`volume=low AND (handoff_cost=high OR context_dependency=high)` → `DIRECT`.** A subagent does not
   share your prompt cache, so every delegation pays a fixed cost (new context + writing the spec).
   Small one-off work loses that trade. **Do it yourself.**
3. **`spec_readiness=executable AND (volume=high OR decomposability=independent) AND verifier_available=yes`
   → `DELEGATE` candidate.**
4. Otherwise → `DIRECT, confidence=low`.

This gate is **qualitative**. There are no paired direct-vs-delegated observations and no comparable
cost unit, so report `break_even: heuristic pass` and **never** claim a number ("saves 37%").

### 2b. The optimization-goal gate — why DELEGATE is not a cost saving here

**No delegate worker runs an economy loadout.** Every worker is pinned to premium/frontier
(2026-09-06 backends.json 실측: opus·max, gpt-6-astra·config, Gemini 3.7 Flash (High)·model-high,
grok-4.6·high). So for a **mechanical batch**,
delegation buys **parallelism and main-context preservation — not a lower tier.**

Do **not** claim delegation is cheaper, and do not claim DIRECT is cheaper either: switching the
session model rebuilds the prompt cache, and a delegate receives a small distilled spec instead of
your whole session context. **`cost_comparison: unmeasured`** is the only honest value.

So when the work is a mechanical batch, the winner depends on `optimization_goal`:

| goal | route |
|---|---|
| `cost` | **DIRECT** at a verified lower tier (the tier-saving is a hypothesis, not a measurement) |
| `latency` / `context_preservation` | **DELEGATE** is fine — with the cost disclaimer attached |
| unstated | **`NEEDS_PREFERENCE`** — present both conditional routes and ask. Do not fabricate a winner. |

**Mechanical is a conjunction, not two flags.** `depth=shallow AND verifiable=yes` alone would
misclassify bulk permission changes, migrations and repo-wide renames — all shallow and exactly
verifiable, yet high-risk. Require: `depth=shallow AND verifiable=yes AND volume=high AND
failcost != high AND spec_readiness=executable AND decomposability=independent AND
context_dependency=low`.

**Tool-first**: if the batch is also `uniformity=high`, check whether a **deterministic script**
can do it before spending any LLM route at all. The cheapest route is often no model.

### 3. Consult the registry

`router.py query` merges this skill's registry with the legacy GPT registry (read-only). Verified
history beats the cold-start prior — **but only when it is strong enough** (next section).

### 4. Recommend

- **DELEGATE** → read the current `backends.json`, bind the current flavor, conductor, default main
  worker and role, and show fixed model/effort as properties. Reject symlinks, duplicate JSON keys,
  schema drift, and explicit CLI model/effort mismatch. A source hash mismatch degrades confidence.
- **DIRECT** → propose **model + effort** for this session, with the exact switch commands.

Selection stages are fixed:

1. `quality_floor` — choose the minimum sufficient model from depth and failure cost.
2. `availability` — remove unavailable candidates.
3. `cost_tiebreak` — use cost/quota only among candidates that already pass quality.

Never downgrade below the quality floor because a stronger model is unavailable; return
`BLOCKED_MODEL_AVAILABILITY`.

Cold-start prior (**tie-break only**, not a quality ranking): `codex` = integration, fan-in,
architecture, small direct implementation · `claude-main` = implementation from a settled spec ·
`grok-adversarial` = counter-examples, adversarial review · `agy-compat` = compatibility, format work.

### 5. Record — after the outcome is verified

```
python3 router.py record --task "..." --worker claude-main --outcome success \
  --attempt-id <unique> --verification-grade V3 \
  --verification-evidence "tests/test_x.py::test_y passed" \
  --axes "..." --axes-ext "..." --effort-requested max --effort-observed high \
  --task-family implementation --role direct --task-origin real
```

**Record every completed attempt — failures, aborts, and runs that ignored the recommendation too.**
Recording only your wins makes every route look good and poisons the learning loop.

Evidence overrides are isolated by `vendor + surface + model_family + task_family + role`.
Unrelated records never increase a cohort's sample. Existing lines are immutable: to correct a bad
attempt, append an `attempt_invalidation` event with the CLI. The append path refuses malformed
existing registries, duplicate IDs, secret-like strings, and raw provider transcript fields.

## Fable 5 rollout

Fable is not assumed equivalent or superior to Opus.

1. V2 controlled shadow: bounded real tasks, independent review, recommendation has no production
   authority.
2. V3 recommendation-only shadow: deterministic evidence, at least 20 all-success records across
   at least 3 real task instances, zero failures/partials, Anthropic+Claude surface only, and an
   independent verifier. V3 output is not model/effort selectable and has no execution authority.
3. Explicit opt-in: even a passing V3 sample remains `V3_SHADOW_PASS_OPT_IN_REQUIRED` until the owner
   opts in.

Synthetic fixtures test the policy but never count as live promotion evidence.

## Effort has a ceiling

- **High is the effective ceiling.** Beyond it you buy over-fitting to the letter of the spec, runaway
  self-polishing, and delegation overhead without insight.
- **If you hit the ceiling and still fail, raise the model tier — not the effort.**
- `xhigh`/`max` are **outside the normal ladder**. They need an explicit reason, a task that genuinely
  decomposes into sub-problems, and operator approval. Never pair a top tier with extended effort.
- **Change exactly one axis per retry.** Two changes at once means you learn nothing.

## Failure diagnosis — pick the right fix

| Symptom | Class | Fix |
|---|---|---|
| Shallow/wrong at low effort; spec and tools fine | `REASONING_DEPTH_FAILURE` | **effort +1 step** (same model) |
| Still wrong at High | `MODEL_CAPABILITY_FAILURE` | **raise the tier, not the effort** |
| Tests pass but it's literal-but-wrong / games the check | `SPEC_FAILURE` | **fix spec + DoD.** Do not raise compute; consider lowering effort |
| Clear bounded bug | `IMPLEMENTATION_BUG` | one bounded repair at the same model·effort |
| Auth / quota / network / CLI / permission | `TOOL_OR_INFRA_FAILURE` | **change nothing.** Fix the environment. Never record as a model-quality failure |
| Quality fine but slow/expensive; endless polishing | `OVERPROVISIONING` | lower one step + state a stop condition |
| Needs a different specialization | `ROLE_OR_VENDOR_MISMATCH` | propose another worker — **never switch vendor automatically** |

`python3 router.py` exposes this as `diagnose()`; each result names exactly one `change_axis`.

## Evidence thresholds — why one success proves nothing

| Verified similar attempts | Use |
|---|---|
| 0–2 | **anecdotal** — display only, never override the heuristic |
| 3–9 | **provisional** — tie-break only, and only V2/V3 with no related failures |
| 10+ | override candidate for a normal task |
| 20+ | override candidate for a high-failcost task |

Wilson 95% lower bound on an all-success run: **1/1 → 20.7%**, 3/3 → 43.8%, 10/10 → 72.2%, 20/20 → 83.9%.
A single success is not evidence of a good route.

Also required: **only V2/V3 with actual evidence count** · V1 is supporting · **V0 counts as zero** ·
≥3 distinct task instances · duplicate `attempt_id` collapses to one · an independent verifier
different from the producer · **any failure or partial blocks override**.

## Verification grades

| | Meaning |
|---|---|
| **V3** | deterministic tests, schema, exact output, render checks |
| **V2** | a human or independent reviewer judged it against a pre-stated DoD |
| **V1** | structured review by the conductor (not the executor) |
| **V0** | worker self-report or unevidenced satisfaction |

**A worker never approves its own result.** Producer and evaluator must differ. V0-only records are
stored but never influence a recommendation. V2/V3 records still count only inside their exact
evidence cohort.

## Honest limits — state these, do not paper over them

- **This is an operator-declared learning loop.** Nothing forces every attempt to be recorded, so
  `stats` reports *observed recorded outcomes*, not a true success rate. Expect selection bias toward
  successes.
- **requested ≠ observed.** `backends.json` and `--effort` record what was *asked for*. An org cap can
  silently clamp the applied effort. If `*_observed` is absent, the value is `requested_not_verified` —
  do not assert it as actual.
- **Effort ranks are not comparable across vendors.** `effort_rank` orders values **only inside one
  `comparison_scope`**. Claude `max`, Grok `high`, agy `model-high` (embedded in the model name) and
  Codex `config` (an unresolved indirection) are not on one scale. `router.compare_effort` raises
  `IncomparableScopes` rather than produce a false comparison. Compare **routes** by verified outcome,
  time and honestly-classified cost — never by effort number.
- **`capabilities.json` is a snapshot** of dispatcher config plus current model-selector evidence,
  captured 2026-07-25. Org caps, alias resolution and CLI updates drift. Old `captured_at` → lower confidence;
  never assume it is current.
- **agy is itself a multi-vendor surface** (it serves Gemini, Claude and GPT-OSS models). `surface` and
  `vendor` are separate fields for that reason.

## Output format

Keep it short (3–5 lines) and framed as a proposal:

> **DELEGATE → `grok-adversarial`** — verifiable=partial, failcost=high, adversarial review needed
> (evidence: anecdotal, n=0 — heuristic). Its loadout is grok-4.6 · high (fixed by backends.json;
> grok-4.5 는 남아 있으나 하위 티어다).
> Verifier: pre-stated DoD reviewed by someone other than the producer.
> I'll record the outcome so the next recommendation improves.

> **DIRECT — `gpt-5.6-terra · medium`** — Codex surface, mid-depth bounded task: this is the minimum
> sufficient quality floor. Switch: `/model gpt-5.6-terra`, `/effort medium`.
> If it fails the check, effort → high; if High still fails, raise the tier, not the effort.
