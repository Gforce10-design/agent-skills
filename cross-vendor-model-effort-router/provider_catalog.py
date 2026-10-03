"""Read-only provider metadata and shared exact model/effort resolution.

Catalog observation is not generation, billing, quota, or provider identity proof.
No credentials are read; CLI subprocesses are restricted to metadata commands.
"""
import argparse
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

PROVIDERS = {'codex': 'codex', 'codex-cli': 'codex', 'claude': 'claude',
             'claude-code': 'claude', 'claude-code-cli': 'claude',
             'grok': 'grok', 'grok-cli': 'grok', 'agy': 'agy', 'agy-cli': 'agy'}
SAFE_ID = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,159}$')
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')
GROK_EFFORT_SOURCE = 'https://docs.x.ai/developers/model-capabilities/text/reasoning'


class CatalogError(ValueError):
    pass


def provider_name(value):
    try:
        return PROVIDERS[value]
    except KeyError:
        raise CatalogError('unsupported provider surface')


def _now(value=None):
    return value or datetime.now(timezone.utc)


def _stamp(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc)
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise CatalogError('timestamp must have timezone')
    return result


def _hash(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:16]


def _metadata(executable, args, timeout=10, env=None):
    binary = Path(executable)
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise CatalogError('configured executable must be an existing absolute executable')
    if args not in (['models'], ['--version']):
        raise CatalogError('non-metadata command refused')
    proc = subprocess.Popen([str(binary), *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    data = bytearray()
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() > deadline:
                raise CatalogError('metadata timeout')
            for key, _ in selector.select(.1):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise CatalogError('metadata output limit')
        if proc.wait(timeout=max(.1, deadline-time.monotonic())):
            raise CatalogError('metadata command failed')
        return data.decode('utf-8')
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=2)


def model_family(model, provider):
    """Versions/effort variants remain distinct; families only group alternatives."""
    if provider == 'codex':
        match = re.fullmatch(r'gpt-(\d+(?:\.\d+)*)(?:-(.+))?', model)
        if match:
            return 'gpt-' + (match.group(2) or 'base')
    if provider == 'claude':
        match = re.match(r'(?:claude-)?(haiku|sonnet|opus|fable)-', model)
        if match:
            return match.group(1)
    if provider == 'grok':
        match = re.fullmatch(r'grok-\d+(?:\.\d+)*(.*)', model)
        if match:
            return 'grok' + match.group(1)
    if provider == 'agy':
        label = re.sub(r'-(low|medium|high|xhigh|max)$', '', model)
        if label.startswith('claude-'):
            return re.sub(r'-\d+(?:-\d+)*$', '', label)
        return re.sub(r'-\d+(?:\.\d+)*-', '-', label)
    return 'unknown:' + model


def _version(model):
    # Ignore date suffix for ordering Claude major/minor family versions.
    nums = re.findall(r'\d+', model)
    return tuple(int(n) for n in nums if len(n) < 8)


def _row(provider, model, efforts, *, label=None, capabilities=None, **extra):
    valid = isinstance(model, str) and bool(SAFE_ID.fullmatch(model))
    known_efforts = isinstance(efforts, list) and all(e in EFFORTS for e in efforts)
    reason = None
    if not valid:
        reason = 'unsafe_or_missing_model_id'
    elif 'fable' in model.lower():
        reason = 'experimental_shadow_only'
    elif known_efforts and not efforts and provider != 'grok':
        reason = 'effort_metadata_empty'
    elif not known_efforts:
        reason = 'unsupported_effort_metadata'
    row = {'provider': provider, 'canonical_model_id': model, 'cli_model': model,
           'label': label or model, 'family': model_family(model, provider) if valid else 'unknown',
           'version': list(_version(model)) if valid else [], 'supported_efforts': efforts,
           'capabilities': capabilities, 'eligible': reason is None, 'eligibility_reason': reason,
           'model_evidence_keys': [model] if valid else []}
    row.update(extra)
    return row


def _finish(provider, rows, *, source, fetched_at, expires_at, account_scope,
            now=None, status=None, **extra):
    current = _now(now)
    fetched, expiry = _stamp(fetched_at), _stamp(expires_at)
    fresh = fetched <= current <= expiry
    status = status or ('AVAILABLE' if fresh else 'STALE')
    if not fresh or status != 'AVAILABLE':
        for row in rows:
            row['eligible'] = False
            row['eligibility_reason'] = status.lower()
    latest = {}
    for row in rows:
        family = row['family']
        if row['eligible'] and not family.startswith('unknown:'):
            previous = latest.get(family)
            if previous is None or tuple(row['version']) > tuple(previous['version']):
                latest[family] = row
    return {'provider': provider, 'status': status, 'models': rows,
            'current_by_family': {f: {'canonical_model_id': r['canonical_model_id'],
                'version': r['version'], 'variants': [x['canonical_model_id'] for x in rows
                if x['family'] == f and x['version'] == r['version'] and x['eligible']]}
                for f, r in latest.items()},
            'source': source, 'freshness': {'fresh': fresh, 'fetched_at': fetched.isoformat(),
                'expires_at': expiry.isoformat(), 'age_seconds': (current-fetched).total_seconds()},
            'account_scope': account_scope, 'generation_proof': False, **extra}


def parse_claude_caches(caches, *, now=None, cli_version=None, account_scope=None):
    """Never merge multiple CC account files or substitute CCD metadata."""
    native = [c for c in caches if isinstance(c, dict) and
              c.get('catalog', {}).get('surface') == 'cc']
    if not native:
        raise CatalogError('no native CC model catalog')
    rows = []
    for cache in native:
        models = cache['catalog'].get('config', {}).get('models')
        if not isinstance(models, list):
            raise CatalogError('invalid native CC model list')
        for model in models:
            thinking = model.get('thinking') or {}
            efforts = ['none'] if thinking.get('type') == 'none' else [
                x.get('id') for x in thinking.get('effort_options', [])]
            if thinking.get('type') not in ('none', 'effort', 'effort_and_mode'):
                efforts = None
            row = _row('claude', model.get('id'), efforts, label=model.get('name'),
                       capabilities=model.get('capabilities'), minimum_cli_version=model.get('min_claude_code_version'),
                       effort_status='native_model_catalog', thinking_type=thinking.get('type'))
            minimum = row['minimum_cli_version']
            if minimum and (not cli_version or _version(cli_version) < _version(minimum) or
                    tuple(map(int, re.findall(r'\d+', cli_version)[:3])) <
                    tuple(map(int, re.findall(r'\d+', minimum)[:3]))):
                row.update(eligible=False, eligibility_reason='minimum_cli_version_unmet')
            rows.append(row)
    return _finish('claude', rows, source='native_cc_model_catalog',
        fetched_at=max(c['fetchedAt'] for c in native), expires_at=min(c['staleAt'] for c in native),
        account_scope=account_scope or {'kind': 'native_cc_cache', 'candidate_accounts': len(native)},
        now=now, status='AMBIGUOUS_ACCOUNT' if len(native) != 1 else ('CACHE_IDENTITY_UNVERIFIED' if _stamp(native[0]['fetchedAt']) <= _now(now) <= _stamp(native[0]['staleAt']) else None),
        runtime_version=cli_version,account_identity_verified=False)


def parse_cli_models(provider, text, *, now=None, account_scope=None):
    provider = provider_name(provider)
    rows = []
    if provider == 'grok':
        for line in text.splitlines():
            match = re.fullmatch(r'\s*[*-]\s+([a-zA-Z0-9][a-zA-Z0-9._-]+)(?:\s+\(default\))?\s*', line)
            if not match:
                continue
            model = match.group(1)
            # Official documentation names these exact versions; do not extrapolate future models.
            efforts = {'grok-4.5': ['low', 'medium', 'high'],
                       'grok-4.6': ['low', 'medium', 'high', 'xhigh'],
                       'grok-4.7': ['low', 'medium', 'high', 'xhigh']}.get(model, [])
            rows.append(_row(provider, model, efforts, effort_status='documented' if efforts else 'unknown_default_only',
                             effort_source=GROK_EFFORT_SOURCE if efforts else None))
    elif provider == 'agy':
        for line in text.splitlines():
            parts = line.split('\t', 1)
            if len(parts) != 2:
                continue
            model, label = parts
            match = re.search(r'-(low|medium|high|xhigh|max)$', model)
            label_match = re.search(r'\((Low|Medium|High|Xhigh|Max)\)$', label)
            embedded = match.group(1) if match else None
            row = _row(provider, model, [embedded] if embedded else None, label=label,
                       effort_status='embedded_model_variant')
            row['cli_model']=label
            if not label_match or label_match.group(1).lower() != embedded:
                row.update(eligible=False, eligibility_reason='embedded_effort_label_mismatch')
            rows.append(row)
    else:
        raise CatalogError('not a text CLI provider')
    if not rows:
        raise CatalogError('model metadata returned no model rows')
    fetched = _now(now)
    from datetime import timedelta
    return _finish(provider, rows, source=provider+'_models', fetched_at=fetched.isoformat(),
                   expires_at=(fetched+timedelta(minutes=15)).isoformat(),
                   account_scope=account_scope or {'kind': 'configured_cli_context'}, now=now)


def probe_claude_models(executable, *, home=None, timeout=20):
    """Only SDK control initialize; no user/prompt messages, no tool/plugin/MCP loads."""
    import signal
    import tempfile
    binary=Path(executable)
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary,os.X_OK):
        raise CatalogError('configured Claude executable invalid')
    argv=[str(binary),'--safe-mode','--print','--verbose','--no-session-persistence',
          '--input-format','stream-json','--output-format','stream-json','--tools','',
          '--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--setting-sources','',
          '--permission-mode','dontAsk','--permission-prompts','none']
    request={'type':'control_request','request_id':'router-model-catalog-probe',
             'request':{'subtype':'initialize','hooks':{},'sdkMcpServers':[]}}
    env=dict(os.environ)
    if home:env['HOME']=str(home)
    with tempfile.TemporaryDirectory(prefix='router-catalog-') as cwd:
        proc=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL,start_new_session=True)
        selector=selectors.DefaultSelector();selector.register(proc.stdout,selectors.EVENT_READ)
        buffer=b'';count=0;deadline=time.monotonic()+timeout
        try:
            proc.stdin.write((json.dumps(request)+'\n').encode());proc.stdin.flush()
            while time.monotonic()<deadline and selector.get_map():
                for key,_ in selector.select(.1):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(key.fileobj);continue
                    count+=len(chunk)
                    if count>1048576:raise CatalogError('Claude metadata output limit')
                    buffer+=chunk
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        row=json.loads(line)
                        if row.get('type') in ('assistant','user','result'):
                            raise CatalogError('unexpected generation message during metadata probe')
                        response=row.get('response',{})
                        if row.get('type')=='control_response' and response.get('request_id')==request['request_id']:
                            models=response.get('response',{}).get('models')
                            if response.get('subtype')!='success' or not isinstance(models,list):
                                raise CatalogError('Claude initialize metadata failed')
                            return [{k:m[k] for k in ('value','displayName','description','supportsEffort',
                                'supportedEffortLevels','supportsAdaptiveThinking','supportsFastMode',
                                'supportsAutoMode') if k in m} for m in models if isinstance(m,dict)]
            raise CatalogError('Claude initialize metadata timeout')
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            raise CatalogError('Claude initialize metadata protocol failure') from exc
        finally:
            selector.close()
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=3)


