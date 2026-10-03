---
name: cross-vendor-model-effort-router
description: "Choose model/effort or direct/delegate routes and automatically run explicitly routed tasks on the selected model. Use when route selection or route-and-run is requested."
---

# Cross-Vendor Model & Effort Router

Current router version: 2.7.0. Every CLI recommendation uses the shared read-only
`provider_catalog.py` resolver for DIRECT and catalog-enabled DELEGATE workers. `router.py catalog
--provider all` displays every observed row, eligibility reasons, exact supported effort, current
versions per family and alternatives. It never truncates the inventory to three IDs. Codex uses
current-account app-server `model/list` including hidden rows; hidden rows remain visible but cannot
be selected. Claude uses bounded SDK control initialize metadata (zero user messages), Grok and AGY
use their native `models` commands. Observed counts are snapshots, not hard-coded limits: the
2026-10-03 discovery contained 12 Claude live rows, 4 Grok rows and 18 AGY rows.

Use `recommend ... --surface codex|claude|grok|agy --model <observed-ID-or-latest[:family]>
[--effort <supported-value>]` for an explicit selection. `--model` is separate from experimental
`--candidate-model`; Fable remains shadow-only. Explicit model selection reports an unverified
quality override rather than claiming the automatic quality floor passed. Omit `--model` to select
the current version of the policy-selected family. Unknown Grok effort metadata permits only the
native default; an explicit unsupported effort fails. Claude Haiku omits the effort flag, and AGY
binds the effort embedded in the exact observed human CLI label.

Catalog metadata proves neither quota nor generation nor provider-signed runtime identity. Claude
aliases are distinct from canonical expected IDs: a single fresh post-probe native `cc` cache can
map a public name to an expected ID, but its account identity remains unverified. Without that
mapping live aliases remain selectable with empty usage-evidence keys; they cannot satisfy required
model-usage proof. Never merge ambiguous account caches or read the `ccd` surface. Cache-only
Claude/Codex fallback is visible and identity-unverified, not selectable. Native Claude `staleAt`
is respected; live Claude/Grok/AGY metadata expires after 15 minutes, Codex after 24 hours. The
resolver rechecks expiry on selection. Explicit `--model-availability` applies to the final model.

Pick the cheapest route that still passes a real check, execute the selected route when explicitly
asked to route-and-run, escalate only on verified failure, and learn from recorded outcomes.

## What this skill is NOT

It does **not** mutate the dispatcher, `backends.json`, global model defaults, or any hook during a
routing call. It creates no second dispatcher or authority path. It may launch one bounded run through
an available native worker tool or `codex exec` when the user explicitly invokes auto-routing. It
never approves its own results.

## Legacy advisor replacement contract

This skill **supersedes `gpt-model-effort-advisor`** and is the **sole automatic owner** of model
recommendation, effort recommendation, implicit pre-task routing, direct-vs-delegate decisions,
worker selection, cost/latency/context trade-offs, failure escalation, and **new outcome recording**.
The legacy skill stays installed for rollback but must **not** be a competing automatic trigger.

For DIRECT OpenAI/Codex routes it preserves the legacy behaviour: official-family tier
recommendation, native effort recommendation, the original four axes, High as the normal ceiling,
tier escalation after High, spec/DoD correction instead of blind effort escalation, legacy registry
lookup, and `session` reporting where observable.

The legacy `registry.jsonl` is **read-only**. All new outcomes — including GPT DIRECT outcomes —
are written only to this skill's registry.

## Role and model binding

DELEGATE selects a stable worker role and then a current catalog model/effort pair within that
worker's existing permission profile. Codex main/critic/recompute roles stay distinct; Claude,
Grok and AGY roles use the same resolver when their reviewed backend policy enables
`provider-catalog-v1`. A missing trusted writer profile is a hard mismatch. The shared resolver and
its Codex inventory dependency are hash-pinned by the backend contract.

Router DELEGATE recommendations always forward the selected pair to the existing dispatcher.
A bare dispatcher invocation without a pair preserves its legacy default. Routing does not mutate
backend allowlists, executable pins, account staging, permissions, history or registry evidence.
DIRECT metadata uses the configured current CLI/account; delegated Codex metadata uses native
`~/.codex`, the account source already staged by the dispatcher, rather than the conductor account.

## Automatic execution contract

