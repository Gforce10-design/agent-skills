#!/usr/bin/env python3
"""
reclaim.py — safe macOS memory / process reclamation engine (AlphaMate fleet).

WHY a script instead of prose: killing the wrong process is irreversible. The
safety invariant — NEVER kill (a) the current agent session tree, (b) the
local-LLM / orchestration backbone, (c) other ACTIVE agent sessions, or (d)
macOS system daemons — must be enforced MECHANICALLY, not left to an agent that
skims "just free memory fast". Baseline test: 3 fresh agents given the same
snapshot produced 3 different kill sets; one was willing to kill an active
`codex --yolo` and the openclaw backbone TUI. A script removes that variance.

DEFAULT = DRY-RUN: prints a memory diagnosis + bucketed candidates, kills nothing.
Acting requires explicit flags, and every kill path RE-CHECKS the guard set and
aborts if it would touch anything guarded.

Usage:
  reclaim.py                      # dry-run: diagnose + list buckets (safe)
  reclaim.py --apply-safe         # kill ONLY the auto-safe bucket (orphaned/leaked)
  reclaim.py --quit-apps "Google Chrome,ChatGPT"   # graceful-quit named GUI apps
  reclaim.py --kill-pids 90113    # kill specific PID subtree(s) (guard-checked)
  reclaim.py --json               # machine-readable buckets (for the agent to read)
"""
import argparse, json, os, re, signal, subprocess, sys, time

PAGE_DEFAULT = 16384  # Apple Silicon page size; overridden from vm_stat header

# Command patterns that must NEVER be killed — the operational backbone.
BACKBONE = re.compile("|".join([
    r"oMLX", r"openclaw", r"hermes", r"tui_gateway",
    r"codex app-server", r"codex_goal_watch", r"caffeinate",
    # C2C deliberately detaches its active per-workspace bridge to launchd.
    # ppid == 1 is expected here and must not make `--apply-safe` stop it.
    r"/codex-with-chatgpt/(?:dist|src)/cli/index\.(?:js|ts) serve --workspace(?: |$)",
    # alpha-c2c's bundled bridge detaches the same way.
    r"/alpha-c2c-(?:claude|codex)/scripts/bridge\.py serve --workspace(?: |$)",
]), re.I)
# Agent CLIs — protected unless proven leaked/orphaned (active-processor-wait).
AGENT = re.compile(r"(^|/| )(claude|codex|grok)( |$|--)", re.I)
# Leftover dev/preview servers that commonly leak as orphans (ppid==1).
LEAKED_SERVER = re.compile(r"\b(serve|http-server|http\.server|vite|webpack|next dev|live-server|nodemon|serve\.js)\b", re.I)
MCP = re.compile(r"(mcp|playwright|chrome-devtools)", re.I)
SYSTEM_PATH = re.compile(r"^/(System|usr/libexec|usr/sbin|usr/bin|sbin|Library/Apple)")
APP_MAIN = re.compile(r"/Applications/([^/]+\.app)/Contents/MacOS/")


def sh(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True).stdout
    except Exception:
        return ""


def snapshot():
    out = sh("ps", "-axo", "pid=,ppid=,rss=,etime=,comm=,args=")
    procs = {}
    for line in out.splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        pid, ppid, rss, etime, comm, args = parts
        try:
            pid, ppid, rss = int(pid), int(ppid), int(rss)
        except ValueError:
            continue
        procs[pid] = dict(pid=pid, ppid=ppid, rss=rss, etime=etime, comm=comm, args=args)
    return procs


def children_map(procs):
    m = {}
    for p in procs.values():
        m.setdefault(p["ppid"], []).append(p["pid"])
    return m


def subtree(root, kids):
    out, stack = set(), [root]
    while stack:
        x = stack.pop()
        if x in out:
            continue
        out.add(x)
        stack += kids.get(x, [])
    return out


def ancestors(pid, procs):
    out = []
    seen = set()
    while pid in procs and pid not in seen:
        seen.add(pid)
        out.append(pid)
        pid = procs[pid]["ppid"]
    return out  # nearest-first


