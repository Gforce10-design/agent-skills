# Trigger map — how this skill auto-applies even when not invoked by name

The user's requirement: *"내가 스킬 호출을 깜빡하더라도 자동으로 적용이 되도록"* — apply the
verification pipeline even when nobody types `/ai-verification-pipeline`. Three independent
layers make that happen; each catches what the others miss.

## Layer 1 — `description` auto-invoke (native, primary)

Claude Code surfaces a skill when the live `description` matches the task. The description
in `SKILL.md` is written to fire on the phrases below — it carries `AUTO-APPLY even when not
explicitly invoked` plus the trigger list so the matcher has explicit hooks, not just a topic.

This is attention-based (the model decides), so it is necessary but not sufficient on its own —
Layers 2 and 3 backstop the cases where the model's attention is elsewhere mid-build.

## Layer 2 — `auto-intent-router` routing row (cross-skill)

`~/.claude/skills/auto-intent-router/SKILL.md` has a classification row mapping the trigger
words to `ai-verification-pipeline`. Crucially it is documented there as a **verification
*layer*, not an exclusive category**: `project-genesis` / `feature-add` / `deploy-pipeline`
chain it at their verify step whenever they produce a non-trivial multi-module build, an
autonomous `/loop`, or subagent-fanned-out code. So even when the user's prompt routes to a
*build* workflow, the verification layer rides along.

## Layer 3 — `UserPromptSubmit` hook (deterministic, opt-in)

The only layer that fires on **every** prompt regardless of model attention. It is **not
installed by default** because it injects on every turn and modifying `~/.claude/settings.json`
hooks is a standing-config change that needs explicit user consent. When the user wants the
hardest guarantee, add a `UserPromptSubmit` hook that scans the prompt for the trigger regex and
injects a one-line hint, e.g.:

```
[verification-hint] This prompt matches a high-stakes-build / verification trigger.
Consider chaining ai-verification-pipeline (traceability gate is mandatory before commit).
```

Keep it a *hint*, not a forced skill load — the router and the model still decide. A hint label
is cheap and reversible; a forced load on every prompt is noisy and fights user intent.

## Trigger phrases (canonical list)

Keep these in sync with the `SKILL.md` `description` and the `auto-intent-router` row.

**KR** — 검증 · 철저히 검증 · 제대로 검증 · 적대적 리뷰 · 코드 리뷰(고위험) · 완주검증 ·
끝까지 멈추지 않는 루프 · 루프가 끝까지 가는지 · 믿을 수 있어 · 신뢰할 수 있어 ·
8프로 council · 크로스벤더 council · AI가 짠 코드 검증 · 빌드 커밋 전 검증

**EN** — verify thoroughly · adversarial review · audit this AI-generated code ·
can I trust this build · prove this loop terminates · make the loop provably terminate ·
traceability / requirements-coverage gate · is the spec actually built

**Structural triggers (no keyword needed)** — fire the pipeline's verification layer whenever,
regardless of phrasing, the work is: a non-trivial multi-module build · an autonomous `/loop` ·
subagent / `Workflow` fan-out that wrote code · anything about to be committed or deployed where
"it ran" is not enough. These are the cases a green suite hides gaps in — exactly what Stage 9
(traceability gate) exists to catch.

## What "auto-apply" does NOT bypass

- **Cross-vendor `8프로` council still requires the explicit `8프로` word** (see `SKILL.md`
  §Legislation). A trigger match runs the single-vendor layers, never auto-escalates to a
  cross-vendor council.
- **Irreversible/outward actions still pre-confirm** (push, merge, deploy) even when the
  pipeline runs automatically.
