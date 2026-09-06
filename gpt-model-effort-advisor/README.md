# gpt-model-effort-advisor

A codex skill that recommends the right **GPT-5.6 model tier** (Luna / Terra / Sol)
and **reasoning effort** (Low … Ultra) for a task, learns from your real outcomes,
diagnoses failures, and reports the live session's model/effort.

It **recommends and records**; you decide and switch. Codex does not change the
model per turn on its own.

## What it does

- **Recommend** a starting `tier · effort` from the task's shape (verifiability,
  failure cost, throughput, reasoning depth), plus an escalation rule.
- **Learn** — records which combos worked or failed; personal history overrides
  the cold-start heuristics over time.
- **Diagnose** a poor result and pick the right fix (raise effort vs. raise the
  model tier vs. lower both).
- **Session state** — reads the current model and effort in real time.

## Install (codex)

```bash
skills add dandacompany/dante-skills@gpt-model-effort-advisor -g -y --copy -a codex
```

(Requires the [Skills CLI](https://skills.sh/): `npm i -g skills`. Installs to the
codex skills directory.)

The skill loads automatically when you ask which model/effort to use, report a
bad result, or ask what model the session is running.

## Files

- `SKILL.md` — the skill instructions and decision framework.
- `registry.py` — engine: `session`, `record`, `query`, `stats` (stdlib only).
- `registry.jsonl` — your outcome log (created on first record; git-ignored).

## Notes

- The registry starts empty and fills from your usage.
- Guidance is principle-based (a smaller model is often enough for verifiable
  work; reasoning effort has a ceiling; escalate only on verifiable failure).
  Re-measure when models change — your recorded outcomes keep it current.