def launchd_managed(procs):
    """PIDs launchd is currently supervising — NOT orphans, however they look.

    `ppid == 1` carries two opposite meanings on macOS: a forked leftover whose
    parent died, and a LaunchAgent doing exactly what it was installed to do.
    This script read only the first, so every long-running LaunchAgent written
    in Python landed in the auto-safe bucket and was SIGTERM'd on sight.

    Observed 2026-09-03: `com.alphavaults.knot-recall` (a resident embedding
    model, ~900MB, ppid 1) and `com.alphavaults.knot-drain` both died with
    status 15 minutes after being installed; `com.sar.knot-sync` is the same
    shape and was only spared by being short-lived. Ask launchd who its
    children are instead of guessing from ppid.
    """
    managed = set()
    for line in sh("launchctl", "list").splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0].strip().isdigit():
            pid = int(parts[0])
            if pid in procs:
                managed.add(pid)
    return managed


def own_session_guard(procs, kids):
    """My entire agent session tree, derived mechanically (no hardcoded PIDs).

    Walk up from this process; the OUTERMOST agent-CLI ancestor (claude/codex/grok)
    is my session root — guard its whole subtree plus every ancestor up to init.
    This is what prevents 'kill all claude' from terminating the running session.
    """
    me = os.getpid()
    anc = ancestors(me, procs)  # nearest-first
    root = me
    for a in anc:  # farther ancestors overwrite → outermost agent wins
        if a in procs and AGENT.search(procs[a]["args"]):
            root = a
    guard = set(anc) | subtree(root, kids) | {me}
    for pid in launchd_managed(procs):
        guard |= subtree(pid, kids) | {pid}
    return guard, root


def read_mem():
    out = sh("vm_stat")
    d, ps = {}, PAGE_DEFAULT
    for l in out.splitlines():
        m = re.search(r"page size of (\d+)", l)
        if m:
            ps = int(m.group(1))
        m = re.match(r"(.+?):\s+(\d+)\.", l)
        if m:
            d[m.group(1).strip()] = int(m.group(2)) * ps
    g = lambda k: d.get(k, 0) / 1e9
    lvl = sh("sysctl", "-n", "kern.memorystatus_vm_pressure_level").strip() or "?"
    pageouts = 0
    m = re.search(r"Pageouts:\s+(\d+)", out)
    if m:
        pageouts = int(m.group(1))
    total = None
    try:
        total = int(sh("sysctl", "-n", "hw.memsize").strip()) / 1e9
    except Exception:
        pass
    return dict(
        total=total, wired=g("Pages wired down"), active=g("Pages active"),
        inactive=g("Pages inactive"), compressor=g("Pages occupied by compressor"),
        free=g("Pages free") + g("Pages speculative"),
        anonymous=g("Anonymous pages"), filebacked=g("File-backed pages"),
        pressure=lvl, pageouts=pageouts,
    )


def classify(procs, kids, guard):
    buckets = dict(auto_safe=[], active_agents=[], gui_apps={}, chatgpt_mcp=[], backbone=[], system=[])
    # locate ChatGPT.app's leaked codex app-server subtree (the usual biggest hog)
    chatgpt_root = None
    for p in procs.values():
        if "ChatGPT.app" in p["args"] and "app-server" in p["args"]:
            chatgpt_root = p["pid"]
            break
    chatgpt_tree = subtree(chatgpt_root, kids) if chatgpt_root else set()

    for p in procs.values():
        pid, args, rss, ppid = p["pid"], p["args"], p["rss"], p["ppid"]
        if pid in guard:
            continue
        if BACKBONE.search(args):
            buckets["backbone"].append(p); continue
        if SYSTEM_PATH.search(args) and ppid == 1:
            buckets["system"].append(p); continue
        if pid in chatgpt_tree:
            buckets["chatgpt_mcp"].append(p); continue
        appm = APP_MAIN.search(args)
        if appm:
            app = appm.group(1)
            buckets["gui_apps"].setdefault(app, 0)
            buckets["gui_apps"][app] += rss
            continue
        # AUTO-SAFE = orphaned (ppid==1) leftover server OR orphaned MCP with no live owner
        orphan = ppid == 1 or ppid not in procs
        if orphan and (LEAKED_SERVER.search(args) or MCP.search(args)):
            buckets["auto_safe"].append(p); continue
        # remaining agent CLIs (not mine, not orphaned) = ACTIVE session → confirm-only
        if AGENT.search(args):
            buckets["active_agents"].append(p); continue
        # unknown orphaned non-system junk is also auto-safe-ish but be conservative:
        # only include clearly-orphaned node/python leftovers
        if orphan and re.search(r"\b(node|python3?)\b", args) and rss > 20000:
            buckets["auto_safe"].append(p)
    return buckets, chatgpt_root, chatgpt_tree