def parse_claude_live(models, *, caches=(), now=None, account_scope=None):
    native=[c for c in caches if c.get('catalog',{}).get('surface')=='cc']
    public_models=native[0]['catalog'].get('config',{}).get('models',[]) if len(native)==1 and _stamp(native[0]['fetchedAt']) <= _now(now) <= _stamp(native[0]['staleAt']) else []
    rows=[]
    for m in models:
        observed=m.get('value');label=m.get('displayName',observed)
        effort=m.get('supportedEffortLevels') if m.get('supportsEffort') else ['none']
        name_hint=(m.get('description','').split(' · ',1)[0] if observed=='default' else label)
        exact=[x for x in public_models if x.get('name')==name_hint]
        canonical=exact[0]['id'] if len(exact)==1 else observed
        row=_row('claude',canonical,effort,label=label,observed_model_id=observed,
            identity_source='fresh_cc_name_mapping_unverified' if canonical!=observed else 'live_cli_id',
            account_identity_verified=False,
            capabilities={k:m[k] for k in ('supportsAdaptiveThinking','supportsFastMode','supportsAutoMode') if k in m})
        row['cli_model']=observed
        if not observed.startswith('claude-') and canonical==observed:
            row['model_evidence_keys']=[]
            row['identity_limit']='alias-only metadata; exact runtime model identity not established'
        if 'fable' in ' '.join(str(x) for x in (canonical,observed,label,m.get('description',''))).lower():
            row.update(eligible=False,eligibility_reason='experimental_shadow_only')
        if observed in ('opus','sonnet','haiku','fable'):
            row['family']=observed
            row['version']=list(_version(label))
        if observed=='default':
            row['family']='default'
        if not SAFE_ID.fullmatch(observed or ''):
            row.update(eligible=False,eligibility_reason='unsafe_cli_model')
        rows.append(row)
    if not rows:raise CatalogError('Claude initialize returned no models')
    current=_now(now)
    from datetime import timedelta
    return _finish('claude',rows,source='claude_control_initialize_models',
        fetched_at=current.isoformat(),expires_at=(current+timedelta(minutes=15)).isoformat(),
        account_scope=account_scope or {'kind':'configured_cli_initialize'},now=now,
        user_messages_sent=0,account_fields_retained=False)


