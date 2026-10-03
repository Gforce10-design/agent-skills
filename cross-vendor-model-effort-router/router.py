#!/usr/bin/env python3
"""Engine for cross-vendor-model-effort-router.

Recommends DIRECT / PLAN_FIRST / DELEGATE, emits an execution contract for direct
Codex routes, and learns from operator-declared, verified outcomes. Standard library only.

It NEVER writes to the legacy gpt-model-effort-advisor registry: that file is read
read-only as legacy evidence. This skill owns its own registry.jsonl.

Subcommands:
  recommend "<task>" [--axes ...] [--axes-ext ...]  Route + worker/model/effort proposal
  record ...                                        Append one verified final attempt
  query "<task>" [--axes ...]                       Similar past attempts (own + legacy)
  stats                                             Observed recorded outcomes
  validate                                          Report malformed/duplicate lines
"""
import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from codex_inventory import apply_inventory, MODEL_ID

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "registry.jsonl"
CAPABILITIES = HERE / "capabilities.json"
LEGACY_REGISTRY = Path.home() / ".agents/skills/gpt-model-effort-advisor/registry.jsonl"

ROUTER_VERSION = "2.7.0"
SCHEMA_VERSION = "v2"
POLICY_VERSION = "2.3.0"

LEGACY_AXES = ("verifiable", "failcost", "volume", "depth")
EXT_AXES = ("handoff_cost", "spec_readiness", "decomposability", "context_dependency",
            "uniformity", "optimization_goal", "verifier_available", "task_family",
            "role", "quota_state", "rollout_stage", "task_origin")
VALID_OUTCOMES = ("success", "fail", "partial")
OPT_GOALS = ("cost", "latency", "context_preservation", "quality")

# Ordinal scale. Ordering is meaningful ONLY inside one comparison_scope.
EFFORT_RANK = {"none": 0, "off": 0, "low": 1, "minimal": 1, "medium": 2,
               "high": 3, "xhigh": 4, "max": 4}
NORMAL_EFFORT_CEILING = "high"
NORMAL_EFFORT_LADDER = ["low", "medium", "high"]

_WORD = re.compile(r"[a-z0-9À-￿]+")


class IncomparableScopes(Exception):
    """Raised when effort ranks from different comparison scopes are compared."""


class DuplicateAttempt(Exception):
    """Raised when a final record for an existing attempt_id is appended again."""


class RegistryIntegrityError(Exception):
    """Raised when an append would extend a malformed or unsafe registry."""


class BackendContractError(Exception):
    """Raised when a backends.json projection cannot be trusted."""


class RegistryLoad:
    def __init__(self, records, invalid):
        self.records = records
        self.invalid = invalid  # [(line_no, error_str)]


# ---------- helpers ----------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _tokens(s):
    return set(_WORD.findall((s or "").lower()))


def load_capabilities(path=None):
    return json.loads(Path(path or CAPABILITIES).read_text(encoding="utf-8"))


def canonical_surface(surface):
    aliases = {
        "codex": "codex-cli",
        "codex-cli": "codex-cli",
        "openai": "codex-cli",
        "claude": "claude-code",
        "claude-code": "claude-code",
        "claude-code-cli": "claude-code",
        "anthropic": "claude-code",
    }
    return aliases.get((surface or "").strip().lower())


def model_family(model):
    model = (model or "").lower()
    match = MODEL_ID.fullmatch(model)
    if match:
        return "gpt-" + match.group(1)
    if model.startswith("gpt-5.6-"):
        return "gpt-5.6"
    if "fable" in model:
        return "fable-5"
    if any(model.startswith(x) for x in ("haiku-", "sonnet-", "opus-")):
        return "claude-5" if model.endswith("-5") else "claude-legacy"
    return model or "unknown"


