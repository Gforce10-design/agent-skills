"""Read the active Codex account's public model metadata. No auth material is read."""
import json
import hashlib
import os
import re
import select
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

MODEL_ID = re.compile(r"^gpt-(\d+(?:\.\d+)*?)-(luna|sol|astra)$")
# Only the runtime state DB identifies its home. Other account session files
# can stay open during cross-account history access and are not identity proof.
ACCOUNT_HOME = re.compile(r"(.*/codex-accounts/[^/]+/home)/state_\d+\.sqlite(?:-(?:wal|shm))?$")
NATIVE_HOME = re.compile(r"(.*/\.codex)/state_\d+\.sqlite(?:-(?:wal|shm))?$")
MAX_AGE_HOURS = 24


def _run(args, timeout=2):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                          check=True).stdout


def active_codex_runtime(explicit=None, executable=None):
    """Use an explicit home or the *ancestor* Codex process, never a fleet scan."""
    configured_home = os.environ.get("CODEX_HOME")
    pid = os.getppid()
    for _ in range(12):
        try:
            fields = _run(["ps", "-p", str(pid), "-o", "ppid=", "-o", "comm="]).strip().split(None, 1)
            if len(fields) != 2:
                break
            parent, command = fields
            if Path(command).name == "codex":
                listing = _run(["lsof", "-a", "-p", str(pid), "-Fn"], timeout=3)
                homes = {m.group(1) for line in listing.splitlines() if line.startswith("n")
                         for pattern in (ACCOUNT_HOME, NATIVE_HOME)
                         for m in [pattern.match(line[1:])] if m}
                binaries = [Path(line[1:]) for line in listing.splitlines()
                            if line.startswith("n") and line.endswith("/bin/codex")]
                binary = Path(executable).resolve() if executable else (
                    binaries[0].resolve() if len(binaries) == 1 else None)
                if explicit:
                    return Path(explicit).expanduser().resolve(), binary, "explicit"
                if len(homes) == 1:
                    return Path(homes.pop()).resolve(), binary, "ancestor_codex_open_files"
                if configured_home:
                    return Path(configured_home).expanduser().resolve(), binary, "CODEX_HOME"
                break
            pid = int(parent)
            if pid <= 1:
                break
        except (OSError, ValueError, subprocess.SubprocessError):
            break
    if explicit or configured_home:
        return Path(explicit or configured_home).expanduser().resolve(), (
            Path(executable).resolve() if executable else None), (
                "explicit" if explicit else "CODEX_HOME")
    return None, None, "unresolved"


def active_codex_home(explicit=None):
    home, _, scope = active_codex_runtime(explicit)
    return home, scope


def _read_response(process, wanted_id, deadline, pending):
    while time.monotonic() < deadline:
        while b"\n" in pending[0]:
            line, _, pending[0] = pending[0].partition(b"\n")
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Codex response is not an object")
            if message.get("id") == wanted_id:
                return message
        ready, _, _ = select.select([process.stdout], [], [], max(0, deadline - time.monotonic()))
        if ready:
            chunk = os.read(process.stdout.fileno(), 65536)
            if chunk:
                pending[0] += chunk
                if len(pending[0]) > 2 * 1024 * 1024:
                    raise ValueError("model/list output limit exceeded")
                continue
            break
    raise TimeoutError("model/list did not respond")