def load_catalog(provider, *, executable=None, codex_home=None, claude_catalog_dir=None,
                 now=None, refresh=True, home=None):
    provider = provider_name(provider)
    try:
        if executable and not Path(executable).is_absolute():
            raise CatalogError('configured executable must be absolute')
        if provider == 'codex':
            from codex_inventory import active_codex_runtime, probe_model_list, parse_cache
            runtime_home, binary, scope = active_codex_runtime(codex_home, executable)
            if runtime_home is None:
                raise CatalogError('active Codex home unresolved')
            error = None
            try:
                raw = probe_model_list(runtime_home, binary) if refresh else None
            except (OSError, ValueError, subprocess.SubprocessError, TimeoutError) as exc:
                raw = None
                error = type(exc).__name__
            if raw is None:
                # Cache fallback cannot silently claim live identity/version. Explicitly scoped cache is visible.
                raw = parse_cache(runtime_home/'models_cache.json', now=now)
                source = 'account_models_cache'
                fresh = False  # cache binding needs live account/runtime proof before selectable
            else:
                source = 'active_app_server_model_list'
                fresh = True
            rows = [_row(provider, key, value, capabilities=raw.get('model_metadata', {}).get(key))
                    for key, value in raw['models'].items()]
            for row in rows:
                if (row['capabilities'] or {}).get('hidden'):
                    row.update(eligible=False,eligibility_reason='hidden_model')
            from datetime import timedelta
            captured = _stamp(raw['fetched_at'])
            return _finish(provider, rows, source=source, fetched_at=captured.isoformat(),
                expires_at=(captured+timedelta(hours=24)).isoformat(), now=now,
                status=None if fresh else 'CACHE_IDENTITY_UNVERIFIED',
                account_scope={'kind': scope, 'home_hash': _hash(runtime_home)},
                probe_error=error, executable=str(binary) if binary else None)
        binary = executable or shutil.which(provider)
        if provider == 'claude':
            directory = Path(claude_catalog_dir or Path(home or Path.home())/'.claude/cache/model-catalog')
            def read_cc():
                paths=sorted(directory.glob('*-cc.json')); result=[]
                for path in paths:
                    try:
                        if path.stat().st_size > 2*1024*1024:
                            return []
                        data=json.loads(path.read_text())
                        if data.get('catalog',{}).get('surface')!='cc':return []
                        result.append(data)
                    except (OSError,ValueError,TypeError):
                        return []  # malformed/ambiguous metadata cannot establish an exact mapping
                return result
            caches=read_cc()
            try:
                live = probe_claude_models(binary, home=home)
            except CatalogError:
                live=None
            if live is not None:
                return parse_claude_live(live, caches=read_cc(), now=now,
                    account_scope={'kind':'configured_cli_initialize','home_hash':_hash(home or Path.home())})
            version_text = _metadata(binary, ['--version']) if binary else ''
            version = re.search(r'\d+\.\d+\.\d+', version_text)
            return parse_claude_caches(caches, now=now, cli_version=version.group() if version else None,
                account_scope={'kind': 'native_cc_cache', 'candidate_accounts':len(caches),
                               'directory_hash':_hash(directory)})
        env = dict(os.environ)
        if home:
            env['HOME'] = str(home)
        text = _metadata(binary, ['models'], env=env)
        return parse_cli_models(provider, text, now=now,
            account_scope={'kind':'configured_cli_context','home_hash':_hash(home or Path.home())})
    except (CatalogError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        return {'provider':provider,'status':'UNAVAILABLE','models':[],
                'current_by_family':{},'source':'metadata_unavailable',
                'freshness':{'fresh':False},'account_scope':{'kind':'unresolved'},
                'reason':str(exc) if isinstance(exc,CatalogError) else type(exc).__name__,
                'generation_proof':False}


def resolve(provider, model='latest', effort=None, *, executable=None, codex_home=None,
            catalog=None, family=None, claude_catalog_dir=None, home=None, now=None):
    provider = provider_name(provider)
    catalog = catalog if catalog is not None else load_catalog(provider, executable=executable,
        codex_home=codex_home, claude_catalog_dir=claude_catalog_dir,home=home,now=now)
    if catalog.get('provider') != provider or catalog.get('status') != 'AVAILABLE' or not catalog.get('freshness',{}).get('fresh'):
        raise CatalogError('catalog not selectable: '+str(catalog.get('status')))
    freshness = catalog['freshness']
    if _now(now) > _stamp(freshness['expires_at']):
        raise CatalogError('catalog expired')
    rows = catalog['models']
    if model == 'latest' or model.startswith('latest:'):
        family = model.split(':',1)[1] if ':' in model else family
        if not family:
            family = {'codex':'gpt-sol','claude':'opus','grok':'grok','agy':'gemini-flash'}[provider]
        candidates = [r for r in rows if r.get('eligible') and r['family']==family]
        if not candidates:
            raise CatalogError('no eligible current family: '+family)
        newest = max(tuple(r['version']) for r in candidates)
        candidates = [r for r in candidates if tuple(r['version'])==newest]
        if effort is not None:
            candidates = [r for r in candidates if effort in (r['supported_efforts'] or []) or (
                effort=='config' and r.get('effort_status')=='unknown_default_only')]
        if not candidates:
            raise CatalogError('latest family does not support requested effort')
        if len(candidates)>1:
            candidates = [r for r in candidates if 'medium' in (r['supported_efforts'] or [])]
        if len(candidates)!=1:
            raise CatalogError('ambiguous latest effort variant; supply exact effort/model')
        row = candidates[0]
    else:
        if not SAFE_ID.fullmatch(model):
            raise CatalogError('unsafe model ID')
        candidates = [r for r in rows if r['canonical_model_id']==model or r.get('observed_model_id')==model]
        if len(candidates)>1:
            candidates=[r for r in candidates if r.get('observed_model_id')!='default']
        if len(candidates)!=1:
            raise CatalogError('model absent or ambiguous in catalog')
        row=candidates[0]
    if not row.get('eligible'):
        raise CatalogError(row.get('eligibility_reason') or 'ineligible model')
    supported=row['supported_efforts'] or []
    effort = effort or ('medium' if 'medium' in supported else 'none' if 'none' in supported
                       else supported[0] if len(supported)==1 else 'config' if not supported else None)
    if effort not in supported and not (effort=='config' and row.get('effort_status')=='unknown_default_only'):
        raise CatalogError('unsupported effort for exact model')
    mode,flag,key = {'codex':('config','--config','model_reasoning_effort'),
                     'claude':('native','--effort',None),
                     'grok':('native','--reasoning-effort',None),
                     'agy':('embedded',None,None)}[provider]
    if (provider=='claude' and effort=='none') or effort=='config':
        mode,flag,key='none',None,None
    return {'provider':provider,'canonical_model_id':row['canonical_model_id'],
            'cli_model':row['cli_model'],'effort':effort,'model_evidence_keys':row['model_evidence_keys'],
            'effort_binding':{'mode':mode,'flag':flag,'config_key':key},'effort_mode':mode,
            'cli_effort_flag':flag,'expected_usage_keys':row['model_evidence_keys'],
            'source':catalog['source'],'freshness':catalog['freshness'],
            'account_scope':catalog['account_scope'],'runtime_scope':catalog['account_scope'],
            'eligible':True,'reason':'exact observed model/effort binding',
            'label':row['label'],'family':row['family'],
            'identity_source':row.get('identity_source','observed_catalog_id'),
            'account_identity_verified':row.get('account_identity_verified',False),
            'identity_limit':row.get('identity_limit','Expected CLI metadata identity only; no provider-signed/runtime observation'),
            'alternatives':[{'canonical_model_id':r['canonical_model_id'],'supported_efforts':r['supported_efforts'],
                'eligible':r['eligible'],'reason':r['eligibility_reason']} for r in rows if r is not row]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['catalog','resolve'])
    parser.add_argument('--provider','--surface',dest='provider',default='all',choices=['all',*PROVIDERS])
    parser.add_argument('--executable')
    parser.add_argument('--codex-home')
    parser.add_argument('--home')
    parser.add_argument('--claude-catalog-dir')
    parser.add_argument('--model',default='latest')
    parser.add_argument('--effort')
    parser.add_argument('--family')
    args=parser.parse_args()
    kw={k:getattr(args,k) for k in ('executable','codex_home','home','claude_catalog_dir')}
    try:
        if args.provider=='all':
            if args.command!='catalog' or args.executable:
                raise CatalogError('all is catalog-only without a shared executable')
            catalogs={name:load_catalog(name,**kw) for name in ('codex','claude','grok','agy')}
            print(json.dumps({'catalogs':catalogs,'generation_proof':False},indent=2))
            return 0 if all(c['status']=='AVAILABLE' for c in catalogs.values()) else 2
        result=load_catalog(args.provider,**kw) if args.command=='catalog' else resolve(
            args.provider,args.model,args.effort,family=args.family,**kw)
        print(json.dumps(result,indent=2))
        return 0 if result.get('status','AVAILABLE')=='AVAILABLE' else 2
    except CatalogError as exc:
        print(json.dumps({'status':'UNAVAILABLE','provider':args.provider,'reason':str(exc)}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
