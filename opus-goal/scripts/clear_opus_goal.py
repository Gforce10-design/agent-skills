#!/usr/bin/env python3
"""Remove the opus-goal Stop hook from a Claude Code settings file, preserving everything else.

Identifies the hook by the sentinel embedded in its prompt (see set_opus_goal.py), so other
hooks, MCP settings, and any unrelated keys are left untouched. Cleans up empty Stop/hooks
containers and writes atomically. Pure stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

SENTINEL = "[opus-goal-hook]"


def settings_path(scope: str) -> str:
    if scope == "global":
        return os.path.expanduser("~/.claude/settings.json")
    return os.path.join(os.getcwd(), ".claude", "settings.local.json")


def load_settings(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        text = f.read().strip()
    return json.loads(text) if text else {}


def is_opus_goal_entry(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    inner = entry.get("hooks")
    if not isinstance(inner, list):
        return False

    def _has(h) -> bool:
        # opus-goal entries carry the sentinel in the judge prompt, and in the
        # auto-teardown command hook's statusMessage. Match either.
        return isinstance(h, dict) and any(
            isinstance(h.get(k), str) and SENTINEL in h[k]
            for k in ("prompt", "command", "statusMessage")
        )

    return any(_has(h) for h in inner)


def atomic_write(path: str, data: dict) -> None:
    parent = os.path.dirname(path) or "."
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
    ap = argparse.ArgumentParser(description="Remove the opus-goal Stop hook.")
    ap.add_argument("--scope", choices=["project", "global"], default="project",
                    help="project = ./.claude/settings.local.json (default), global = ~/.claude/settings.json")
    args = ap.parse_args()

    path = settings_path(args.scope)
    if not os.path.exists(path):
        print(f"nothing to clear ({path} missing)")
        return 0

    settings = load_settings(path)
    if not isinstance(settings, dict):
        print(f"ERROR: {path} is not a JSON object", file=sys.stderr)
        return 2

    hooks = settings.get("hooks")
    if not isinstance(hooks, dict) or not isinstance(hooks.get("Stop"), list):
        print("no opus-goal hook found (nothing to clear)")
        return 0

    before = len(hooks["Stop"])
    hooks["Stop"][:] = [e for e in hooks["Stop"] if not is_opus_goal_entry(e)]
    removed = before - len(hooks["Stop"])

    # prune empty containers so we don't leave dangling {} / []
    if not hooks["Stop"]:
        del hooks["Stop"]
    if not hooks:
        del settings["hooks"]

    atomic_write(path, settings)
    print(f"removed {removed} opus-goal hook(s) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
