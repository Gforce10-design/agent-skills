# SOTA mapping — each pipeline stage ↔ research/product (2025–26)

Why this pipeline is shaped the way it is, with sources. Surveyed 2026-06-15.

## Stage ↔ SOTA

| Stage | SOTA name | Key takeaway |
|---|---|---|
| 2 Decompose + completeness critic | agentic decomposition + critic | one pass under-specifies; a critic that asks "what's missing/unverified" recovers gaps |
| 3 Cross-vendor council | **Multi-Agent Debate** | **diversity > count.** Scaling agent *count* → diminishing returns + adversarial-persuasion risk. Vary the *vendor*, not the headcount |
| 4 Materialize | — | adopted-but-only-referenced fixes are a lie the executor trips on |
| 5 Liveness verify | **Agentproof** (workflow-graph static verification, LTL), **SEVerA** (verified synthesis, Dafny) | deterministic scenario tracing is the lightweight form of these |
| 6 Fix→re-verify | **Self-Refine / MAgICoRe / Adaptive-Critique-Refinement** | Solver→Reviewer→Refiner loop, step-wise reward |
| 8 Adversarial code review | **Adversarial Review** (2026) — main + reviewer + critic, structured disagreement | refute-first; trustworthy cooperation needs *evidence-grounded disagreement*, not agreement. Whole-repo context (Greptile-style) > diff-only (CodeRabbit) for cross-module bugs |
| 9 Traceability gate | **ReqToCode** — traceability as a structural property / build failure | "invariants must be enforced by a mechanism **external to the proposer** — learned behavior is unreliable" (Nidus). The single highest-ROI layer |
| 10 Execution check (optional) | **RepoZero** — execution-based black-box validation of full-repo generation | run the built artifact, don't just read it |

## Verdict on the pipeline

Near-SOTA. The one structural weakness in a naive version is **traceability**: catching "spec adopted but never built" via *post-hoc review* instead of a *build-time gate*. Stage 9 (`traceability_gate.py`) closes it — proven 2026-06-15 to catch 8 unbuilt council boxes that a 532-test-green suite hid.

## Upgrade backlog (beyond this skill's defaults)

1. **Verifier/reward model** to automate Stage 5/8 (vs manual scenario tracing).
2. **Execution-based validation** (RepoZero) as an extra Stage 10 layer.
3. **Formal workflow verification** (Agentproof / LTL) for loop liveness where stakes justify it.
4. **DSPy** to optimize council/review prompts.
5. **Self-improving loop** (A Self-Improving Coding Agent) — the pipeline tunes its own prompts over runs.

## Tooling / skill-ification

No single framework fits, because the cross-vendor diversity council needs *other vendors* (grok/gemini/chatgpt) that same-vendor systems (Claude **Agent Teams**, LangGraph, AutoGen, CrewAI) can't supply. Composition:

- **Spine** = this Claude Code skill (`SKILL.md`).
- **Fan-out / review** = the `Workflow` tool (single-vendor Claude).
- **Cross-vendor council** = external CLI / webchat wrappers the skill invokes.
- **Gates** = Claude Code **hooks** (Stop / SubagentStop): run tests, block forbidden writes, **run the traceability gate**.
- **The missing piece** = `scripts/traceability_gate.py` (Stage 9).

## Sources

- Adversarial Review — https://openreview.net/forum?id=fOHvpLs6zp
- Multi-Agent Debate, persuasion limits — https://www.nature.com/articles/s41598-026-42705-7
- Multi-Agent Debate judges — https://openreview.net/forum?id=Vusd1Hw2D9
- ReqToCode (traceability=build failure) — https://arxiv.org/html/2603.13999
- Nidus (external-enforced invariants) — https://arxiv.org/pdf/2604.05080
- Agentproof (workflow static verification) — https://arxiv.org/pdf/2603.20356
- SEVerA (verified synthesis) — https://hf.co/papers/2603.25111
- MAgICoRe — https://hf.co/papers/2409.12147
- CodeCoR — https://hf.co/papers/2501.07811
- RefineCoder / ACR — https://hf.co/papers/2502.09183
- RepoZero — https://hf.co/papers/2605.07122
- A Self-Improving Coding Agent — https://hf.co/papers/2504.15228
- Claude Code full stack (skills/subagents/hooks) — https://alexop.dev/posts/understanding-claude-code-full-stack/
- Agent Teams + Skills 2026 — https://www.agensi.io/learn/claude-code-agent-teams-skills
- LangGraph vs AutoGen vs CrewAI 2026 — https://tensoria.fr/en/blog/multi-agent-orchestration-comparison
- Greptile vs CodeRabbit — https://www.greptile.com/content-library/best-ai-code-review-tools
