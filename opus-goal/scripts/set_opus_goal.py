#!/usr/bin/env python3
"""Install an Opus-evaluator "opus-goal" Stop hook into a Claude Code settings file.

The built-in /goal command evaluates its completion condition with the configured small-fast
model (Haiku) and exposes no per-invocation model override. /goal is a wrapper around a
session-scoped prompt-based Stop hook; this script installs the equivalent hook but pins the
evaluator to a stronger model (Opus by default). It merges into the target settings file
preserving existing keys, uses the schema-correct nesting (Stop -> [{hooks: [{type:prompt}]}]),
writes atomically, and tags the hook with a sentinel so clear_opus_goal.py removes only this hook.

Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

# Embedded in the hook prompt; clear_opus_goal.py keys off this to remove only our hook.
SENTINEL = "[opus-goal-hook]"

PROMPT_TEMPLATE = (
    "{sentinel} 너는 goal 완료 평가자다(Opus). 명령 실행·파일 읽기 불가 — 어시스턴트가 "
    "transcript에 surface한 출력만 보고 yes/no + 한 줄 이유로 판정하라. 아래 [종결조건]이 그 출력으로 "
    "입증됐으면 yes, 아니면 no(+다음에 진행할 일). 증거 없는 주장(가짜 충족)은 no. 또는 어시스턴트가 "
    "{turn_cap}턴 초과를 보고하며 상태표를 출력했으면 yes로 종료. [종결조건] {condition} [입력] $ARGUMENTS"
)


def settings_path(scope: str) -> str:
    if scope == "global":
        return os.path.expanduser("~/.claude/settings.json")
    return os.path.join(os.getcwd(), ".claude", "settings.local.json")


def load_settings(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text) if text else {}


def is_opus_goal_entry(entry) -> bool:
    """A Stop entry is ours iff an inner hook carries the sentinel (judge prompt OR
    the auto-teardown command hook's statusMessage)."""
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks")
    if not isinstance(inner, list):
        return False

    def _has(h) -> bool:
        return isinstance(h, dict) and any(
            isinstance(h.get(k), str) and SENTINEL in h[k]
            for k in ("prompt", "command", "statusMessage")
        )

    return any(_has(h) for h in inner)


def atomic_write(path: str, data: dict) -> None:
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def main() -> int:
    ap = argparse.ArgumentParser(description="Install the opus-goal Opus-evaluator Stop hook.")
    ap.add_argument("--condition", required=True,
                    help="completion condition the evaluator checks (transcript-provable).")
    ap.add_argument("--model", default="claude-opus-4-8", help="evaluator model (default: claude-opus-4-8)")
    ap.add_argument("--turn-cap", type=int, default=150, help="safety turn ceiling (default: 150)")
    ap.add_argument("--timeout", type=int, default=60, help="hook eval timeout seconds (default: 60)")
    ap.add_argument("--scope", choices=["project", "global"], default="project",
                    help="project = ./.claude/settings.local.json (default), global = ~/.claude/settings.json")
    args = ap.parse_args()

    path = settings_path(args.scope)
    settings = load_settings(path)
    if not isinstance(settings, dict):
        print(f"ERROR: {path} is not a JSON object", file=sys.stderr)
        return 2

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        print(f"ERROR: existing 'hooks' is not an object in {path}", file=sys.stderr)
        return 2
    stop = hooks.setdefault("Stop", [])
    if not isinstance(stop, list):
        print(f"ERROR: existing 'hooks.Stop' is not an array in {path}", file=sys.stderr)
        return 2

    # Idempotent replace: drop any prior opus-goal entries before appending the new one.
    stop[:] = [e for e in stop if not is_opus_goal_entry(e)]

    prompt = PROMPT_TEMPLATE.format(sentinel=SENTINEL, turn_cap=args.turn_cap, condition=args.condition)
    stop.append({
        "hooks": [{
            "type": "prompt",
            "model": args.model,
            "timeout": args.timeout,
            "statusMessage": "opus-goal: Opus 평가 중",
            "prompt": prompt,
        }]
    })

    atomic_write(path, settings)
    clear = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clear_opus_goal.py")
    print(f"OK: installed opus-goal Stop hook (model={args.model}, turn_cap={args.turn_cap}, "
          f"scope={args.scope}) -> {path}")
    print("→ file-watcher가 라이브 반영(안 잡히면 세션 재시작).")
    print(f"→ teardown(루프의 일부): 종결 술어 도달 시 실행자가 마지막 단계로 다음을 실행한 뒤 종결한다 — "
          f'python3 "{clear}" --scope {args.scope}. (중도중단 수동 제거도 동일.)')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