def capability_freshness(caps, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        captured = datetime.fromisoformat(str(caps["captured_at"])).replace(tzinfo=timezone.utc)
        age = (now - captured).days
    except (KeyError, TypeError, ValueError):
        return {"status": "UNKNOWN", "age_days": None}
    limit = int(caps.get("stale_after_days", 0))
    return {
        "status": "FRESH" if limit and age <= limit else "STALE",
        "age_days": age,
        "stale_after_days": limit,
    }


def codex_model_availability(caps, model, now=None):
    """Use a recent authenticated model/list snapshot; stale snapshots say unknown."""
    snapshot = caps.get("_codex_account_inventory", {})
    try:
        captured = datetime.fromisoformat(str(snapshot["captured_at"])).replace(
            tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - captured).total_seconds() / 86400
    except (KeyError, TypeError, ValueError):
        return "unknown"
    if age < 0 or age > float(snapshot.get("stale_after_days", 1)):
        return "unknown"
    if model in snapshot.get("available_recommendation_models", []):
        return "available"
    if model in snapshot.get("official_but_not_exposed", []):
        return "unavailable"
    return "unknown"


def infer_vendor(rec):
    """Explicit vendor wins. Legacy gpt-* records predate the vendor field -> openai."""
    v = rec.get("vendor")
    if v:
        return v
    model = (rec.get("model") or rec.get("model_requested") or "")
    if model.startswith("gpt-") or model.startswith("o1") or model.startswith("o3"):
        return "openai"
    return "unknown"


# ---------- read-only MultiAgent backend contract ----------
def _reject_duplicate_json_keys(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise BackendContractError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def _flag_value(args, flag):
    if not isinstance(args, list) or flag not in args:
        return None
    i = args.index(flag)
    return args[i + 1] if i + 1 < len(args) else None


def _backend_semantic_projection(data):
    worker_fields = (
        "model", "effort", "call_type", "brief_mode", "requested_model_cli",
        "dynamic_loadout",
        "expected_model_usage_key",
        "expected_model_usage_keys",
        "expected_executable_sha256", "expected_version_regex", "cwd_policy", "write_policy",
        "operation_proof_eligible", "proof_scope", "model_evidence_scope",
        "permission_profile", "result_capture", "read_policy",
        "provider_auth_trust_boundary", "require_independent_verification",
        "require_os_write_confinement", "state_write_policy", "approval_class",
        "timeout",
    )
    trusted_fields = (
        "enabled", "model", "effort", "permission_class", "gateway_commit",
        "provider_git_write", "args_template", "timeout",
    )
    workers = {}
    for name, raw in sorted(data.get("workers", {}).items()):
        row = {key: raw.get(key) for key in worker_fields}
        cli = raw.get("cli") or {}
        row["cli"] = {
            "command": cli.get("command"),
            "args_template": cli.get("args_template"),
            "version_args": cli.get("version_args"),
            "help_args": cli.get("help_args"),
            "required_help_tokens": cli.get("required_help_tokens"),
        }
        trusted = raw.get("trusted_writer_profile")
        row["trusted_writer_profile"] = (
            {key: trusted.get(key) for key in trusted_fields}
            if isinstance(trusted, dict) else None
        )
        workers[name] = row
    return {
        "schema_version": data.get("schema_version"),
        "flavor": data.get("flavor"),
        "multiagent_root_env": data.get("multiagent_root_env"),
        "receipt_contract": data.get("receipt_contract"),
        "trusted_executable_paths": data.get("trusted_executable_paths"),
        "workers": workers,
    }


def _validate_model_effort_binding(name, worker):
    args = (worker.get("cli") or {}).get("args_template") or []
    declared_model = worker.get("model")
    cli_model = worker.get("requested_model_cli") or declared_model
    declared_effort = worker.get("effort")
    dynamic = worker.get("dynamic_loadout")
    if dynamic is not None:
        if not isinstance(dynamic, dict) or dynamic.get("selector") not in ("router-v1", "provider-catalog-v1"):
            raise BackendContractError(f"{name}: invalid dynamic_loadout selector")
        models = dynamic.get("allowed_models")
        efforts = dynamic.get("allowed_efforts")
        if not isinstance(models, list) or not models or not all(
                isinstance(value, str) and value for value in models):
            raise BackendContractError(f"{name}: dynamic_loadout allowed_models invalid")
        if not isinstance(efforts, list) or not efforts or not all(
                value in (NORMAL_EFFORT_LADDER if dynamic.get("selector")=="router-v1" else ("none","minimal","low","medium","high","xhigh","max","ultra","config","model-high","auto")) for value in efforts):
            raise BackendContractError(f"{name}: dynamic_loadout allowed_efforts invalid")
        if len(models) != len(set(models)) or len(efforts) != len(set(efforts)):
            raise BackendContractError(f"{name}: dynamic_loadout allowlists contain duplicates")
        if dynamic.get("default_model") != declared_model:
            raise BackendContractError(f"{name}: dynamic_loadout default_model mismatch")
        if dynamic.get("fallback_effort") != declared_effort:
            raise BackendContractError(f"{name}: dynamic_loadout fallback_effort mismatch")
    arg_model = _flag_value(args, "--model")
    arg_effort = _flag_value(args, "--effort")
    if arg_model is not None and arg_model != cli_model:
        raise BackendContractError(
            f"{name}: declared CLI model {cli_model!r} != CLI --model {arg_model!r}")
    if arg_effort is not None and arg_effort != declared_effort:
        raise BackendContractError(
            f"{name}: declared effort {declared_effort!r} != CLI --effort {arg_effort!r}")

    trusted = worker.get("trusted_writer_profile")
    if not isinstance(trusted, dict) or not trusted.get("enabled"):
        return
    targs = trusted.get("args_template") or []
    tmodel = _flag_value(targs, "--model")
    teffort = _flag_value(targs, "--effort")
    # Writer profiles may omit model/effort to inherit the worker's pinned loadout.
    # Treat omission as inheritance; only an explicit conflicting value is drift.
    trusted_declared_model = trusted.get("model") or declared_model
    trusted_cli_model = (
        worker.get("requested_model_cli")
        if trusted_declared_model == declared_model and worker.get("requested_model_cli")
        else trusted_declared_model
    )
    if tmodel is not None and tmodel != trusted_cli_model:
        raise BackendContractError(
            f"{name}.trusted_writer_profile model does not match args_template")
    trusted_declared_effort = trusted.get("effort") or declared_effort
    if teffort is not None and teffort != trusted_declared_effort:
        raise BackendContractError(
            f"{name}.trusted_writer_profile effort does not match args_template")


def load_backend_contract(path):
    """Read and validate backends.json without executing or mutating anything."""
    p = Path(path)
    if p.is_symlink():
        raise BackendContractError(f"backends path must not be a symlink: {p}")
    if not p.is_file():
        raise BackendContractError(f"backends path is not a regular file: {p}")
    raw = p.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_keys)
    except BackendContractError:
        raise
    except Exception as exc:
        raise BackendContractError(f"invalid backends JSON: {exc}") from exc
    if str(data.get("schema_version")) != "2":
        raise BackendContractError(
            f"unsupported backends schema_version: {data.get('schema_version')!r}")
    if not isinstance(data.get("flavor"), str) or not data["flavor"]:
        raise BackendContractError("backends flavor must be a non-empty string")
    workers = data.get("workers")
    if not isinstance(workers, dict) or not workers:
        raise BackendContractError("backends workers must be a non-empty object")
    for name, worker in workers.items():
        if not isinstance(worker, dict):
            raise BackendContractError(f"{name}: worker entry must be an object")
        for field in ("model", "effort", "call_type", "cli", "write_policy"):
            if field not in worker:
                raise BackendContractError(f"{name}: missing required field {field}")
        _validate_model_effort_binding(name, worker)
    projection = _backend_semantic_projection(data)
    canonical = json.dumps(
        projection, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "source_path": str(p.absolute()),
        "source_byte_sha256": hashlib.sha256(raw).hexdigest(),
        "semantic_sha256": hashlib.sha256(canonical).hexdigest(),
        "schema_version": str(data["schema_version"]),
        "flavor": data["flavor"],
        "workers": workers,
    }


def build_multiagent_execution_plan(
        contract, role="reviewer", selected_worker=None, selected_model=None,
        selected_effort=None, catalog_binding=None):
    topology = {
        "claude-conductor": {
            "conductor_surface": "claude-code",
            "default_main_worker": "codex-main",
        },
        "codex-conductor": {
            "conductor_surface": "codex-cli",
            "default_main_worker": "claude-main",
        },
    }
    flavor = contract.get("flavor")
    topo = topology.get(flavor)
    if topo is None:
        raise BackendContractError(f"unsupported MultiAgent flavor: {flavor!r}")
    worker_name = selected_worker or topo["default_main_worker"]
    raw = contract.get("workers", {}).get(worker_name)
    if not isinstance(raw, dict):
        raise BackendContractError(f"worker absent from backends contract: {worker_name}")
    trusted = raw.get("trusted_writer_profile")
    dynamic = raw.get("dynamic_loadout")
    effective_model = raw.get("model")
    effective_effort = raw.get("effort")
    model_selectable = isinstance(dynamic, dict)
    effort_selectable = isinstance(dynamic, dict)
    if (selected_model is None) != (selected_effort is None):
        raise BackendContractError("model and effort overrides must be supplied together")
    if selected_model is not None:
        if not isinstance(dynamic, dict):
            raise BackendContractError(f"{worker_name}: dynamic loadout is not enabled")
        catalog_valid = (dynamic.get("selector") == "provider-catalog-v1" and isinstance(catalog_binding, dict)
                         and catalog_binding.get("eligible") is True
                         and catalog_binding.get("provider") == dynamic.get("catalog_provider")
                         and catalog_binding.get("canonical_model_id") == selected_model
                         and catalog_binding.get("effort") == selected_effort)
        if not catalog_valid and selected_model not in dynamic.get("allowed_models", []):
            raise BackendContractError(
                f"{worker_name}: selected model is outside dynamic loadout allowlist")
        if not catalog_valid and selected_effort not in dynamic.get("allowed_efforts", []):
            raise BackendContractError(
                f"{worker_name}: selected effort is outside dynamic loadout allowlist")
        effective_model = selected_model
        effective_effort = selected_effort
    writer_role = role in ("implementation_writer", "feature_branch_owner", "writer")
    trusted_enabled = isinstance(trusted, dict) and trusted.get("enabled") is True
    if writer_role and not trusted_enabled:
        execution_status = "BLOCKED_CONTRACT_MISMATCH"
        writer_fit = "BLOCKED_CONTRACT_MISMATCH"
        writer_fit_reason = (
            f"{worker_name} is the flavor default implementation worker but has no enabled "
            "trusted_writer_profile; the advisor cannot invent write capability")
    else:
        execution_status = "READY"
        writer_fit = "READY" if writer_role else "NOT_APPLICABLE_READ_ONLY_ROLE"
        writer_fit_reason = None
    return {
        "flavor": flavor,
        "conductor_surface": topo["conductor_surface"],
        "default_main_worker": topo["default_main_worker"],
        "selected_worker": worker_name,
        "role": role,
        "execution_status": execution_status,
        "writer_fit": writer_fit,
        "writer_fit_reason": writer_fit_reason,
        "source_path": contract.get("source_path"),
        "source_byte_sha256": contract.get("source_byte_sha256"),
        "semantic_sha256": contract.get("semantic_sha256"),
        "worker": {
            "model": effective_model,
            "effort": effective_effort,
            "default_model": raw.get("model"),
            "default_effort": raw.get("effort"),
            "model_selectable": model_selectable,
            "effort_selectable": effort_selectable,
            "dynamic_loadout": dynamic,
            "write_policy": raw.get("write_policy"),
            "trusted_writer_profile": trusted if trusted_enabled else None,
            "operation_proof_eligible": raw.get("operation_proof_eligible"),
            "proof_scope": raw.get("proof_scope"),
        },
    }


# ---------- registry io ----------
def _registry_semantic_error(rec):
    if not isinstance(rec, dict):
        return "registry row must be an object"
    schema = str(rec.get("schema_version") or "v0")
    if schema not in {"v0", "v1", "v2"}:
        return f"unsupported schema_version: {schema!r}"
    event_type = rec.get("event_type", "attempt_final")
    if event_type == "attempt_invalidation":
        missing = [
            key for key in (
                "event_id", "target_attempt_id", "reason_code", "verification_evidence"
            ) if not rec.get(key)
        ]
        return f"invalidation missing required fields: {missing}" if missing else None
    if event_type != "attempt_final":
        return f"unsupported event_type: {event_type!r}"
    missing = [key for key in ("task", "outcome") if not rec.get(key)]
    if schema in ("v1", "v2") and not rec.get("attempt_id"):
        missing.append("attempt_id")
    if schema == "v0" and not (rec.get("model") or rec.get("worker")):
        missing.append("model_or_worker")
    if missing:
        return f"attempt missing required fields: {sorted(set(missing))}"
    if rec.get("outcome") not in VALID_OUTCOMES:
        return f"invalid outcome: {rec.get('outcome')!r}"
    grade = rec.get("verification_grade")
    if grade is not None and grade not in ("V0", "V1", "V2", "V3"):
        return f"invalid verification_grade: {grade!r}"
    return None


def load_registry(path=None):
    """Read a registry. Malformed lines are REPORTED, never silently dropped."""
    p = Path(path or REGISTRY)
    records, invalid = [], []
    if not p.exists():
        return RegistryLoad(records, invalid)
    for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception as e:
            invalid.append((i, str(e)))
            continue
        rec.setdefault("schema_version", "v0")
        if not rec.get("vendor"):
            rec["vendor"] = infer_vendor(rec)
        semantic_error = _registry_semantic_error(rec)
        if semantic_error:
            invalid.append((i, semantic_error))
            continue
        records.append(rec)
    return RegistryLoad(records, invalid)


def read_legacy_registry(path=None):
    """READ-ONLY view of the GPT advisor's registry. Never written by this skill."""
    load = load_registry(path or LEGACY_REGISTRY)
    for r in load.records:
        r["_source"] = "legacy_gpt_registry"
    return load.records


_SECRET_LIKE = re.compile(
    r"(?:api[_-]?key\s*[:=]|authorization\s*:\s*bearer|-----BEGIN [A-Z ]*PRIVATE KEY-----|"
    r"\bsk-[a-zA-Z0-9_-]{6,})",
    re.I,
)
_FORBIDDEN_EVIDENCE_KEYS = {
    "provider_transcript", "raw_transcript", "raw_prompt", "provider_response",
    "full_response", "credential", "credentials", "token",
}


def _unsafe_registry_payload(rec):
    def walk(value, key=None):
        if key in _FORBIDDEN_EVIDENCE_KEYS:
            return f"forbidden raw/secret field: {key}"
        if isinstance(value, dict):
            for child_key, child in value.items():
                issue = walk(child, str(child_key).lower())
                if issue:
                    return issue
        elif isinstance(value, list):
            for child in value:
                issue = walk(child, key)
                if issue:
                    return issue
        elif isinstance(value, str) and _SECRET_LIKE.search(value):
            return "secret-like content detected"
        return None
    return walk(rec)


def append_record(path, rec):
    """Append one attempt or invalidation event to a healthy registry."""
    p = Path(path)
    load = load_registry(p)
    if load.invalid:
        raise RegistryIntegrityError(
            f"registry has malformed existing lines; repair by superseding source, not append: "
            f"{load.invalid}")
    issue = _unsafe_registry_payload(rec)
    if issue:
        raise RegistryIntegrityError(issue)
    existing = load.records
    event_type = rec.get("event_type", "attempt_final")
    aid = rec.get("attempt_id")
    if event_type == "attempt_final" and aid and any(
            r.get("event_type", "attempt_final") == "attempt_final"
            and r.get("attempt_id") == aid for r in existing):
        raise DuplicateAttempt(f"attempt_id already has a final record: {aid}")
    event_id = rec.get("event_id")
    if event_id and any(r.get("event_id") == event_id for r in existing):
        raise DuplicateAttempt(f"event_id already exists: {event_id}")
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def build_record(task, axes, axes_ext, worker, outcome, attempt_id,
                 parent_attempt_id=None, vendor=None, surface=None,
                 model_requested=None, model_observed=None,
                 effort_requested=None, effort_observed=None,
                 observation_source="operator_declared",
                 verification_grade="V0", verification_method=None,
                 verifier_role=None, verification_evidence=None,
                 recommended_route=None, actual_route=None, override_reason=None,
                 cost_value=None, cost_unit="unknown", cost_basis="unknown",
                 minutes=None, reason="", notes="", comparison_scope=None,
                 task_family=None, role=None, rollout_stage=None,
                 model_family_value=None, task_origin=None):
    if outcome not in VALID_OUTCOMES:
        raise ValueError(
            f"top-level outcome must be one of {VALID_OUTCOMES} (legacy readers depend on it); "
            f"express detail in outcome_reason_code/failure_class instead: got {outcome!r}")
    # legacy axes string carries ONLY the original four axes
    legacy_axes = ",".join(f"{k}={axes[k]}" for k in LEGACY_AXES if k in axes)
    observed_any = model_observed or effort_observed
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "attempt_final",
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "record_id": f"{attempt_id}:final",
        "attempt_id": attempt_id,
        "parent_attempt_id": parent_attempt_id,
        "task": task,
        "axes": legacy_axes,
        "task_axes_ext": {k: axes_ext.get(k) for k in EXT_AXES},
        "worker": worker,
        "vendor": vendor,
        "surface": surface,
        "model": model_observed or model_requested,   # legacy field
        "effort": effort_observed or effort_requested,  # legacy field
        "model_requested": model_requested,
        "model_observed": model_observed,
        "model_family": model_family_value or model_family(model_observed or model_requested),
        "effort_requested": effort_requested,
        "effort_observed": effort_observed,
        "observation_source": observation_source,
        "observation_status": "observed" if observed_any else "requested_not_verified",
        "comparison_scope": comparison_scope,
        "task_family": task_family or axes_ext.get("task_family"),
        "role": role or axes_ext.get("role"),
        "rollout_stage": rollout_stage or axes_ext.get("rollout_stage"),
        "task_origin": task_origin or axes_ext.get("task_origin"),
        "cross_vendor_comparable": False,
        "outcome": outcome,
        "reason": reason,
        "verification_grade": verification_grade,
        "verification_method": verification_method,
        "verifier_role": verifier_role,
        "verification_evidence": verification_evidence,
        "recommended_route": recommended_route,
        "actual_route": actual_route,
        "override_reason": override_reason,
        "cost_value": cost_value,
        "cost_unit": cost_unit,
        "cost_basis": cost_basis,
        "minutes": minutes,
        "notes": notes,
        "router_version": ROUTER_VERSION,
        "policy_version": POLICY_VERSION,
    }


