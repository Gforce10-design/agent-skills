---
name: ai-verification-pipeline
description: Use when building or verifying a complex / high-stakes AI deliverable (spec, plan, code, autonomous loop) that must be trusted before it ships or runs — runs a multi-layer verification pipeline (decompose → cross-vendor council → materialize → liveness-verify → fix-loop → harden → adversarial review → traceability gate) instead of single-pass generation. AUTO-APPLY even when not explicitly invoked. Trigger phrases (KR) 검증/철저히 검증/제대로 검증/적대적 리뷰/완주검증/끝까지 멈추지 않는 루프/믿을 수 있어/8프로 council/AI가 짠 코드 검증; (EN) verify thoroughly / adversarial review / can I trust this build / audit this AI-generated code / make this loop provably terminate. ALSO fire on any non-trivial multi-module build, autonomous /loop, or subagent-fanned-out code that must be correct — chain it as the verification layer of feature-add / project-genesis / deliver-deep. Catches what one pass hides: missing requirements, false-stop loops, agent drift, spec-adopted-but-not-built gaps.
---

# AI Verification Pipeline

Single-pass AI generation looks done and isn't. This skill runs a **layered verification pipeline** that each catch a different failure mode, ending in a **build-time traceability gate** so "the spec said it but nobody built it" fails automatically instead of slipping through green tests.

Validated 2026-06-15: this exact pipeline built a 22-module system, and its own adversarial-review + traceability layers caught **8 council-mandated boxes that were never built** despite a 532-test-green suite.

## When to use

- Building a non-trivial system, spec, plan, or autonomous loop where correctness matters and you want more than "it ran."
- User asks to "검증/verify thoroughly", "끝까지 멈추지 않는 루프", "적대적 리뷰", or to trust an AI-built artifact before commit/deploy.
- Any time you fan out subagents to build code — pair it with the traceability gate (§Stage 9), or missing boxes ship silently.

## The pipeline — scale stages to the task

Not every task needs all stages. A quick change needs Stage 8–9. A high-stakes autonomous loop needs all of them. Run only what the risk warrants; always end on the **traceability + commit gate**.

1. **Spec** — brainstorm → design doc. The contract everything else checks against.
2. **Decompose** — `Workflow` (ultracode) fan-out → detailed plan + an **adversarial completeness critic** agent (asks "what's missing/unverified?"). One pass under-specifies; the critic surfaces gaps.
3. **Cross-vendor council** — *only if the user explicitly says `8프로` / cross-vendor.* See §Legislation. **Diversity beats count**: a chair + genuinely different vendors (grok / Codex / gemini CLIs + Codex.ai / chatgpt webchats, in-project with sources refreshed) catch what same-model panels miss. Neutral framing, **refute-first**. Scaling agent *count* hits diminishing returns and invites adversarial persuasion — vary the vendor, not the headcount. **Operational routes** (how to actually get a large prompt into each surface without corrupting CJK or colliding with another session, CLI-vs-webchat repo-access weighting, honest "유효 N surfaces" reporting): `references/webchat-council-routes.md`.
4. **Materialize** — physically merge every adopted fix into the artifact's body / vectors / write-set. A plan that only *references* "C8 adopted" but leaves the stale box is a lie the executor will trip on. No override-by-reference.
5. **Liveness / completion verify** (loops & plans) — adversarial **scenario tracing**: trace the control flow against hostile scenarios (all-pass, a quarantined dependency, external-dependency-only residue, runaway, crash-between-ticks). Confirm it converges to a terminal state with **no false-stop and no infinite loop**. This is the lightweight form of formal workflow verification (LTL / Dafny).
6. **Fix → re-verify loop** — iterate Stage 5 until clean. (Self-Refine / Adaptive-Critique-Refinement.) Don't declare "completes" until the trace proves it.
7. **Harden** — production-robustness pass: concurrency, crash recovery, idempotency, the edges the liveness check surfaced.
8. **Adversarial code review** — `Workflow` fan-out of reviewers by *dimension* (correctness-vs-spec, security, cross-module drift, the control logic, the domain core) → **adversarially verify each finding** (a second agent tries to *refute* it; default to refuted if unsure) → synthesize must-fix. Read-only reviewers. This is the Adversarial-Review (reviewer + critic, structured disagreement) pattern.
9. **🥇 Traceability gate** — `scripts/traceability_gate.py`. Turn the spec's box/requirement list into a **manifest**; the gate asserts every box has its module + expected symbols + a referencing test. **Missing = nonzero exit = build failure.** This is the single highest-ROI layer: it makes "adopted but not built" and agent-drift impossible to hide behind a green suite. Run it as a barrier and ideally as a `Stop` hook. (ReqToCode: traceability as a structural property, not a post-hoc review.)
10. **Commit gate** — barrier (full test suite) + boundary check (no writes outside the allowlist) + traceability gate + no-secret scan, then commit explicit files only.