An explicit `$model-router <task>` invocation or a request to choose a model and run the task means
**route-and-run**. A question that only asks which model to use remains recommendation-only.

1. Run a fresh `router.py recommend` call and inspect its machine-readable result.
2. For `DIRECT`, reuse the current agent only when its model and effort are both verifiably equal to
   the recommendation. Otherwise launch one bounded Codex worker with the exact recommended model
   and effort. Prefer the native worker/subagent tool when available; otherwise use the returned
   `execution_contract.fallback_argv`, pass the task over stdin, and preserve the current cwd and
   existing permission posture. Non-Codex DIRECT currently reports session selection only, with
   no headless fallback argv or guessed slash command. Use a matching current provider session or
   its verified delegate adapter. Do not interpolate the task into shell source.
3. For `DELEGATE`, execute the validated worker plan through the existing dispatcher. Pass the
   returned model and effort only when `model_effort_selectable=true`; otherwise preserve the
   worker's legacy loadout only when no catalog-enabled pair is available.
4. For `PLAN_FIRST`, finish the bounded specification first and rerun the router. For
   `NEEDS_PREFERENCE`, `BLOCKED_*`, or an unavailable selected model, report the exact blocker rather
   than silently choosing another model.
5. Bring the worker result and verification evidence back into the current conversation, then
   record the outcome only after verification.

Codex currently cannot let a skill mutate the model of the already-running interactive turn. The
automatic path therefore runs the task on the selected model while the conductor session stays on
its existing model. Say `executed on <model> · <effort>`; never claim the visible session switched.

## Engine: `router.py`

Standard library only. Always use the CLI — never hand-edit the JSONL.

Every explicit recommendation request and every real model-transition recommendation requires a
**fresh `router.py recommend` call for the next bounded action**. Reading this file, reusing an
earlier result, or hand-picking a model from generic labels such as “plan” and “implementation” does
not count. Report the returned `router_version` and the four declared axes. If an already-open
session previously used an older router version, rerun the command; the executable on disk is the
current source of truth. The CLI returns `NEEDS_AXES` with exit 2 when any four core axes or the five
break-even axes are missing; do not replace that failure with a hand-written recommendation. Supply
the missing classification and rerun it.

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

### 0. Bind the provider surface and catalog

Pass `--surface codex|claude|grok|agy` whenever DIRECT is possible. Missing/unknown surface returns
`NEEDS_SURFACE`; the router never guesses. DIRECT Codex discovers its ancestor runtime/account;
use `--codex-home` and the configured `--executable` when outside that process tree. DELEGATE
resolves the worker's configured CLI and native account staging context, not the conductor account.

Every catalog-backed choice refreshes safe metadata, then resolves the current policy family or an
explicit observed ID. All rows remain visible, including older alternatives and unknown/ineligible
rows with reasons. Static `capabilities.json` names are historical/default policy inputs, not the
current selectable inventory. No static/cache fallback may claim a fresh selectable account model.
Claude's live aliases and exact expected identities remain distinct; ambiguous/stale caches are not
merged. `--model` permits observed alternatives with an explicit unverified quality override, while
Fable is still restricted to its separate shadow experiment.

The reviewed `provider-catalog-v1` backend policy permits current pairs for all four providers;
selection validates the shared resolver/dependency hashes and exact model/effort metadata without
mutating backends. Legacy `router-v1`/fixed policies retain their prior allowlists and defaults.
Permissions, worker roles, executable pins, native account staging and usage-proof gates remain
independent of catalog selection.

### 1. Classify

Four core axes (same vocabulary as the GPT advisor):
`--axes "verifiable=yes|partial|no,failcost=low|mid|high,volume=high|low,depth=shallow|mid|deep"`

Classify the **next bounded action**, not the overall project, later review stage, or domain prestige.
This is the main protection against the false `Astra/high` versus `Terra/medium` split:

- `depth=shallow`: deterministic edit, command, formatting, or mechanical transformation.
- `depth=mid`: bounded implementation or test work with a settled design and local reasoning.
- `depth=deep`: the next action itself requires new architecture, semantic policy, or several
  coupled deductions. The words “planning”, “security”, “finance”, or “large project” do not make it deep.
- `failcost=high`: a wrong result can escape the next independent check and cause material,
  irreversible, live, financial, or security harm. A complex task with tests and review before any
  effect is normally `mid` at that step.