def build_invalidation_event(target_attempt_id, reason_code, evidence, event_id):
    if not all((target_attempt_id, reason_code, evidence, event_id)):
        raise ValueError("invalidation requires target, reason_code, evidence and event_id")
    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "attempt_invalidation",
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event_id": event_id,
        "target_attempt_id": target_attempt_id,
        "reason_code": reason_code,
        "verification_evidence": evidence,
        "router_version": ROUTER_VERSION,
        "policy_version": POLICY_VERSION,
    }


# ---------- effort normalization ----------
def _scope_of(surface_or_scope, caps):
    for w in caps["workers"].values():
        if w.get("vendor_cli", {}).get("comparison_scope") == surface_or_scope:
            return w["vendor_cli"]
    for key, d in caps.get("direct_execution", {}).items():
        if key == surface_or_scope or d.get("comparison_scope") == surface_or_scope:
            return d
    return {}


def normalize_effort(native, comparison_scope, caps):
    """Keep native + rank + semantics together. Never invent a level."""
    scope = _scope_of(comparison_scope, caps)
    semantics = scope.get("effort_semantics", "unknown")
    allowed = scope.get("effort_values")

    if native is None:
        rank, semantics = None, semantics if allowed else "unsupported"
    elif native in ("auto", "adaptive"):
        rank, semantics = None, "adaptive_auto"          # never silently -> medium
    elif native in ("config",):
        rank, semantics = None, "externally_configured"  # unresolved indirection
    elif semantics == "embedded_in_model":
        rank = None                                      # not a separate dial
    elif allowed and native not in allowed:
        rank, semantics = None, "unsupported"
    else:
        rank = EFFORT_RANK.get(native)

    return {
        "effort_native": native,
        "effort_rank": rank,
        "effort_semantics": semantics,
        "comparison_scope": comparison_scope,
        "cross_vendor_comparable": False,
    }


def comparable(scope_a, scope_b):
    return scope_a is not None and scope_a == scope_b


def compare_effort(a, b, caps):
    """a, b = (native, comparison_scope). Returns -1/0/1. Refuses cross-scope."""
    (a_native, a_scope), (b_native, b_scope) = a, b
    if not comparable(a_scope, b_scope):
        raise IncomparableScopes(
            f"effort_rank is only ordered within one comparison_scope: {a_scope!r} vs {b_scope!r}")
    ra = normalize_effort(a_native, a_scope, caps)["effort_rank"]
    rb = normalize_effort(b_native, b_scope, caps)["effort_rank"]
    if ra is None or rb is None:
        raise IncomparableScopes("effort rank unavailable for one side (null rank)")
    return (ra > rb) - (ra < rb)


def effective_effort(rec):
    """Observed wins over requested; never assert requested as actual."""
    return rec.get("effort_observed") or rec.get("effort_requested")


# ---------- session (parity with the legacy advisor, but vendor-aware) ----------
def session(surface=None):
    """Report the CURRENT session's model/effort for the given surface.

    The legacy advisor had a bug: it read CODEX_HOME rollouts regardless of who
    called it, so a Claude session got told it was running a Codex model. Here an
    unobservable surface returns null with observation_status='unobserved' rather
    than a confident wrong answer.
    """
    surface = surface or os.environ.get("AWO_ROUTER_SURFACE") or "unknown"
    out = {"surface": surface, "model": None, "effort": None,
           "source": None, "observation_status": "unobserved"}

    if surface in ("codex-cli", "codex"):
        cfg = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")) / "config.toml"
        if cfg.exists():
            t = cfg.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'^\s*model\s*=\s*"([^"]+)"', t, re.M)
            e = re.search(r'^\s*model_reasoning_effort\s*=\s*"([^"]+)"', t, re.M)
            out.update({
                "model": m.group(1) if m else None,
                "effort": e.group(1) if e else None,
                "source": "codex_config_default",
                "observation_status": "config_default_not_session_observed",
                "caveat": "A session-level /model override is not visible here.",
            })
        return out

    if surface in ("claude-code-cli", "claude-code", "claude"):
        out["caveat"] = ("Claude Code does not expose the running session's model/effort to a "
                         "subprocess. Ask the operator, or read it from the UI. Never guess — and "
                         "never read a Codex rollout and call it the Claude session.")
        return out

    return out


# ---------- evidence ----------
def evidence_tier(n):
    if n <= 2:
        return "anecdotal"
    if n <= 9:
        return "provisional"
    return "override_eligible"


def override_allowed(n, failcost="low"):
    if failcost == "high":
        return n >= 20
    return n >= 10


def _record_matches_cohort(rec, cohort):
    if not cohort:
        return True
    actual = {
        "vendor": infer_vendor(rec),
        "surface": canonical_surface(rec.get("surface")),
        "model_family": rec.get("model_family") or model_family(
            rec.get("model_observed") or rec.get("model_requested") or rec.get("model")),
        "task_family": rec.get("task_family"),
        "role": rec.get("role"),
    }
    expected = dict(cohort)
    if "surface" in expected:
        expected["surface"] = canonical_surface(expected["surface"])
    return all(actual.get(key) == value for key, value in expected.items() if value is not None)


def _independent_verifier_present(rec):
    verifier = str(rec.get("verifier_role") or "").strip().lower()
    worker = str(rec.get("worker") or "").strip().lower()
    if not verifier or verifier in {"self", "producer", "executor", "worker", "self-review"}:
        return False
    if worker and verifier == worker:
        return False
    return True


def usable_attempts(records, cohort=None):
    """Only valid V2/V3 evidence from the same cohort, de-duplicated by attempt."""
    invalidated = {
        r.get("target_attempt_id") for r in records
        if r.get("event_type") == "attempt_invalidation"
    }
    seen, out = set(), []
    for r in records:
        if r.get("event_type", "attempt_final") != "attempt_final":
            continue
        if r.get("verification_grade") not in ("V2", "V3"):
            continue
        if not r.get("verification_evidence"):
            continue
        if not _independent_verifier_present(r):
            continue
        aid = r.get("attempt_id")
        if aid in invalidated:
            continue
        if not _record_matches_cohort(r, cohort):
            continue
        if aid in seen:
            continue
        seen.add(aid)
        out.append(r)
    return out


def override_decision(records, failcost="low", cohort=None):
    usable = usable_attempts(records, cohort=cohort)
    n = len(usable)
    unique_tasks = len({r.get("task") for r in usable})
    success = sum(1 for r in usable if r.get("outcome") == "success")
    fail = sum(1 for r in usable if r.get("outcome") == "fail")
    all_success = n > 0 and success == n and fail == 0
    partial = sum(1 for r in usable if r.get("outcome") == "partial")
    allowed = override_allowed(n, failcost) and unique_tasks >= 3 and all_success
    return {
        "allowed": allowed,
        "n": n,
        "tier": evidence_tier(n),
        "unique_task_instances": unique_tasks,
        "success": success,
        "fail": fail,
        "partial": partial,
        "reason": None if allowed else (
            "fewer than 3 unique task instances" if unique_tasks < 3
            else "cohort contains failed or partial outcomes" if not all_success
            else f"{evidence_tier(n)} evidence (n={n}); Wilson 95% lower bound is too weak to override"),
    }


def fable_rollout_gate(records, explicit_opt_in=False):
    observed = [
        r for r in usable_attempts(records)
        if (r.get("model_family") or model_family(
            r.get("model_observed") or r.get("model_requested") or r.get("model"))) == "fable-5"
    ]
    eligible = [
        r for r in observed
        if infer_vendor(r) == "anthropic"
        and canonical_surface(r.get("surface")) == "claude-code"
        and r.get("rollout_stage") == "v3"
        and r.get("task_origin") == "real"
    ]
    n = len(eligible)
    unique_tasks = len({r.get("task") for r in eligible})
    failures = sum(1 for r in eligible if r.get("outcome") == "fail")
    partials = sum(1 for r in eligible if r.get("outcome") == "partial")
    successes = sum(1 for r in eligible if r.get("outcome") == "success")
    sample_pass = (
        n >= 20 and unique_tasks >= 3 and failures == 0 and partials == 0
        and successes == n
    )
    if not sample_pass:
        status = "SHADOW_ONLY"
    elif not explicit_opt_in:
        status = "V3_SHADOW_PASS_OPT_IN_REQUIRED"
    else:
        status = "OPT_IN_ELIGIBLE"
    return {
        "status": status,
        "production_eligible": sample_pass and explicit_opt_in,
        "promotion_allowed": sample_pass and explicit_opt_in,
        "observed_n": len(observed),
        "excluded_from_v3_promotion": len(observed) - n,
        "n": n,
        "unique_task_instances": unique_tasks,
        "successes": successes,
        "failures": failures,
        "partials": partials,
        "required_n": 20,
        "requires_explicit_opt_in": True,
    }