## Legislation (global)

`AlphaWorkflow` / `AWO` / invoking the `Workflow` tool ≠ `8프로` council. AlphaWorkflow is single-vendor Codex fan-out (Stages 2/8). The cross-vendor council (Stage 3) fires **only** when the user explicitly says `8프로` / `8프로세서` / `AWO 8 processors`. Don't auto-escalate a Workflow into a cross-vendor council.

## Hard rules / guards (learned the hard way)

- **cwd before every `Workflow`**: the Workflow tool inherits the shell's *persistent* cwd. A prior `cd tools/awo-runtime/...` makes fan-out agents unable to read repo-root docs (they silently build from the embedded prompt only → missing boxes) and misplace doc edits. **Reset to repo root immediately before launching any Workflow**, and pass agents repo-root-relative paths.
- **Green ≠ complete.** A passing suite only covers what was built. Always run the **traceability gate** (Stage 9) — that is what catches the boxes no test references.
- **Write-set serialization for parallel builds**: two agents writing the same file = corruption. Assign each agent a *distinct* file set; same-file work is one agent, serial. State this in every build-agent prompt.
- **Track / boundary**: forbidden paths (e.g. another repo, generated `.js`) are read-only — agents must never write them; verify with `git status` allowlist after each phase. Cross-boundary work is a handoff, not an autonomous action.
- **Destructive ops are surgical**: never `rm -rf` a directory that may hold tracked files to delete one stray artifact — delete the exact path, or `git status` first and `git restore` anything tracked you hit.
- **No-secret scan before commit**: scan staged files; distinguish real secrets from redaction-regex patterns and fake test fixtures (`...thisShouldNeverBe...`).
- **Pre-confirm irreversible/outward actions** (push, merge, deploy) even with authority — show exactly what, then do it.

## Failure modes this pipeline catches (and which stage)

| Failure mode | Caught by |
|---|---|
| Spec under-specified / requirement omitted | Stage 2 critic, Stage 3 council |
| Adopted fix never materialized (override-by-reference) | Stage 4, Stage 8 review |
| Loop false-stops / deadlocks / never terminates | Stage 5 liveness trace |
| Plausible-but-wrong review finding | Stage 8 adversarial verify (refute-first) |
| **Spec box never built / agent drift (green hides it)** | **Stage 9 traceability gate** ← the one most pipelines lack |
| Secret / boundary / push leaking into commit | Stage 10 commit gate |

## References

- `references/webchat-council-routes.md` — Stage 3 cross-vendor council mechanics: verified input routes per composer type (ProseMirror CJK trap + ASCII workaround, `form_input`/clipboard/CDP-bridge limits), collision avoidance across concurrent sessions, CLI invocation (grok / agy-Gemini / codex), and honest synthesis.
- `references/sota-mapping.md` — each stage ↔ its 2025–26 SOTA paper/product + sources, and the upgrade backlog.
- `scripts/traceability_gate.py` — the Stage 9 gate. `python3 traceability_gate.py --manifest <m.json> --src <dir> --tests <dir>`.
