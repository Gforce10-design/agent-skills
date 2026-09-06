#!/usr/bin/env python3
"""Traceability gate — make "spec adopted but not built" a build failure.

Turns a spec's box/requirement list (a manifest) into a coverage assertion:
every box must have its module + expected symbols + a test that references it.
Missing → nonzero exit. This is what catches agent-drift and adopted-but-unbuilt
boxes that a green test suite hides (because no test exists for the missing box).

Manifest (JSON): a list of boxes. Each box:
    {
      "id":       "B-exec-port",                              # required, human label
      "module":   "awo_runtime/contract_execution_port.py",   # required, path under --src
      "symbols":  ["ContractExecutionPort", "execute"],       # optional, top-level defs/assigns
      "test_ref": "contract_execution_port"                   # optional, substring a test must contain
    }
(Also accepts {"boxes": [ ... ]} or a list at top level.)

Usage:
    python3 traceability_gate.py --manifest spec.json --src tools/awo-runtime/src --tests tools/awo-runtime/tests
    python3 traceability_gate.py --manifest spec.json --src src --tests tests --json   # machine-readable
Exit: 0 = every box traced; 1 = one or more gaps; 2 = bad input.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


def _top_level_names(path: Path) -> set[str]:
    """Top-level defs / classes / assignment targets in a module (ast, no import)."""
    names: set[str] = set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, OSError):
        return names
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _load_boxes(manifest: Path) -> list[dict]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("boxes", data.get("manifest", []))
    if not isinstance(data, list):
        raise ValueError("manifest must be a list of boxes (or {'boxes': [...]})")
    return data


def check(manifest: Path, src: Path, tests: Path) -> list[dict]:
    """Return one result dict per box: {id, status, detail}. status in OK/MISSING/INCOMPLETE/UNTESTED."""
    boxes = _load_boxes(manifest)
    test_blobs = {p: p.read_text(encoding="utf-8", errors="ignore")
                  for p in tests.rglob("test_*.py")} if tests.exists() else {}
    results: list[dict] = []
    for box in boxes:
        bid = box.get("id", box.get("module", "?"))
        mod_rel = box.get("module")
        if not mod_rel:
            results.append({"id": bid, "status": "INCOMPLETE", "detail": "manifest box has no 'module'"})
            continue
        mod_path = src / mod_rel
        if not mod_path.exists():
            results.append({"id": bid, "status": "MISSING", "detail": f"module absent: {mod_rel}"})
            continue
        defined = _top_level_names(mod_path)
        missing_syms = [s for s in box.get("symbols", []) if s not in defined]
        if missing_syms:
            results.append({"id": bid, "status": "INCOMPLETE",
                            "detail": f"symbols absent in {mod_rel}: {missing_syms}"})
            continue
        ref = box.get("test_ref")
        if ref and not any(ref in blob for blob in test_blobs.values()):
            results.append({"id": bid, "status": "UNTESTED",
                            "detail": f"no test references '{ref}'"})
            continue
        results.append({"id": bid, "status": "OK", "detail": str(mod_rel)})
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Traceability gate: spec manifest ↔ code/test coverage.")
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--src", required=True, type=Path, help="source root the module paths are relative to")
    ap.add_argument("--tests", required=True, type=Path, help="test root (scanned for test_*.py)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    if not args.manifest.exists():
        print(f"manifest not found: {args.manifest}", file=sys.stderr)
        return 2
    try:
        results = check(args.manifest, args.src, args.tests)
    except ValueError as exc:
        print(f"bad manifest: {exc}", file=sys.stderr)
        return 2

    gaps = [r for r in results if r["status"] != "OK"]
    if args.json:
        print(json.dumps({"results": results, "gaps": len(gaps), "total": len(results)}, ensure_ascii=False, indent=2))
    else:
        for r in results:
            mark = "✅" if r["status"] == "OK" else "❌"
            print(f"{mark} [{r['status']:10}] {r['id']} — {r['detail']}")
        print(f"\n{len(results) - len(gaps)}/{len(results)} traced. {len(gaps)} gap(s).")
    return 1 if gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