# ---------- escalation ----------
def next_tier(worker, caps):
    """Never invent a model that the vendor CLI does not list."""
    w = caps["workers"].get(worker, {})
    ladder = w.get("tier_ladder", {})
    if "next_tier" in ladder:
        return {"next_tier": ladder["next_tier"],
                "escalation_status": ladder["escalation_status"],
                "reason": ladder.get("reason")}
    return {"next_tier": None,
            "escalation_status": ladder.get("escalation_status", "unavailable"),
            "reason": "dispatcher fixes this worker's loadout; the skill does not modify it"}


def next_direct_tier(model, surface, caps):
    surface = canonical_surface(surface) or surface
    d = caps.get("direct_execution", {}).get(surface, {})
    models = d.get("recommendation_models", d.get("models", []))
    if model not in models:
        return None
    i = models.index(model)
    next_model = models[i + 1] if i + 1 < len(models) else None
    if surface == "codex-cli" and next_model and \
            codex_model_availability(caps, next_model) == "unavailable":
        return None
    return next_model


def next_effort(effort, surface, caps):
    """One step at a time, stopping at the normal ceiling (High)."""
    if effort not in NORMAL_EFFORT_LADDER:
        return None
    i = NORMAL_EFFORT_LADDER.index(effort)
    if i + 1 >= len(NORMAL_EFFORT_LADDER):
        return None  # High is the ceiling: raise the tier instead
    return NORMAL_EFFORT_LADDER[i + 1]


def diagnose(failure_class, model=None, effort=None, surface="claude-code", caps=None):
    """Change exactly ONE axis per retry."""
    caps = caps or load_capabilities()
    if failure_class == "REASONING_DEPTH_FAILURE":
        return {"change_axis": "effort", "from": effort,
                "to": next_effort(effort, surface, caps),
                "rationale": "not enough deliberation; raise effort one step in the same model"}
    if failure_class == "MODEL_CAPABILITY_FAILURE":
        return {"change_axis": "model", "from": model,
                "to": next_direct_tier(model, surface, caps),
                "rationale": "intelligence ceiling reached at High; raise the tier, not the effort"}
    if failure_class == "TOOL_OR_INFRA_FAILURE":
        return {"change_axis": "none",
                "rationale": "auth/quota/network/CLI problem; do not record as a model-quality failure"}
    if failure_class == "SPEC_FAILURE":
        return {"change_axis": "spec",
                "rationale": "literal-but-wrong / spec gaming; fix the spec and DoD, do not raise compute"}
    if failure_class == "OVERPROVISIONING":
        return {"change_axis": "effort", "from": effort,
                "to": "low" if effort in ("medium", "high") else effort,
                "rationale": "quality is sufficient; lower compute and state a clear Definition of Done"}
    if failure_class == "ROLE_OR_VENDOR_MISMATCH":
        return {"change_axis": "worker",
                "rationale": "propose a different worker; never switch vendor automatically"}
    return {"change_axis": "none", "rationale": f"unknown failure class: {failure_class}"}


# ---------- decision flow ----------
def is_mechanical_batch(axes, axes_ext):
    """`shallow + verifiable` alone is NOT mechanical.

    Bulk permission changes, migrations and repo-wide renames are all shallow and
    exactly verifiable, yet carry high failure cost or integration risk. Require the
    full conjunction before calling work mechanical.
    """
    return (axes.get("depth") == "shallow"
            and axes.get("verifiable") == "yes"
            and axes.get("volume") == "high"
            and axes.get("failcost") != "high"
            and axes_ext.get("spec_readiness") == "executable"
            and axes_ext.get("decomposability") == "independent"
            and axes_ext.get("context_dependency") == "low")


def break_even(axes_ext):
    """Qualitative gate. No paired observations or comparable cost units exist,
    so this returns a heuristic verdict and never a quantitative saving claim."""
    spec = axes_ext.get("spec_readiness")
    if spec and spec != "executable":
        return "PLAN_FIRST"
    volume = axes_ext.get("volume")
    handoff = axes_ext.get("handoff_cost")
    ctx = axes_ext.get("context_dependency")
    decomp = axes_ext.get("decomposability")
    verifier = axes_ext.get("verifier_available")

    if volume == "low" and (handoff == "high" or ctx == "high"):
        return "DIRECT"
    if spec == "executable" and (volume == "high" or decomp == "independent") \
            and verifier == "yes":
        return "DELEGATE"
    return "DIRECT"


def _worker_evidence_cohort(name, caps, axes_ext):
    worker = caps.get("workers", {}).get(name, {})
    dispatcher = worker.get("dispatcher", {})
    return {
        "vendor": worker.get("vendor"),
        "surface": worker.get("surface"),
        "model_family": model_family(
            dispatcher.get("model_observed") or dispatcher.get("model_requested")),
        "task_family": axes_ext.get("task_family"),
        "role": axes_ext.get("role"),
    }


def _pick_worker(task, axes, axes_ext, caps, records):
    """Choose worker using only same-loadout evidence; otherwise cold-start prior."""
    qt = _tokens(task)
    best, best_score, best_decision = None, 0.0, None
    for name, worker_capability in caps.get("workers", {}).items():
        if worker_capability.get("alias_of"):
            continue
        cohort = _worker_evidence_cohort(name, caps, axes_ext)
        decision = override_decision(
            records, failcost=axes.get("failcost", "low"), cohort=cohort)
        if not decision["allowed"]:
            continue
        for rec in usable_attempts(records, cohort=cohort):
            if rec.get("outcome") != "success":
                continue
            score = len(qt & _tokens(rec.get("task"))) / (
                len(qt | _tokens(rec.get("task"))) or 1)
            if score > best_score:
                best, best_score, best_decision = name, score, decision
    if best:
        return best, "registry", best_decision
    prior = caps.get("cold_start_prior", {})
    depth = axes.get("depth")
    verifiable = axes.get("verifiable")
    task_fit = " ".join(
        str(value or "").lower()
        for value in (task, axes_ext.get("task_family"), axes_ext.get("role"))
    )
    compatibility_markers = (
        "compat", "compatibility", "format", "alternate-vendor", "cross-vendor",
        "호환", "포맷", "형식", "대체 공급자", "교차 공급자",
    )
    adversarial_markers = (
        "adversarial", "counterexample", "attack path", "security review",
        "반례", "공격 경로", "적대적", "보안 검토", "논리적 맹점",
    )
    if any(marker in task_fit for marker in compatibility_markers):
        worker = "agy-compat"
    elif any(marker in task_fit for marker in adversarial_markers):
        worker = "grok-adversarial"
    elif verifiable == "yes" and depth in ("shallow", "mid"):
        worker = "claude-main"
    elif axes.get("failcost") == "high":
        worker = "grok-adversarial"
    else:
        worker = "claude-main"
    decision = override_decision(
        records,
        failcost=axes.get("failcost", "low"),
        cohort=_worker_evidence_cohort(worker, caps, axes_ext),
    )
    return worker, "heuristic", decision


def _direct_selection(axes, direct):
    """Select model capability and deliberation as separate dimensions.

    Depth determines the base capability tier. Failure cost raises the model tier,
    while weak verification raises model capability and/or deliberation. `volume`
    deliberately does not participate: it means model output volume and belongs to
    the direct-vs-delegate break-even gate, not the quality floor.
    """
    depth = {"medium": "mid"}.get(axes.get("depth"), axes.get("depth"))
    depth = depth if depth in ("shallow", "mid", "deep") else "mid"
    failcost = axes.get("failcost") if axes.get("failcost") in ("low", "mid", "high") else "mid"
    verifiable = axes.get("verifiable") if axes.get("verifiable") in ("yes", "partial", "no") else "partial"
    policy = direct.get("selection_policy")
    if not policy:
        floor = direct["quality_floor"]
        model = (floor["deep_or_high_failcost"] if depth == "deep" or failcost == "high"
                 else floor["mid"] if depth == "mid" else floor["shallow_low_failcost"])
        effort = "high" if depth == "deep" or failcost == "high" else (
            "medium" if depth == "mid" else "low")
        return model, effort, ["legacy_quality_floor"]

    allowed = direct["recommendation_models"]
    base_model = policy["base_model_by_depth"][depth]
    model_index = allowed.index(base_model)
    adjustments = []
    if failcost == "high":
        model_index += int(policy.get("high_failcost_model_steps", 0))
        adjustments.append("high_failcost")
    if verifiable == "no":
        model_index += int(policy.get("unverifiable_model_steps", 0))
        adjustments.append("unverifiable_output")
    model = allowed[min(model_index, len(allowed) - 1)]

    effort_index = {"shallow": 0, "mid": 1, "deep": 2}[depth]
    if verifiable == "partial":
        effort_index += int(policy.get("partial_effort_steps", 0))
        adjustments.append("partial_verifiability")
    elif verifiable == "no":
        effort_index += int(policy.get("unverifiable_effort_steps", 0))
        adjustments.append("verifiability")
    effort = NORMAL_EFFORT_LADDER[min(effort_index, len(NORMAL_EFFORT_LADDER) - 1)]
    return model, effort, adjustments


def _classification_receipt(axes, direct):
    """Expose the operator-declared boundary and nearby outcomes.

    The engine cannot infer task depth or failure cost from prose.  Returning the
    scope contract and one-axis counterfactuals makes whole-project inflation
    visible before a recommendation is repeated as fact.
    """
    current_model, current_effort, _ = _direct_selection(axes, direct)
    variants = []
    changes = (
        ("narrower_depth", "depth", {"deep": "mid", "mid": "shallow"}),
        ("lower_failure_cost", "failcost", {"high": "mid"}),
        ("stronger_verification", "verifiable", {"no": "partial", "partial": "yes"}),
    )
    for label, axis, mapping in changes:
        old = axes.get(axis)
        new = mapping.get(old)
        if new is None:
            continue
        candidate = dict(axes)
        candidate[axis] = new
        model, effort, _ = _direct_selection(candidate, direct)
        if (model, effort) == (current_model, current_effort):
            continue
        variants.append({
            "condition": f"if evidence supports {axis}={new}",
            "change": label,
            "model": model,
            "effort": effort,
        })
    return {
        "scope": "next_bounded_action",
        "rules": [
            "depth describes the next bounded action, not the whole project; planning alone is not deep",
            "failcost=high only when a wrong result can cause material harm before an independent check",
            "verifiable=yes when deterministic tests or exact evidence decide this step",
            "an advisor model is an independent reviewer and never substitutes for this direct-route result",
        ],
        "axis_sensitivity": variants,
    }


