#!/usr/bin/env python3
"""Registry engine for gpt-model-effort-advisor.

Learns which (task -> model + effort) combos worked or failed, and reads the
live session's model/effort. Standard library only.

Subcommands:
  session                      Read the current session's model + effort.
  record ...                   Append a task outcome (success/fail/partial).
  query "<task>" [--axes ...]  Find similar past successes/failures.
  stats                        Registry summary.

Registry lives next to this file as registry.jsonl (append-only JSON lines).
"""
import argparse
import glob
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "registry.jsonl"
_WORD = re.compile(r"[a-z0-9À-￿]+")


def _tokens(s):
    return set(_WORD.findall((s or "").lower()))


# ---------- state: read the live session's model + effort ----------
def _ps_cmd(pid):
    try:
        return subprocess.run(["ps", "-o", "command=", "-p", str(pid)],
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _ps_ppid(pid):
    try:
        out = subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)],
                             capture_output=True, text=True).stdout.strip()
        return int(out) if out else None
    except Exception:
        return None


def _codex_launch_args():
    """Walk up the process tree to the ancestor codex process and read its
    -m / -c model_reasoning_effort launch overrides. Correct even early in a
    session before the rollout file has recorded the model."""
    pid = os.getppid()
    for _ in range(12):
        if not pid or pid <= 1:
            break
        cmd = _ps_cmd(pid)
        if "codex" in cmd and ("--" in cmd or " -m " in cmd or "model" in cmd):
            m = re.search(r"(?:-m|--model)\s+(\S+)", cmd)
            e = re.search(r'model_reasoning_effort\s*=\s*"?([a-z_]+)"?', cmd)
            cm = re.search(r'(?:-c\s+)?\bmodel\s*=\s*"?(gpt[\w.\-]+)"?', cmd)
            model = m.group(1) if m else (cm.group(1) if cm else None)
            if model or e:
                return model, (e.group(1) if e else None)
        pid = _ps_ppid(pid)
    return None, None


def cmd_session(_args):
    home = os.environ.get("CODEX_HOME") or os.environ.get("ORCA_CODEX_HOME")
    model = effort = src = None
    # 1) Newest rollout (reflects /model changes; may be empty very early).
    if home:
        sess = Path(home) / "sessions"
        rolls = sorted(glob.glob(str(sess / "**" / "rollout-*.jsonl"), recursive=True),
                       key=lambda p: os.path.getmtime(p), reverse=True)
        if rolls:
            txt = Path(rolls[0]).read_text(encoding="utf-8", errors="ignore")
            m = re.findall(r'"model"\s*:\s*"([^"]+)"', txt)
            e = re.findall(r'"(?:reasoning_effort|effort)"\s*:\s*"([^"]+)"', txt)
            if m:
                model, src = m[-1], "session rollout"
            if e:
                effort = e[-1]
    # 2) codex launch args (accurate early / for overrides).
    if not model or not effort:
        am, ae = _codex_launch_args()
        if not model and am:
            model, src = am, "codex launch args"
        if not effort and ae:
            effort = ae
    # 3) config.toml default (inaccurate if the session overrode it — flagged).
    if not model or not effort:
        cfg = Path.home() / ".codex" / "config.toml"
        if cfg.exists():
            t = cfg.read_text(encoding="utf-8", errors="ignore")
            mm = re.search(r'^\s*model\s*=\s*"([^"]+)"', t, re.M)
            ee = re.search(r'^\s*model_reasoning_effort\s*=\s*"([^"]+)"', t, re.M)
            if not model:
                model, src = (mm.group(1) if mm else None), "config default (inaccurate if overridden)"
            if not effort:
                effort = ee.group(1) if ee else None
    print(json.dumps({"model": model, "effort": effort, "source": src}, ensure_ascii=False))


# ---------- record an outcome ----------
def cmd_record(a):
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "task": a.task,
        "axes": a.axes,               # e.g. "verifiable=yes,failcost=low,volume=high,depth=shallow"
        "model": a.model,
        "effort": a.effort,
        "outcome": a.outcome,         # success | fail | partial
        "reason": a.reason or "",
        "cost": a.cost,
        "minutes": a.minutes,
        "notes": a.notes or "",
    }
    with open(REGISTRY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({"recorded": rec}, ensure_ascii=False))


def _load():
    if not REGISTRY.exists():
        return []
    out = []
    for line in REGISTRY.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def _axes_set(s):
    return set(x.strip().lower() for x in (s or "").split(",") if x.strip())


# ---------- query similar past outcomes ----------
def cmd_query(a):
    recs = _load()
    qt = _tokens(a.task)
    qa = _axes_set(a.axes) if a.axes else set()
    scored = []
    for r in recs:
        rt = _tokens(r.get("task"))
        kw = len(qt & rt) / (len(qt | rt) or 1)                  # keyword Jaccard
        ax = len(qa & _axes_set(r.get("axes"))) / 4 if qa else 0  # 4-axis agreement
        score = kw * 0.6 + ax * 0.4
        if score > 0.08:
            scored.append((round(score, 3), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:6]
    succ = [r for _s, r in top if r.get("outcome") == "success"]
    fail = [r for _s, r in top if r.get("outcome") == "fail"]

    combo = {}
    for r in succ:
        k = f"{r.get('model')} · {r.get('effort')}"
        combo[k] = combo.get(k, 0) + 1
    best = sorted(combo.items(), key=lambda kv: kv[1], reverse=True)

    print(json.dumps({
        "matched": len(top),
        "best_success_combos": [{"combo": k, "wins": v} for k, v in best],
        "recent_successes": [{"combo": f"{r['model']} · {r['effort']}", "task": r["task"],
                              "notes": r.get("notes", "")} for r in succ[:3]],
        "avoid_failures": [{"combo": f"{r['model']} · {r['effort']}", "task": r["task"],
                            "reason": r.get("reason", "")} for r in fail[:3]],
    }, ensure_ascii=False, indent=2))


def cmd_stats(_a):
    recs = _load()
    by = {}
    for r in recs:
        k = f"{r.get('model')}·{r.get('effort')}"
        d = by.setdefault(k, {"success": 0, "fail": 0, "partial": 0})
        o = r.get("outcome", "partial")
        d[o] = d.get(o, 0) + 1
    print(json.dumps({"total": len(recs), "by_combo": by}, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="model-effort registry engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("session").set_defaults(fn=cmd_session)

    r = sub.add_parser("record")
    r.add_argument("--task", required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--effort", required=True)
    r.add_argument("--outcome", required=True, choices=["success", "fail", "partial"])
    r.add_argument("--axes", default="")
    r.add_argument("--reason", default="")
    r.add_argument("--cost", default=None)
    r.add_argument("--minutes", default=None)
    r.add_argument("--notes", default="")
    r.set_defaults(fn=cmd_record)

    q = sub.add_parser("query")
    q.add_argument("task")
    q.add_argument("--axes", default="")
    q.set_defaults(fn=cmd_query)

    sub.add_parser("stats").set_defaults(fn=cmd_stats)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