def mb(x):
    return f"{x/1024:.0f}MB"


def kill_pids(pids, guard, procs, kids, label):
    targets = set()
    for pid in pids:
        targets |= subtree(pid, kids)
    targets &= set(procs)
    bad = targets & guard
    assert not bad, f"REFUSING: {label} kill set intersects guarded session/backbone: {sorted(bad)}"
    for pid in sorted(targets):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"  ! PermissionError SIGTERM {pid}")
    time_wait()
    survivors = []
    for pid in targets:
        try:
            os.kill(pid, 0); survivors.append(pid)
        except OSError:
            pass
    for pid in survivors:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    freed = sum(procs[p]["rss"] for p in targets) / 1024
    return len(targets), freed


def time_wait():
    # bounded settle without foreground `sleep`; ~1.2s
    subprocess.run(["/bin/sh", "-c", "for i in 1 2 3 4 5 6; do : ; done; /usr/bin/true"], capture_output=True)
    t = 0.0
    while t < 1.2:
        os.times(); t += 0.2
        subprocess.run(["/usr/bin/true"], capture_output=True)


def diagnose(m):
    used = (m["total"] - m["free"]) if m["total"] else None
    print("== MEMORY ==")
    if m["total"]:
        print(f"  total {m['total']:.0f}GB | used ~{used:.0f}GB | free+spec {m['free']:.0f}GB | pressure_level={m['pressure']} (1=normal 2=warn 4=critical) | pageouts={m['pageouts']}")
    print(f"  anonymous(앱 실메모리) {m['anonymous']:.1f}GB | active {m['active']:.1f}GB | inactive(반납가능) {m['inactive']:.1f}GB | filecache {m['filebacked']:.1f}GB | wired {m['wired']:.1f}GB | compressed {m['compressor']:.1f}GB")
    note = []
    if m["pressure"] == "1" and m["pageouts"] < 1000:
        note.append("스왑 아님(pressure normal). 단 raw used가 커도 '괜찮다'고 넘기지 말 것 — 낮추려면 anonymous를 줄여야 함(=안 쓰는 GUI 앱 quit).")
    else:
        note.append("압력/스왑 신호 있음 — 회수 우선순위 높음.")
    note.append("판정 기준 = raw used(캐시+inactive 포함)가 아니라 anonymous(앱 실메모리) + pressure/pageouts.")
    for n in note:
        print(f"  · {n}")