def select_direct_model(surface, axes, caps, *, quota_state=None,
                        optimization_goal=None, model_availability=None):
    surface = canonical_surface(surface)
    if surface not in ("codex-cli", "claude-code"):
        return {
            "route": "NEEDS_SURFACE",
            "reason": "DIRECT recommendations require --surface codex or --surface claude",
            "model": None,
            "model_effort_selectable": False,
        }
    direct = caps["direct_execution"][surface]
    chosen, effort, adjustments = _direct_selection(axes, direct)
    vendor = "openai" if surface == "codex-cli" else "anthropic"
    allow = direct["recommendation_models"]
    if chosen not in allow:
        raise ValueError(f"quality-floor model is not in surface allowlist: {chosen}")
    if surface == "codex-cli":
        supported = caps.get("_codex_account_inventory", {}).get("model_efforts", {}).get(chosen)
        if supported is not None and effort not in supported:
            return {"route": "BLOCKED_MODEL_EFFORT", "model": None, "effort": effort,
                    "model_effort_selectable": False,
                    "reason": f"{chosen} does not support requested effort {effort}"}
    availability = (model_availability or {}).get(chosen)
    if availability is None:
        availability = codex_model_availability(caps, chosen) \
            if surface == "codex-cli" else None
    if availability is None:
        availability = quota_state or "unknown"
    stages = [
        {
            "stage": "quality_floor",
            "status": "PASS",
            "model": chosen,
            "effort": effort,
            "adjustments": adjustments,
            "reason": "depth base plus independent failure-cost and verifiability adjustments",
        },
        {
            "stage": "availability",
            "status": "BLOCK" if availability == "unavailable" else "PASS",
            "signal": availability,
        },
        {
            "stage": "cost_tiebreak",
            "status": "NOT_APPLICABLE" if availability == "unavailable" else "PASS",
            "optimization_goal": optimization_goal,
            "reason": (
                "cost/quota may rank only quality-passing candidates; no downgrade below "
                "the quality floor is allowed"
            ),
        },
    ]
    if availability == "unavailable":
        return {
            "route": "BLOCKED_MODEL_AVAILABILITY",
            "surface": surface,
            "vendor": vendor,
            "model": None,
            "model_effort_selectable": False,
            "selection_stages": stages,
            "reason": f"{chosen} is unavailable and weaker models do not pass the quality floor",
        }
    return {
        "route": "DIRECT",
        "surface": surface,
        "vendor": vendor,
        "model": chosen,
        "effort": effort,
        "model_effort_selectable": True,
        "selection_stages": stages,
    }


def _discover_backend_path(explicit=None):
    if explicit:
        return Path(explicit)
    env_path = os.environ.get("AWO_BACKENDS_PATH")
    if env_path:
        return Path(env_path)
    candidate = Path.cwd() / "_shared" / "backends.json"
    if candidate.is_file() and not candidate.is_symlink():
        try:
            local = json.loads(candidate.read_text(encoding="utf-8"))
            workers = local.get("workers", {})
            if all(isinstance(workers.get(role, {}).get("dynamic_loadout"), dict)
                   for role in ("codex-main", "codex-critic", "codex-recompute")):
                return candidate
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
    # A worktree-local contract wins.  This user-level fallback lets sibling
    # worktrees use the verified dispatcher when they do not vendor one.
    fallback = Path.home() / "Developer" / "VibeCoding" / "_shared" / "backends.json"
    return fallback if fallback.is_file() and not fallback.is_symlink() else None


def _infer_role(task, axes_ext):
    if axes_ext.get("role"):
        return axes_ext["role"]
    text = (task or "").lower()
    # The requested action outranks names of files, workers, or components in
    # the review target.  Otherwise a code-review task mentioning
    # "codex-recompute" is misrouted as a recomputation task.
    if any(phrase in text for phrase in (
            "code review", "review the patch", "review the diff", "regression review",
            "critique the implementation", "코드 리뷰", "패치 검수", "diff 검수",
            "구현 검수", "회귀 검토", "코드 검수")):
        return "critic"
    if any(phrase in text for phrase in (
            "independent recomputation", "independent recalculation", "recompute",
            "recalculate", "verify the numbers", "reproduce the calculation",
            "독립 재계산", "재계산", "수치 재현", "계산 검증", "결과 재현")):
        return "recompute"
    if any(word in text for word in (
            "implement", "build", "fix", "refactor", "rename", "migrate",
            "구현", "수정", "리팩터", "마이그레이션")):
        return "implementation_writer"
    return "reviewer"


