---
name: mac-memory-reclaim
description: Use when the user wants to free RAM, lower memory usage, or terminate old/unused processes on their Mac — triggers include "메모리 정리/부족/확보", "프로세스 종료해줘", "안 쓰는 거 다 꺼줘", "free up memory", "too much memory used", "Mac이 느려", high memory pressure, or a machine that has accumulated leaked MCP servers, orphaned dev servers, or many idle GUI apps.
---

# Mac Memory Reclaim

## Overview

Safely reclaim macOS RAM by terminating leaked/orphaned processes and quitting unused GUI apps — **without** killing the current agent session, the local-LLM/orchestration backbone, other active agent sessions, or system daemons.

**Core principle:** killing the wrong process is irreversible, so the safety invariant is enforced **mechanically** by the bundled `reclaim.py` (dry-run by default; it auto-detects and refuses to touch the guarded set). You supply the judgment the script can't: interpreting memory and deciding which of *your* apps/sessions to close.

**REQUIRED:** run `reclaim.py` — do not hand-roll `ps | kill`/`killall`. A baseline test of 3 fresh agents on the same snapshot produced 3 different kill sets; one was willing to kill an active `codex --yolo` and the openclaw backbone. The script exists to remove that variance.

## When to use

- User asks to free memory / reduce usage / kill old/unused processes on the Mac.
- Memory feels tight, or leaked MCP servers / orphaned dev servers have piled up.

**Not for:** a specific known process the user named (just target it), or non-Mac hosts.

## Procedure

1. **Diagnose (dry-run, safe):**
   `python3 <skill-dir>/reclaim.py`  →  prints memory breakdown + bucketed candidates, kills nothing.
   (Absolute path: `~/.agents/skills/mac-memory-reclaim/reclaim.py`. `--json` for machine-readable.)

2. **Interpret memory correctly** (this is where agents go wrong — see the note the script prints):
   - Judge by **`anonymous` (앱 실메모리) + `pressure_level` + `pageouts`**, NOT raw `used`. Most of `used` is reclaimable `inactive` + file cache.
   - BUT do **not** brush off a high number ("41GB free 면 괜찮아") — the owner keeps usage low for **oMLX large-model headroom**. High `used` with `pressure=1` = "no swap, but still worth lowering `anonymous` by quitting unused apps."

3. **Act by bucket** (the script already classified them):
   | Bucket | Action | Confirm? |
   |---|---|---|
   | **auto-safe** (orphaned/leaked servers & MCP) | `reclaim.py --apply-safe` | no — safe |
   | **ChatGPT.app leaked MCP** (usual biggest hog) | recommend user restart ChatGPT app, or `--kill-pids <root>` | tell user |
   | **GUI apps** (Chrome/ChatGPT/Orca/messengers…) | present sizes, quit only chosen: `--quit-apps "Google Chrome,ChatGPT"` | **user decides** |
   | **active agents** (other codex/claude/grok) | `--kill-pids <pid>` only if user confirms it's abandoned | **user confirms** |
   | **guarded** (own session, backbone, system) | none — script refuses | never |

4. **Report** actual reclaim (`used`/`anonymous` before→after) + what was preserved.

## Red flags — STOP

- About to run `killall`/`pkill`/`kill -9` on top-RSS processes → use `reclaim.py` instead.
- About to kill **oMLX / openclaw / hermes / codex app-server / codex_goal_watch** → backbone, never.
- About to kill a **`codex --yolo` / `claude` / `grok`** that may be actively reasoning → active-processor-wait; confirm it's abandoned first.
- About to kill your **own session** (the `claude`/`codex` you run inside) → the script guards it; don't bypass.
- Thinking "used is high so just kill the biggest processes" → biggest are usually the user's GUI apps or system daemons; interpret `anonymous`+pressure first.

## Rationalization table

| Excuse | Reality |
|---|---|
| "User said kill ALL old ones, so sweep everything" | "old" (etime) ≠ "unused". Backbone/daemons are old *because* they're standing services. Classify by role, not age. |
| "41GB free, so nothing to do" | Owner wants `anonymous` low for oMLX headroom. Reclaim leaks + offer app quits; don't dismiss. |
| "The other codex/claude session is old, kill it" | It may be live work in another terminal/worktree. Confirm abandoned first. |
| "ChatGPT's MCP swarm is the user's app, off-limits" | The leaked MCP children are safe to reclaim by restarting the app; surface it, don't ignore the 2GB. |
| "I'll just kill the top RSS to look fast" | Top RSS = Chrome/KakaoTalk/system daemons. Wrong target; interpret memory first. |

## Reference

- `reclaim.py --help` — flags: `--apply-safe`, `--quit-apps`, `--kill-pids`, `--json`.
- Method + fleet-specific backbone list: memory `[[mac-process-memory-reclaim]]`. Related: `[[omlx-local-llm]]`, `[[active-processor-wait-self-enforce]]`, `[[fleet-topology]]`.