def report(buckets, chatgpt_root, guard_root, procs, m):
    diagnose(m)
    print("\n== AUTO-SAFE (--apply-safe 로 회수, orphaned/leaked) ==")
    if not buckets["auto_safe"]:
        print("  (없음)")
    for p in sorted(buckets["auto_safe"], key=lambda x: -x["rss"]):
        print(f"  {mb(p['rss']):>7}  pid={p['pid']:<6} {p['args'][:70]}")
    print(f"\n== ChatGPT.app 누수 codex MCP (앱 재시작 권장, 또는 --kill-pids {chatgpt_root or ''}) ==")
    if buckets["chatgpt_mcp"]:
        tot = sum(p["rss"] for p in buckets["chatgpt_mcp"]) / 1024
        print(f"  {len(buckets['chatgpt_mcp'])} procs, ~{tot:.0f}MB (root app-server pid={chatgpt_root})")
    else:
        print("  (없음)")
    print("\n== GUI 앱 (사용자 결정 → --quit-apps 'name,name'; 열린 상태 소실) ==")
    for app, rss in sorted(buckets["gui_apps"].items(), key=lambda x: -x[1]):
        print(f"  {rss/1048576:>5.1f}GB  {app}")
    print("\n== 다른 활성 에이전트 세션 (confirm-only; active-processor-wait) ==")
    for p in sorted(buckets["active_agents"], key=lambda x: -x["rss"]):
        print(f"  {mb(p['rss']):>7}  pid={p['pid']:<6} {p['args'][:60]}  → 버려진 세션 확실할 때만 --kill-pids {p['pid']}")
    print(f"\n== 보존(guarded, 절대 kill 안 함): 내 세션 트리 root pid={guard_root} + backbone {len(buckets['backbone'])} + system {len(buckets['system'])} ==")


def main():
    ap = argparse.ArgumentParser(description="Safe macOS memory/process reclamation")
    ap.add_argument("--apply-safe", action="store_true", help="kill ONLY the auto-safe (orphaned/leaked) bucket")
    ap.add_argument("--quit-apps", default="", help="comma-separated GUI app names to graceful-quit")
    ap.add_argument("--kill-pids", default="", help="comma-separated PIDs whose subtrees to kill (guard-checked)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable buckets and exit")
    args = ap.parse_args()

    procs = snapshot()
    kids = children_map(procs)
    guard, guard_root = own_session_guard(procs, kids)
    buckets, chatgpt_root, chatgpt_tree = classify(procs, kids, guard)
    m = read_mem()

    if args.json:
        out = dict(
            memory=m, guard_root=guard_root,
            auto_safe=[{k: p[k] for k in ("pid", "rss", "args")} for p in buckets["auto_safe"]],
            chatgpt_mcp_root=chatgpt_root, chatgpt_mcp_count=len(buckets["chatgpt_mcp"]),
            chatgpt_mcp_mb=round(sum(p["rss"] for p in buckets["chatgpt_mcp"]) / 1024),
            gui_apps={a: round(r / 1048576, 1) for a, r in buckets["gui_apps"].items()},
            active_agents=[{k: p[k] for k in ("pid", "rss", "args")} for p in buckets["active_agents"]],
        )
        print(json.dumps(out, ensure_ascii=False, indent=2)); return

    acted = False
    if args.kill_pids.strip():
        acted = True
        pids = [int(x) for x in re.split(r"[,\s]+", args.kill_pids.strip()) if x]
        n, freed = kill_pids(pids, guard, procs, kids, "--kill-pids")
        print(f"--kill-pids: {n} procs terminated, ~{freed:.0f}MB")
    if args.apply_safe:
        acted = True
        pids = [p["pid"] for p in buckets["auto_safe"]]
        if pids:
            n, freed = kill_pids(pids, guard, procs, kids, "--apply-safe")
            print(f"--apply-safe: {n} orphaned/leaked procs terminated, ~{freed:.0f}MB")
        else:
            print("--apply-safe: auto-safe 버킷 비어있음, 종료할 것 없음")
    if args.quit_apps.strip():
        acted = True
        for app in [a.strip() for a in args.quit_apps.split(",") if a.strip()]:
            r = sh("osascript", "-e", f'quit app "{app}"')
            print(f'  quit app "{app}"')

    if acted:
        print("\n== 회수 후 ==")
        diagnose(read_mem())
    else:
        report(buckets, chatgpt_root, guard_root, procs, m)
        print("\n(dry-run. 실행: --apply-safe / --quit-apps 'name' / --kill-pids N)")


if __name__ == "__main__":
    main()