def _recommend_legacy(task, axes, axes_ext, caps=None, records=None, *, surface=None,
              backends_path=None, candidate_model=None, rollout_stage=None,
              quota_state=None, optimization_goal=None, model_availability=None,
              explicit_opt_in=False, catalog_enabled_gate=False):
    caps = caps or load_capabilities()
    records = records if records is not None else load_registry().records
    axes_ext = dict(axes_ext)
    if optimization_goal is not None:
        axes_ext["optimization_goal"] = optimization_goal
    if quota_state is not None:
        axes_ext["quota_state"] = quota_state
    if rollout_stage is not None:
        axes_ext["rollout_stage"] = rollout_stage
    route = break_even(axes_ext)

    out = {
        "route": route,
        "task": task,
        "axes": axes,
        "task_axes_ext": {k: axes_ext.get(k) for k in EXT_AXES},
        "break_even": "heuristic pass" if route == "DELEGATE" else "heuristic hold",
        "break_even_detail": (
            "Qualitative gate only. No paired direct-vs-delegated observations and no comparable "
            "cost unit exist, so no quantitative saving is claimed."),
        "router_version": ROUTER_VERSION,
        "capability_profile_version": caps.get("capability_profile_version"),
        "capability_captured_at": caps.get("captured_at"),
        "capability_freshness": capability_freshness(caps),
    }

    if route == "PLAN_FIRST":
        out.update({
            "reason": "spec_readiness is not executable; settle goal, scope, DoD and verifier "
                      "before spending an expensive run",
            "model_effort_selectable": False,
            "evidence_tier": evidence_tier(len(usable_attempts(records))),
            "decision_source": "heuristic",
        })
        return out

    if candidate_model:
        if canonical_surface(surface) != "claude-code" or candidate_model != "fable-5":
            out.update({
                "route": "BLOCKED_EXPERIMENT_CONTRACT",
                "production_eligible": False,
                "model_effort_selectable": False,
                "reason": "the only experimental direct candidate is fable-5 on Claude",
            })
            return out
        if rollout_stage not in ("v2", "v3"):
            out.update({
                "route": "BLOCKED_EXPERIMENT_CONTRACT",
                "production_eligible": False,
                "model_effort_selectable": False,
                "reason": "Fable requires --rollout-stage v2 or v3",
            })
            return out
        gate = fable_rollout_gate(records, explicit_opt_in=explicit_opt_in)
        recommendation_only = rollout_stage == "v3"
        out.update({
            "route": "SHADOW_EVALUATION",
            "surface": "claude-code",
            "vendor": "anthropic",
            "candidate_model": "fable-5",
            "rollout_stage": rollout_stage,
            "production_eligible": False,
            "model_effort_selectable": not recommendation_only,
            "rollout_gate": gate,
            "reason": (
                "Fable 5 remains V2 controlled/V3 recommendation-only shadow; this output "
                "does not authorize production use"),
        })
        if not recommendation_only:
            _, out["effort"], _ = _direct_selection(
                axes, caps["direct_execution"]["claude-code"])
        return out

    # ---- optimization-goal gate ----------------------------------------------
    # Fixed legacy roles need an optimization preference for mechanical batches.
    # Catalog-enabled roles resolve their selectable pair later; neither path
    # establishes a measured end-to-end cost advantage.
    econ = caps.get("economy", {})
    inferred_delegate_role = _infer_role(task, axes_ext)
    dynamic_role_worker = {
        "implementation_writer": "codex-main",
        "critic": "codex-critic",
        "recompute": "codex-recompute",
    }.get(inferred_delegate_role)
    dynamic_role_economy = bool(
        dynamic_role_worker
        and caps.get("workers", {}).get(dynamic_role_worker, {}).get("delegation_selectable")
    )
    if catalog_enabled_gate and route == "DELEGATE":
        catalog_backend_path = _discover_backend_path(backends_path)
        if catalog_backend_path is not None:
            try:
                catalog_contract = load_backend_contract(catalog_backend_path)
                if surface:
                    from provider_catalog import provider_name
                    catalog_provider=provider_name(surface)
                    selected_catalog_worker={'codex': {'critic':'codex-critic','recompute':'codex-recompute'}.get(inferred_delegate_role,'codex-main'),
                        'claude':'claude-main','grok':'grok-adversarial','agy':'agy-compat'}[catalog_provider]
                else:
                    selected_catalog_worker=_pick_worker(task,axes,axes_ext,caps,records)[0]
                catalog_dynamic=catalog_contract['workers'][selected_catalog_worker].get('dynamic_loadout',{})
                dynamic_role_economy = dynamic_role_economy or catalog_dynamic.get('selector')=='provider-catalog-v1'
            except (BackendContractError,KeyError,ValueError):
                pass  # invalid/fixed contracts never gain catalog selection authority
    if (route == "DELEGATE" and is_mechanical_batch(axes, axes_ext)
            and not dynamic_role_economy
            and not econ.get("delegate_economy_loadout_available", True)):
        goal = axes_ext.get("optimization_goal")
        cost_note = (
            "The delegate fleet has no economy loadout — every worker is pinned to a "
            "premium/frontier setting. Delegation here buys parallelism and main-context "
            "preservation, not a lower model tier. Whether its TOTAL cost exceeds DIRECT is "
            "unmeasured.")
        tool_first = None
        if axes_ext.get("uniformity") == "high":
            tool_first = ("This batch is uniform and machine-verifiable — check whether a "
                          "deterministic script or tool can do it before spending any LLM route.")

        if goal not in OPT_GOALS:
            out.update({
                "route": "NEEDS_PREFERENCE",
                "reason": "A mechanical batch with no economy delegate loadout. The winning route "
                          "depends on whether cost, latency or context preservation matters most, "
                          "and that cannot be derived from the task.",
                "ask": "비용 / 완료시간 / 메인 컨텍스트 보존 중 무엇이 우선입니까?",
                "options": {
                    "cost_first": {"route": "DIRECT",
                                   "note": "switch this session to a verified lower tier"},
                    "latency_or_context_first": {
                        "route": "DELEGATE",
                        "worker": _pick_worker(task, axes, axes_ext, caps, records)[0],
                        "note": "runs in a separate context, in parallel with your session"},
                },
                "cost_comparison": "unmeasured",
                "cost_note": cost_note,
                "tool_first_note": tool_first,
                "model_effort_selectable": False,
                "evidence_tier": evidence_tier(len(usable_attempts(records))),
                "decision_source": "heuristic",
            })
            return out

        if goal == "cost":
            out.update({
                "route": "DIRECT",
                "reason": "Cost was named as the priority and no delegate worker runs an economy "
                          "loadout, so DIRECT is evaluated after enforcing the quality floor.",
                "cost_comparison": "unmeasured",
                "cost_note": cost_note,
                "tool_first_note": tool_first,
                "caveat": "Switching the session model rebuilds the prompt cache — the direct cost "
                          "advantage is a hypothesis, not a measurement.",
            })
            route = "DIRECT"
        # latency / context_preservation / quality fall through to DELEGATE, but the
        # cost disclaimer travels with it.
        out["cost_note"] = cost_note
        out["cost_comparison"] = "unmeasured"
        out["tool_first_note"] = tool_first

    if route == "DELEGATE":
        role = _infer_role(task, axes_ext)
        worker, source, decision = _pick_worker(task, axes, axes_ext, caps, records)
        contract_path = _discover_backend_path(backends_path)
        plan = None
        adapter_status = "SNAPSHOT_ONLY"
        if contract_path is not None:
            try:
                contract = load_backend_contract(contract_path)
                default_worker = build_multiagent_execution_plan(
                    contract, role=role)["default_main_worker"]
                role_workers = {
                    "implementation_writer": default_worker,
                    "critic": "codex-critic",
                    "recompute": "codex-recompute",
                }
                selected = role_workers.get(role, worker)
                selected_model = None
                selected_effort = None
                selected_raw = contract.get("workers", {}).get(selected, {})
                if (selected_raw.get("dynamic_loadout") or {}).get("selector") == "router-v1":
                    selected_model, selected_effort, _ = _direct_selection(
                        axes, caps["direct_execution"]["codex-cli"])
                plan = build_multiagent_execution_plan(
                    contract, role=role, selected_worker=selected,
                    selected_model=selected_model, selected_effort=selected_effort)
                selected_availability = (model_availability or {}).get(selected_model)
                if selected_availability is None and selected_model:
                    selected_availability = codex_model_availability(caps, selected_model)
                if selected_availability == "unavailable":
                    out.update({
                        "route": "BLOCKED_MODEL_AVAILABILITY",
                        "execution_status": "BLOCKED",
                        "worker": selected,
                        "model": None,
                        "effort": selected_effort,
                        "model_effort_selectable": False,
                        "model_availability": "unavailable",
                        "reason": (f"{selected_model} is not exposed by the current Codex account; "
                                   "refresh the inventory or choose an available allowlisted pair"),
                    })
                    return out
                worker = selected
                if contract["semantic_sha256"] != caps.get("backends_semantic_sha256"):
                    adapter_status = "DEGRADED_SEMANTIC_MISMATCH"
                elif contract["source_byte_sha256"] != caps.get("backends_source_sha256"):
                    adapter_status = "FRESH_SEMANTIC_BYTE_DRIFT"
                else:
                    adapter_status = "FRESH"
            except BackendContractError as exc:
                out.update({
                    "route": "BLOCKED_BACKEND_CONTRACT",
                    "execution_status": "BLOCKED",
                    "model_effort_selectable": False,
                    "backend_contract_error": str(exc),
                })
                return out
        w = caps["workers"].get(worker, {})
        disp = w.get("dispatcher", {})
        fixed_model = plan["worker"]["model"] if plan else disp.get("model_requested")
        fixed_effort = plan["worker"]["effort"] if plan else disp.get("effort_requested")
        dynamic_selected = bool(plan and plan["worker"].get("model_selectable"))
        escalation = next_tier(worker, caps)
        if dynamic_selected:
            escalation = {
                "reasoning_failure_next_effort": next_effort(
                    fixed_effort, "codex-cli", caps),
                "capability_failure_next_model": next_direct_tier(
                    fixed_model, "codex-cli", caps),
                "normal_effort_ceiling": NORMAL_EFFORT_CEILING,
                "note": "Change one axis per verified failure; raise tier after High.",
            }
        out.update({
            "worker": worker,
            "vendor": w.get("vendor"),
            "surface": w.get("surface"),
            "model": fixed_model,
            "effort": fixed_effort,
            "model_effort_selectable": dynamic_selected,
            "model_effort_note": (
                "This Codex role keeps a stable worker identity while the router selects its "
                "allowlisted model and effort for the bounded task."
                if dynamic_selected else
                "Model and effort are a property of the worker, fixed by its backend contract."),
            "execution_contract": ({
                "mode": "multiagent_dynamic_loadout",
                "changes_current_interactive_session": False,
                "model": fixed_model,
                "effort": fixed_effort,
                "fallback_argv": [
                    str(Path(plan["source_path"]).parent / "adapters" / "call_worker.sh"),
                    worker, "<brief-file>", "--model", fixed_model,
                    "--effort", fixed_effort,
                ],
            } if dynamic_selected else None),
            "escalation": escalation,
            "evidence_tier": decision["tier"],
            "evidence": decision,
            "decision_source": source,
            "backend_adapter_status": adapter_status,
            "multiagent_execution_plan": plan,
            "execution_status": plan["execution_status"] if plan else "ADVISORY_ONLY",
            "verifier": "define a deterministic check (V3) before dispatch; a worker may not "
                        "approve its own result",
        })
        return out

    # DIRECT
    selected = select_direct_model(
        surface, axes, caps,
        quota_state=quota_state or axes_ext.get("quota_state"),
        optimization_goal=optimization_goal or axes_ext.get("optimization_goal"),
        model_availability=model_availability,
    )
    if selected["route"] != "DIRECT":
        out.update(selected)
        return out
    effort = selected["effort"]
    cohort = {
        "vendor": selected["vendor"],
        "surface": selected["surface"],
        "model_family": model_family(selected["model"]),
        "task_family": axes_ext.get("task_family"),
        "role": axes_ext.get("role") or "direct",
    }
    decision = override_decision(
        records, failcost=axes.get("failcost", "low"), cohort=cohort)
    out.update(selected)
    out.update({
        "classification_receipt": _classification_receipt(
            axes, caps["direct_execution"][selected["surface"]]),
        "model_effort_note": "Direct execution is the only place a real 2-axis ladder exists; "
                             "reuse the current runtime only when it already matches, otherwise "
                             "launch a bounded run with the selected model and effort.",
        "switch_commands": [f"/model {selected['model']}", f"/effort {effort}"],
        "execution_contract": {
            "mode": "reuse_current_or_launch_selected",
            "changes_current_interactive_session": False,
            "model": selected["model"],
            "effort": effort,
            "cwd": "current",
            "prompt_transport": "stdin",
            "fallback_argv": [
                "codex", "exec", "--model", selected["model"],
                "--config", f"model_reasoning_effort={effort}",
                "--cd", "<current-cwd>", "-",
            ],
        },
        "escalation": {
            "next_effort": next_effort(effort, selected["surface"], caps),
            "note": "High is the normal ceiling; if it still fails, raise the tier, not the effort. "
                    "xhigh/max are outside the normal ladder and need explicit approval.",
        },
        "evidence_tier": decision["tier"],
        "evidence": decision,
        "decision_source": "registry" if decision["allowed"] else "heuristic",
        "verifier": "state the check that decides success before running",
    })
    return out