def probe_model_list(home, executable, timeout=8):
    """Read current account metadata through Codex app-server; no generation call."""
    if not executable or not Path(executable).is_file():
        raise FileNotFoundError("active Codex executable unresolved")
    env = dict(os.environ, CODEX_HOME=str(home))
    process = subprocess.Popen([str(executable), "app-server", "--stdio"],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, env=env)
    deadline = time.monotonic() + timeout
    pending = [b""]
    try:
        def send(value):
            process.stdin.write(json.dumps(value, separators=(",", ":")) + "\n")
            process.stdin.flush()
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "model_router_inventory_probe", "version": "1.0.0"},
            "capabilities": {"experimentalApi": False}}})
        if "result" not in _read_response(process, 1, deadline, pending):
            raise ValueError("Codex initialization failed")
        send({"method": "initialized", "params": {}})
        models, metadata, cursor = {}, {}, None
        for page in range(20):
            params = {"limit": 100, "includeHidden": True}
            if cursor:
                params["cursor"] = cursor
            send({"id": page + 2, "method": "model/list", "params": params})
            response = _read_response(process, page + 2, deadline, pending)
            if "result" not in response:
                raise ValueError("Codex model/list failed")
            result = response["result"]
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise ValueError("Codex model/list has invalid data")
            for item in result["data"]:
                if not isinstance(item, dict):
                    raise ValueError("Codex model/list row is not an object")
                model = item.get("model") or item.get("id")
                if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", model):
                    continue
                levels = item.get("supportedReasoningEfforts")
                if not isinstance(levels, list):
                    raise ValueError("Codex model/list efforts are invalid")
                efforts = {v.get("reasoningEffort") for v in levels
                           if isinstance(v, dict)}
                efforts.discard(None)
                models[model] = sorted(efforts)
                metadata[model] = {key:item[key] for key in ("hidden", "displayName", "defaultReasoningEffort") if key in item}
            cursor = result.get("nextCursor")
            if cursor is not None and not isinstance(cursor, str):
                raise ValueError("Codex model/list cursor is invalid")
            if not cursor:
                break
        else:
            raise ValueError("Codex model/list exceeded page limit")
        if not models:
            raise ValueError("Codex model/list returned no models")
        return {"models": models, "model_metadata": metadata, "fetched_at": datetime.now(timezone.utc).isoformat(),
                "age_hours": 0, "fresh": True, "client_version": "active_app_server",
                "identity_hash": None}
    finally:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def parse_cache(path, now=None):
    """Return a strict, sanitized model list from the account-scoped Codex cache."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Codex cache has invalid model data")
    when = datetime.fromisoformat(data["fetched_at"].replace("Z", "+00:00"))
    if when.tzinfo is None:
        raise ValueError("cache timestamp lacks timezone")
    age_hours = ((now or datetime.now(timezone.utc)) - when).total_seconds() / 3600
    if age_hours < -0.1:
        raise ValueError("cache timestamp is in the future")
    models = {}
    metadata = {}
    for item in data["models"]:
        if not isinstance(item, dict):
            raise ValueError("Codex cache row is not an object")
        model = item.get("slug")
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", model):
            continue
        levels = item.get("supported_reasoning_levels")
        if not isinstance(levels, list):
            raise ValueError("Codex cache efforts are invalid")
        efforts = {v.get("effort") for v in levels
                   if isinstance(v, dict)}
        efforts.discard(None)
        models[model] = sorted(efforts)
        metadata[model] = {'hidden':item.get('visibility')!='list'}
    if not models:
        raise ValueError("cache has no visible models")
    return {"models": models, "model_metadata":metadata, "fetched_at": when.isoformat(),
            "age_hours": round(age_hours, 3), "fresh": age_hours <= MAX_AGE_HOURS,
            "client_version": str(data.get("client_version", "unknown")),
            "identity_hash": hashlib.sha256(json.dumps(data.get("identity"),
                sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]}


def newest_tier_models(models):
    """Pick the newest numeric version per role that supports normal efforts."""
    chosen = {}
    for model, efforts in models.items():
        match = MODEL_ID.fullmatch(model)
        if not match:
            continue
        if not {"low", "medium", "high"}.issubset(set(efforts)):
            continue
        version = tuple(int(part) for part in match.group(1).split("."))
        role = match.group(2)
        if role not in chosen or version > chosen[role][0]:
            chosen[role] = (version, model)
    return [chosen[role][1] for role in ("luna", "sol", "astra") if role in chosen]


def apply_inventory(caps, *, home=None, executable=None, now=None, refresh=True):
    """Update only DIRECT Codex candidates in memory; dispatcher pins stay untouched."""
    account_home, binary, scope = active_codex_runtime(home, executable)
    if not account_home:
        return {"status": "UNRESOLVED", "scope": scope}
    live_error = False
    try:
        catalog = probe_model_list(account_home, binary) if refresh else None
    except (OSError, ValueError, TypeError, AttributeError,
            TimeoutError, subprocess.SubprocessError):
        catalog = None
        live_error = True
    used_cache = catalog is None
    try:
        catalog = catalog or parse_cache(account_home / "models_cache.json", now=now)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError):
        return {"status": "REFRESH_FAILED", "scope": scope}
    if used_cache and not catalog["fresh"]:
        return {"status": "STALE_UNUSABLE", "scope": scope,
                "fetched_at": catalog["fetched_at"], "age_hours": catalog["age_hours"]}
    if used_cache and account_home.name == ".codex":
        try:
            if (account_home / "auth.json").stat().st_mtime > \
                    datetime.fromisoformat(catalog["fetched_at"]).timestamp():
                return {"status": "ACCOUNT_CHANGED_SINCE_CACHE", "scope": scope}
        except OSError:
            return {"status": "ACCOUNT_UNVERIFIED", "scope": scope}
    if used_cache:
        release_path = re.search(r"/releases/([^/]+)/bin/codex$", str(binary)) if binary else None
        if not release_path or not release_path.group(1).startswith(catalog["client_version"] + "-"):
            return {"status": "RUNTIME_VERSION_MISMATCH", "scope": scope,
                    "fetched_at": catalog["fetched_at"]}
    direct = caps["direct_execution"]["codex-cli"]
    selected = newest_tier_models(catalog["models"])
    # Keep the declared policy's three quality positions. A missing tier keeps
    # its static placeholder but is explicitly marked unavailable below.
    static = direct["recommendation_models"]
    by_role = {MODEL_ID.fullmatch(m).group(2): m for m in selected}
    for old in static:
        role = MODEL_ID.fullmatch(old).group(2)
        if role not in by_role:
            by_role[role] = old
    ladder = [by_role[r] for r in ("luna", "sol", "astra")]
    available = [model for model in ladder if model in selected]
    unavailable = [model for model in ladder if model not in available]
    direct["recommendation_models"] = ladder
    direct["models"] = list(catalog["models"])
    direct["selection_policy"]["base_model_by_depth"] = {
        "shallow": ladder[0], "mid": ladder[1], "deep": ladder[1]}
    direct["quality_floor"] = {
        "shallow_low_failcost": ladder[0], "mid": ladder[1],
        "deep": ladder[1], "high_failcost": ladder[2]}
    caps["_codex_account_inventory"] = {
        "captured_at": catalog["fetched_at"], "stale_after_days": 1,
        "available_recommendation_models": available,
        "official_but_not_exposed": unavailable,
        "model_efforts": catalog["models"],
    }
    base_status = "ACTIVE_RUNTIME_LIST" if not used_cache else "RECENT_ACCOUNT_CACHE"
    return {"status": base_status if not unavailable else base_status + "_PARTIAL",
            "scope": scope, "fetched_at": catalog["fetched_at"],
            "age_hours": catalog["age_hours"], "client_version": catalog["client_version"],
            "account_scope_hash": hashlib.sha256(str(account_home).encode()).hexdigest()[:16],
            "identity_hash": catalog["identity_hash"],
            "account_identity_verified": not used_cache,
            "source": "active_app_server_model_list" if not used_cache else "models_cache_json",
            "recommendation_models": ladder,
            "available_recommendation_models": available}