- `verifiable=yes`: deterministic tests, schema checks, exact evidence, or a bounded observable
  result decide this step. Use `partial` only for irreducible judgment, and `no` only when there is no
  independent check.

Do not substitute the configured Advisor model for a direct-session recommendation. Advisor is a
separate independent reviewer; direct model selection always comes from this CLI.

`volume` means the amount of output the **model must generate**, not the number of input rows or
files a deterministic tool processes. A million-row script with a ten-line report can still be
`volume=low`. Check the tool-first route before assigning an LLM to uniform work.

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

### 2b. The optimization-goal gate

Catalog-enabled roles can use a selected delegated loadout. Legacy backend profiles remain
pinned. Apply the old no-economy preference gate only to a genuinely fixed legacy worker. A task routed to `codex-main`, `codex-critic`, or `codex-recompute` may proceed with the
selected allowlisted tier without asking for an optimization preference.

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

- **DELEGATE** → infer the role first. Implementation selects `codex-main`; patch/code/regression
  review selects `codex-critic`; independent numerical/calculation reproduction selects
  `codex-recompute`; general, compatibility, and adversarial review retain their existing worker
  fit rules. For a catalog-enabled role, select model/effort with the same task axes as DIRECT and bind them to
  the dispatcher argv. Reject symlinks, duplicate JSON keys, schema drift, allowlist escape, and
  model/effort pair mismatch. A source hash mismatch degrades confidence.
- **DIRECT** → propose **model + effort** for this session. Codex retains its verified switch/fallback contract; other providers expose selection metadata with no guessed switch command or headless fallback.

Selection stages are fixed:

1. `quality_floor` — depth chooses the base model; high failure cost raises the model one tier;
   unverifiable output raises it another tier. For Codex this makes Sol the normal deep-work tier
   and reserves Astra for compounded risk instead of treating `deep OR failcost=high` as identical.
   Partial or absent verification raises effort independently, capped at High.
2. `availability` — remove unavailable candidates.
3. `cost_tiebreak` — use cost/quota only among candidates that already pass quality.

Never downgrade below the quality floor because a stronger model is unavailable; return
`BLOCKED_MODEL_AVAILABILITY`.

Cold-start prior (**tie-break only**, not a quality ranking): `codex-main` = delegated implementation
under the current Claude-conductor flavor · `codex-critic` = code/patch/regression review ·
`codex-recompute` = independent calculation or numerical reproduction · `claude-main` = general
review · `grok-adversarial` = counter-examples and adversarial review · `agy-compat` = compatibility
and format work.

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

Include the CLI `router_version`, the four axes, and one relevant boundary from
`classification_receipt.axis_sensitivity`. This makes an inflated axis visible instead of silently
collapsing every plan to Astra and every implementation to Terra.

> **DELEGATE → `grok-adversarial`** — verifiable=partial, failcost=high, adversarial review needed
> (evidence: anecdotal, n=0 — heuristic). Its current catalog-bound loadout is grok-4.7 · high
> (metadata snapshot; older IDs remain available as explicit alternatives).
> Verifier: pre-stated DoD reviewed by someone other than the producer.
> I'll record the outcome so the next recommendation improves.

> **DIRECT — `gpt-6-sol · medium`** — Codex surface, mid-depth bounded task: this is the minimum
> sufficient quality floor. Auto-run: selected model worker launched; the conductor session remains
> unchanged.
> If it fails the check, effort → high; if High still fails, raise the tier, not the effort.


## Detailed discovery context

Use this skill before multi-file, multi-step, batch/repeated, architecture, or high-failure-cost work when no model, effort, or execution route has been deliberately selected. Also recommends a model/effort or delegate worker when asked directly, judges direct-vs-delegate, and handles cost cuts, post-failure escalation, and outcome recording. Sole owner of model/effort/worker routing (supersedes gpt-model-effort-advisor); returns DIRECT, PLAN_FIRST, DELEGATE, NEEDS_SURFACE, or NEEDS_PREFERENCE. 한국어의 모델·effort·워커 라우팅, 직접·위임 판단, 비용 절감, 실패 에스컬레이션, 결과 기록 요청에도 사용한다. Do not use for trivial execution requests needing no route selection, incidental model names in code, logs, or config, or informational explanations/comparisons of model commands, capabilities, prices, or benchmarks. Do not reconsider an already fixed or normally progressing route unless troubleshooting, rerouting, or recording.