def recommend(task, axes, axes_ext, caps=None, records=None, *, surface=None,
              requested_model=None, requested_effort=None, provider_executable=None,
              codex_home=None, catalogs=None, use_catalog=False, **kwargs):
    """Catalog-backed model binding; legacy policy/evidence/permission gates stay intact."""
    from provider_catalog import (CatalogError, provider_name, resolve, load_catalog,
                                  model_family as catalog_family)
    out = _recommend_legacy(task, axes, axes_ext, caps, records, surface=surface,
                            catalog_enabled_gate=use_catalog or catalogs is not None or requested_model is not None, **kwargs)
    if not use_catalog and requested_model is None and catalogs is None:
        return out
    if kwargs.get('candidate_model'):
        if requested_model is not None:
            return dict(out, route='BLOCKED_EXPERIMENT_CONTRACT', reason='--model and Fable shadow candidate are separate')
        return out
    if out['route'] not in ('DIRECT', 'DELEGATE', 'NEEDS_SURFACE'):
        return out
    try:
        route=out['route']
        if route=='NEEDS_SURFACE':
            if break_even(axes_ext)!='DIRECT':
                return out
            provider=provider_name(surface)
            route='DIRECT'
            out.update(route=route,surface={'grok':'grok-cli','agy':'agy-cli'}[provider])
        else:
            provider=provider_name(out.get('surface') or surface)
        contract=None;raw=None;worker=out.get('worker')
        if route=='DELEGATE':
            path=_discover_backend_path(kwargs.get('backends_path'))
            if path is None:
                raise CatalogError('delegated catalog binding requires actual backend contract')
            contract=load_backend_contract(path)
            if surface:
                requested_provider=provider_name(surface)
                codex_worker={'critic':'codex-critic','recompute':'codex-recompute'}.get(_infer_role(task,axes_ext),'codex-main')
                worker={'codex':codex_worker,'claude':'claude-main','grok':'grok-adversarial','agy':'agy-compat'}[requested_provider]
                provider=requested_provider
            raw=contract['workers'][worker]
            dynamic=raw.get('dynamic_loadout',{})
            if dynamic.get('selector')!='provider-catalog-v1' or dynamic.get('catalog_provider')!=provider:
                raise CatalogError('worker has no matching catalog-backed loadout contract')
            module=Path(__file__).resolve().with_name('provider_catalog.py')
            if Path(dynamic.get('catalog_resolver_path','')).resolve()!=module or dynamic.get('catalog_resolver_sha256')!=hashlib.sha256(module.read_bytes()).hexdigest():
                raise CatalogError('backend shared catalog resolver pin mismatch')
            dependencies=dynamic.get('catalog_resolver_dependencies',{})
            expected_dependency=hashlib.sha256(module.with_name('codex_inventory.py').read_bytes()).hexdigest()
            if dependencies != {'codex_inventory.py':expected_dependency}:
                raise CatalogError('backend catalog dependency pin mismatch')
            provider_executable=raw['cli']['command']
            # Existing dispatcher stages ~/.codex auth; conductor CODEX_HOME is a different account.
            codex_home=str(Path.home()/'.codex') if provider=='codex' else None
        catalog=(catalogs or {}).get(provider)
        if catalog is None:
            catalog=load_catalog(provider,executable=provider_executable,codex_home=codex_home)
        level={'shallow':0,'mid':1,'deep':2}[axes.get('depth','mid')]
        level += {'yes':0,'partial':1,'no':2}[axes.get('verifiable','yes')]
        desired_effort=requested_effort or NORMAL_EFFORT_LADDER[min(level,2)]
        if route=='DIRECT' and requested_effort is None and out.get('effort') in NORMAL_EFFORT_LADDER:
            desired_effort=out['effort']
        desired=requested_model
        if desired is None:
            old_model=out.get('model')
            if route=='DELEGATE' and provider in ('codex','claude'):
                policy_caps=caps or load_capabilities()
                old_model,_,_=_direct_selection(axes,policy_caps['direct_execution']['codex-cli' if provider=='codex' else 'claude-code'])
            family=catalog_family(old_model,provider) if old_model else None
            if provider=='claude' and family.startswith('unknown:'):family='opus'
            if provider=='agy':family='gemini-flash'
            if provider=='grok':family='grok'
            desired='latest:'+family if family else 'latest'
        # Native no-effort models omit the dial instead of inventing medium.
        explicit_rows=[r for r in catalog.get('models',[]) if desired in (r['canonical_model_id'],r.get('observed_model_id'))]
        if explicit_rows and explicit_rows[0].get('supported_efforts')==['none'] and requested_effort is None:
            desired_effort='none'
        if desired.startswith('latest:haiku') and requested_effort is None:
            desired_effort='none'
        if provider=='grok' and requested_effort is None:
            family=desired.split(':',1)[1] if desired.startswith('latest:') else ('grok' if desired=='latest' else None)
            possible=[r for r in catalog.get('models',[]) if (r['family']==family if family else r['canonical_model_id']==desired)]
            if possible:
                newest=max(possible,key=lambda r:tuple(r['version']))
                if newest.get('effort_status')=='unknown_default_only':desired_effort='config'
        binding=resolve(provider,desired,desired_effort,catalog=catalog)
        model=binding['canonical_model_id'];effort=binding['effort']
        if any((kwargs.get('model_availability') or {}).get(key)=='unavailable' for key in (model,binding['cli_model'],requested_model) if key):
            raise CatalogError('final selected model explicitly unavailable')
        out['selection_stages']=[{'stage':'catalog_binding','status':'PASS','model':model,'effort':effort},
            {'stage':'quality_floor','status':'EXPLICIT_OVERRIDE_UNVERIFIED' if requested_model else 'POLICY_FAMILY_CURRENT',
             'model':model,'effort':effort,'reason':'Explicit model choice does not establish task quality sufficiency' if requested_model else 'Current version of policy-selected family'}]
        if requested_model:out['explicit_quality_override']=True
        receipt=out.get('classification_receipt')
        if receipt:
            for variant in receipt.get('axis_sensitivity',[]):
                try:
                    alt=resolve(provider,'latest:'+catalog_family(variant['model'],provider),variant['effort'],catalog=catalog)
                    variant.update(model=alt['canonical_model_id'],effort=alt['effort'])
                except CatalogError:
                    variant.update(model=None,catalog_availability='unavailable')
        out.update(route=route,model=model,effort=effort,model_effort_selectable=True,
                   vendor={'codex':'openai','claude':'anthropic','grok':'xai','agy':'google'}[provider],
                   model_family=binding['family'], surface={'codex':'codex-cli','claude':'claude-code','grok':'grok-cli','agy':'agy-cli'}[provider],
                   decision_source='catalog_explicit_override' if requested_model else 'policy_family_current_catalog',
                   provider_catalog_binding=binding,catalog_source=catalog['source'],
                   catalog_freshness=catalog['freshness'],alternatives=binding['alternatives'],cost_comparison='unmeasured',
                   reason='Exact current provider catalog binding; execution and task quality require independent verification.')
        if provider=='agy':
            out['vendor']='anthropic' if model.startswith('claude-') else 'openai' if model.startswith('gpt-') else 'google' if model.startswith('gemini-') else 'unknown'
        out['escalation']={'next_effort': next((e for e in ('low','medium','high') if e in next((r['supported_efforts'] for r in catalog['models'] if r['canonical_model_id']==model),[]) and NORMAL_EFFORT_LADDER.index(e)>NORMAL_EFFORT_LADDER.index(effort)),None) if effort in NORMAL_EFFORT_LADDER else None,
            'note':'Re-resolve the same fresh catalog before escalation; metadata does not establish task quality.'}
        if route=='DELEGATE':
            if provider=='claude' and raw.get('model_evidence_scope')=='PINNED_CLI_RESPONSE_MODEL_USAGE_METADATA' and not binding['model_evidence_keys']:
                raise CatalogError('CLAUDE_MODEL_USAGE_IDENTITY_UNRESOLVED')
            role=_infer_role(task,axes_ext)
            plan=build_multiagent_execution_plan(contract,role=role,selected_worker=worker,
                selected_model=model,selected_effort=effort,catalog_binding=binding)
            out.update(worker=worker,multiagent_execution_plan=plan,execution_status=plan['execution_status'],
                       surface=raw.get('surface') or {'codex':'codex-cli','claude':'claude-code','grok':'grok-cli','agy':'agy-cli'}[provider],
                       model_effort_note='Stable worker permission profile; exact current catalog model/effort binding.')
            out['execution_contract']={'mode':'multiagent_catalog_loadout','changes_current_interactive_session':False,
                'model':model,'effort':effort,'fallback_argv':[str(Path(contract['source_path']).parent/'adapters/call_worker.sh'),
                    worker,'<brief-file>','--model',model,'--effort',effort]}
        else:
            binary=provider_executable or provider
            argv=[binary,'exec','--model',binding['cli_model']] if provider=='codex' else [binary,'--model',binding['cli_model']]
            eb=binding['effort_binding']
            if eb['flag']:
                argv += [eb['flag'],eb['config_key']+'='+effort if eb['config_key'] else effort]
            if provider=='codex':argv+=['--cd','<current-cwd>','-']
            out['model_effort_note']='Current provider catalog binds exact model and supported effort; metadata is not runtime/generation proof.'
            out['execution_contract']={'mode':'reuse_current_or_launch_selected','changes_current_interactive_session':False,
                'model':model,'effort':effort,'cwd':'current','prompt_transport':'stdin','fallback_argv':argv}
            out['switch_commands']=[f"/model {binding['cli_model']}"] + ([] if eb['mode'] in ('none','embedded') else [f'/effort {effort}'])
            if provider!='codex':
                out['execution_contract'].update(mode='current_session_selection_only',prompt_transport=None,fallback_argv=[],
                    headless_fallback_supported=False,reason='Use the selected provider session or the verified delegate adapter; no generic headless argv is emitted.')
                out['switch_commands']=[]
                out['session_selection']={'cli_model':binding['cli_model'],'effort':effort,'effort_binding':eb,'native_command_syntax_verified':False}
        return out
    except (CatalogError,BackendContractError,KeyError,TypeError) as exc:
        return dict(out,route='BLOCKED_PROVIDER_CATALOG',execution_status='BLOCKED',model=None,
                    model_effort_selectable=False,reason=str(exc))


# ---------- query / stats ----------
def _score(task, axes_str, rec):
    qt, rt = _tokens(task), _tokens(rec.get("task"))
    kw = len(qt & rt) / (len(qt | rt) or 1)
    qa = {x.strip() for x in (axes_str or "").split(",") if x.strip()}
    ra = {x.strip() for x in (rec.get("axes") or "").split(",") if x.strip()}
    ax = len(qa & ra) / 4 if qa else 0
    return kw * 0.6 + ax * 0.4


def cmd_query(a):
    own = load_registry(a.registry).records
    legacy = read_legacy_registry() if not a.no_legacy else []
    pool = own + legacy
    cohort = {
        "vendor": a.vendor,
        "surface": a.surface,
        "model_family": a.model_family,
        "task_family": a.task_family,
        "role": a.role,
    }
    cohort = {k: v for k, v in cohort.items() if v is not None}
    if cohort:
        pool = [record for record in pool if _record_matches_cohort(record, cohort)]
    scored = [(round(_score(a.task, a.axes, r), 3), r) for r in pool]
    scored = [x for x in scored if x[0] > 0.08]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [r for _s, r in scored[:6]]
    usable = usable_attempts(top, cohort=cohort)
    decision = override_decision(top, failcost="low", cohort=cohort)
    print(json.dumps({
        "matched": len(top),
        "usable_for_override": len(usable),
        "evidence": decision,
        "candidates": [{
            "worker": r.get("worker"), "vendor": r.get("vendor"),
            "model": r.get("model"), "effort": r.get("effort"),
            "outcome": r.get("outcome"), "verification_grade": r.get("verification_grade", "V0"),
            "source": r.get("_source", "own_registry"), "task": r.get("task"),
        } for r in top],
        "_meaning": "Candidates are observed recorded outcomes, not a complete success rate.",
    }, ensure_ascii=False, indent=2))


def cmd_stats(a):
    load = load_registry(a.registry)
    by = {}
    for r in load.records:
        if r.get("event_type", "attempt_final") != "attempt_final":
            continue
        k = f"{r.get('worker') or r.get('vendor')}·{r.get('model')}·{r.get('effort')}"
        d = by.setdefault(k, {"success": 0, "fail": 0, "partial": 0, "V0": 0, "V2+": 0})
        d[r.get("outcome", "partial")] = d.get(r.get("outcome", "partial"), 0) + 1
        if r.get("verification_grade") in ("V2", "V3"):
            d["V2+"] += 1
        else:
            d["V0"] += 1
    print(json.dumps({
        "total": len(load.records),
        "invalid_lines": len(load.invalid),
        "by_combo": by,
        "_meaning": "These are observed recorded outcomes, not a complete success rate. "
                    "Recording is operator-declared and may be incomplete or biased toward successes.",
    }, ensure_ascii=False, indent=2))


def cmd_session(a):
    print(json.dumps(session(a.surface), ensure_ascii=False, indent=2))


def cmd_validate(a):
    load = load_registry(a.registry)
    attempts = [
        r for r in load.records if r.get("event_type", "attempt_final") == "attempt_final"
    ]
    events = [
        r for r in load.records if r.get("event_type") == "attempt_invalidation"
    ]
    ids = [r.get("attempt_id") for r in attempts if r.get("attempt_id")]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    event_ids = [r.get("event_id") for r in events if r.get("event_id")]
    duplicate_events = sorted({i for i in event_ids if event_ids.count(i) > 1})
    dangling = sorted({
        r.get("target_attempt_id") for r in events
        if r.get("target_attempt_id") not in set(ids)
    })
    unsafe = [
        {"record": r.get("attempt_id") or r.get("event_id"), "error": issue}
        for r in load.records if (issue := _unsafe_registry_payload(r))
    ]
    print(json.dumps({
        "records": len(load.records),
        "attempt_records": len(attempts),
        "invalidation_events": len(events),
        "invalid_lines": len(load.invalid),
        "invalid_detail": [{"line": n, "error": e} for n, e in load.invalid],
        "duplicate_attempt_ids": dupes,
        "duplicate_event_ids": duplicate_events,
        "dangling_invalidation_targets": dangling,
        "unsafe_payloads": unsafe,
        "healthy": not load.invalid and not dupes and not duplicate_events and not dangling
                   and not unsafe,
        "_note": "Invalid lines are reported, never silently skipped. This command does not rewrite "
                 "the registry.",
    }, ensure_ascii=False, indent=2))


def _parse_axes(s):
    out = {}
    for part in (s or "").split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def cmd_recommend(a):
    axes = _parse_axes(a.axes)
    axes_ext = _parse_axes(a.axes_ext)
    required_core = set(LEGACY_AXES)
    required_ext = {
        "handoff_cost", "spec_readiness", "decomposability",
        "context_dependency", "verifier_available",
    }
    missing_core = sorted(required_core - set(axes))
    missing_ext = sorted(required_ext - set(axes_ext))
    valid_core = {
        "verifiable": {"yes", "partial", "no"},
        "failcost": {"low", "mid", "high"},
        "volume": {"low", "high"},
        "depth": {"shallow", "mid", "deep"},
    }
    invalid_core = {
        key: axes.get(key) for key, allowed in valid_core.items()
        if key in axes and axes.get(key) not in allowed
    }
    if missing_core or missing_ext or invalid_core:
        print(json.dumps({
            "route": "NEEDS_AXES",
            "router_version": ROUTER_VERSION,
            "error": "A recommendation requires explicit classification of the next bounded action",
            "missing_core_axes": missing_core,
            "missing_extended_axes": missing_ext,
            "invalid_core_axes": invalid_core,
        }, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    axes_ext.setdefault("volume", axes.get("volume"))
    if a.role:
        axes_ext["role"] = a.role
    records = load_registry(a.registry).records
    availability = _parse_axes(a.model_availability)
    caps = load_capabilities()
    inventory = None
    result = recommend(
        a.task, axes, axes_ext, caps, records,
        surface=a.surface,
        backends_path=a.backends,
        candidate_model=a.candidate_model,
        rollout_stage=a.rollout_stage,
        quota_state=a.quota_state,
        optimization_goal=a.optimization_goal,
        model_availability=availability,
        requested_model=a.model, requested_effort=a.effort, provider_executable=a.executable or a.codex_executable,
        codex_home=a.codex_home, use_catalog=True,
    )
    if inventory is not None:
        result["codex_inventory"] = inventory
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_record(a):
    rec = build_record(
        task=a.task, axes=_parse_axes(a.axes), axes_ext=_parse_axes(a.axes_ext),
        worker=a.worker, outcome=a.outcome, attempt_id=a.attempt_id,
        parent_attempt_id=a.parent_attempt_id, vendor=a.vendor, surface=a.surface,
        model_requested=a.model_requested, model_observed=a.model_observed,
        effort_requested=a.effort_requested, effort_observed=a.effort_observed,
        verification_grade=a.verification_grade, verification_method=a.verification_method,
        verifier_role=a.verifier_role, verification_evidence=a.verification_evidence,
        recommended_route=a.recommended_route, actual_route=a.actual_route,
        override_reason=a.override_reason, cost_value=a.cost_value, cost_unit=a.cost_unit,
        cost_basis=a.cost_basis, minutes=a.minutes, reason=a.reason or "", notes=a.notes or "",
        comparison_scope=a.comparison_scope, task_family=a.task_family, role=a.role,
        rollout_stage=a.rollout_stage, model_family_value=a.model_family,
        task_origin=a.task_origin,
    )
    if rec["verification_grade"] == "V0" and rec["outcome"] == "success":
        print(json.dumps({
            "warning": "V0 = self-report. Stored, but it will never override the heuristic.",
        }, ensure_ascii=False), file=sys.stderr)
    append_record(a.registry or REGISTRY, rec)
    print(json.dumps({"recorded": rec}, ensure_ascii=False, indent=2))


def cmd_invalidate(a):
    event = build_invalidation_event(
        target_attempt_id=a.target_attempt_id,
        reason_code=a.reason_code,
        evidence=a.verification_evidence,
        event_id=a.event_id,
    )
    append_record(a.registry or REGISTRY, event)
    print(json.dumps({"recorded": event}, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "catalog":
        from provider_catalog import main as catalog_main
        raise SystemExit(catalog_main())
    # --registry is accepted both before and after the subcommand
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--registry", default=None,
                        help="registry path (default: this skill's own registry.jsonl)")

    ap = argparse.ArgumentParser(description="cross-vendor model/effort router",
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("recommend", parents=[common])
    r.add_argument("task")
    r.add_argument("--axes", default="")
    r.add_argument("--axes-ext", dest="axes_ext", default="")
    r.add_argument("--surface", default=None, help="codex | claude | grok | agy")
    r.add_argument("--backends", default=None, help="read-only backends.json path")
    r.add_argument("--role", default=None)
    r.add_argument("--model", default=None, help="Exact observed ID or latest[:family]; separate from Fable shadow")
    r.add_argument("--effort", default=None, help="Exact supported effort; native none/embedded variants respected")
    r.add_argument("--executable", default=None, help="Configured absolute provider CLI for DIRECT metadata")
    r.add_argument("--candidate-model", dest="candidate_model", default=None)
    r.add_argument("--rollout-stage", dest="rollout_stage", choices=["v2", "v3"], default=None)
    r.add_argument("--quota-state", dest="quota_state",
                   choices=["available", "limited", "unavailable", "unknown"], default=None)
    r.add_argument("--optimization-goal", dest="optimization_goal",
                   choices=list(OPT_GOALS), default=None)
    r.add_argument("--model-availability", dest="model_availability", default="",
                   help="model=available|limited|unavailable comma list")
    r.add_argument("--codex-home", dest="codex_home", default=None,
                   help="active account's Codex home; default: ancestor Codex process")
    r.add_argument("--codex-executable", dest="codex_executable", default=None,
                   help="Codex executable for bounded model/list; default: ancestor process")
    r.set_defaults(fn=cmd_recommend)

    q = sub.add_parser("query", parents=[common])
    q.add_argument("task")
    q.add_argument("--axes", default="")
    q.add_argument("--no-legacy", action="store_true")
    q.add_argument("--vendor", default=None)
    q.add_argument("--surface", default=None)
    q.add_argument("--model-family", dest="model_family", default=None)
    q.add_argument("--task-family", dest="task_family", default=None)
    q.add_argument("--role", default=None)
    q.set_defaults(fn=cmd_query)

    rec = sub.add_parser("record", parents=[common])
    rec.add_argument("--task", required=True)
    rec.add_argument("--worker", required=True)
    rec.add_argument("--outcome", required=True, choices=list(VALID_OUTCOMES))
    rec.add_argument("--attempt-id", dest="attempt_id", required=True)
    rec.add_argument("--parent-attempt-id", dest="parent_attempt_id", default=None)
    rec.add_argument("--axes", default="")
    rec.add_argument("--axes-ext", dest="axes_ext", default="")
    rec.add_argument("--vendor", default=None)
    rec.add_argument("--surface", default=None)
    rec.add_argument("--model-requested", dest="model_requested", default=None)
    rec.add_argument("--model-observed", dest="model_observed", default=None)
    rec.add_argument("--effort-requested", dest="effort_requested", default=None)
    rec.add_argument("--effort-observed", dest="effort_observed", default=None)
    rec.add_argument("--verification-grade", dest="verification_grade",
                     default="V0", choices=["V0", "V1", "V2", "V3"])
    rec.add_argument("--verification-method", dest="verification_method", default=None)
    rec.add_argument("--verifier-role", dest="verifier_role", default=None)
    rec.add_argument("--verification-evidence", dest="verification_evidence", default=None)
    rec.add_argument("--recommended-route", dest="recommended_route", default=None)
    rec.add_argument("--actual-route", dest="actual_route", default=None)
    rec.add_argument("--override-reason", dest="override_reason", default=None)
    rec.add_argument("--cost-value", dest="cost_value", default=None)
    rec.add_argument("--cost-unit", dest="cost_unit", default="unknown",
                     choices=["usd", "quota", "unknown"])
    rec.add_argument("--cost-basis", dest="cost_basis", default="unknown",
                     choices=["metered", "estimated", "subscription", "unknown"])
    rec.add_argument("--minutes", default=None)
    rec.add_argument("--reason", default="")
    rec.add_argument("--notes", default="")
    rec.add_argument("--comparison-scope", dest="comparison_scope", default=None)
    rec.add_argument("--model-family", dest="model_family", default=None)
    rec.add_argument("--task-family", dest="task_family", default=None)
    rec.add_argument("--role", default=None)
    rec.add_argument("--rollout-stage", dest="rollout_stage", choices=["v2", "v3"], default=None)
    rec.add_argument("--task-origin", dest="task_origin",
                     choices=["real", "synthetic"], default=None)
    rec.set_defaults(fn=cmd_record)

    inv = sub.add_parser("invalidate", parents=[common])
    inv.add_argument("--target-attempt-id", dest="target_attempt_id", required=True)
    inv.add_argument("--reason-code", dest="reason_code", required=True)
    inv.add_argument("--verification-evidence", dest="verification_evidence", required=True)
    inv.add_argument("--event-id", dest="event_id", required=True)
    inv.set_defaults(fn=cmd_invalidate)

    s = sub.add_parser("session", parents=[common])
    s.add_argument("--surface", default=None,
                   help="claude-code-cli | codex-cli (default: $AWO_ROUTER_SURFACE)")
    s.set_defaults(fn=cmd_session)

    sub.add_parser("stats", parents=[common]).set_defaults(fn=cmd_stats)
    sub.add_parser("validate", parents=[common]).set_defaults(fn=cmd_validate)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
