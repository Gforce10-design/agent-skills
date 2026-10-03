"""Actual CLI/new-backend integrations using metadata-only fake provider processes."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime,timezone,timedelta

SKILL=Path(__file__).resolve().parents[1];FIX=Path(__file__).parent/'fixtures'
sys.path.insert(0,str(SKILL))
import provider_catalog as pc
import router

class RealCatalogBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.catalogs=json.loads((FIX/'catalog-backends.json').read_text())
        raw=json.loads((FIX/'claude-cc-catalogs.json').read_text())[0]
        now=datetime.now(timezone.utc);raw['fetchedAt']=int(now.timestamp()*1000)-1000
        raw['staleAt']=int((now+timedelta(hours=1)).timestamp()*1000)
        cache=self.root/'.claude/cache/model-catalog';cache.mkdir(parents=True)
        (cache/'test-account-cc.json').write_text(json.dumps(raw))
        self.stubs={}
        for provider in ('codex','claude','grok','agy'):
            script=self.root/provider
            text="""#!"""+sys.executable+"""
import json,os,sys,time
from pathlib import Path
provider=Path(sys.argv[0]).name
with Path("""+repr(str(self.root/'metadata-invocations.jsonl'))+""").open('a') as f:
 f.write(json.dumps({'provider':provider,'argv':sys.argv[1:],'HOME':os.environ.get('HOME'),'CODEX_HOME':os.environ.get('CODEX_HOME')})+'\\n')
fixture=Path("""+repr(str(FIX))+""")
if provider=='codex':
 for line in sys.stdin:
  m=json.loads(line)
  if m.get('method')=='initialize':print(json.dumps({'id':m['id'],'result':{}}),flush=True)
  if m.get('method')=='model/list':
   models=['gpt-6-luna','gpt-6-sol','gpt-6.1-sol','gpt-6-astra','gpt-5.4-mini']
   print(json.dumps({'id':m['id'],'result':{'data':[{'model':x,'supportedReasoningEfforts':[{'reasoningEffort':e} for e in ['low','medium','high']]} for x in models],'nextCursor':None}}),flush=True)
elif provider=='claude' and '--safe-mode' in sys.argv:
 m=json.loads(sys.stdin.readline())
 if m['type']!='control_request':raise SystemExit(7)
 models=json.loads((fixture/'claude-control-init-metadata.json').read_text())['models']
 print(json.dumps({'type':'control_response','response':{'request_id':m['request_id'],'subtype':'success','response':{'models':models}}}),flush=True)
 time.sleep(60)
elif provider in ('grok','agy') and sys.argv[1:]==['models']:
 print('\\n'.join(json.loads((fixture/(provider+'-models.json')).read_text())['sanitized_model_lines']))
else:raise SystemExit('non-metadata command refused')
"""
            script.write_text(text);script.chmod(0o755);self.stubs[provider]=str(script)
        for name,row in self.catalogs['workers'].items():
            dynamic=row['dynamic_loadout'];provider=dynamic['catalog_provider']
            dynamic['catalog_resolver_path']=str(SKILL/'provider_catalog.py')
            dynamic['catalog_resolver_sha256']=hashlib.sha256((SKILL/'provider_catalog.py').read_bytes()).hexdigest()
            dynamic['catalog_resolver_dependencies']={'codex_inventory.py':hashlib.sha256((SKILL/'codex_inventory.py').read_bytes()).hexdigest()}
            row['cli']['command']=self.stubs[provider]
            self.catalogs['trusted_executable_paths'][name]=self.stubs[provider]
        self.backends=self.root/'backends.json';self.backends.write_text(json.dumps(self.catalogs))
        self.env=dict(os.environ,HOME=str(self.root))
        self.axes='verifiable=yes,failcost=mid,volume=low,depth=mid'

    def tearDown(self):self.tmp.cleanup()

    def run_route(self,provider,route,extra=()):
        ext=('handoff_cost=high,spec_readiness=executable,decomposability=single,context_dependency=high,verifier_available=yes'
             if route=='DIRECT' else 'handoff_cost=low,spec_readiness=executable,decomposability=independent,context_dependency=low,verifier_available=yes')
        cmd=[sys.executable,str(SKILL/'router.py'),'recommend','bounded catalog integration','--surface',provider,
             '--axes',self.axes,'--axes-ext',ext,'--backends',str(self.backends),'--role','critic',
             '--executable',self.stubs[provider],'--codex-home',str(self.root/'conductor-home'),
             '--registry',str(self.root/'empty-registry.jsonl'),*extra]
        p=subprocess.run(cmd,env=self.env,capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr)
        return json.loads(p.stdout)

    def test_actual_cli_direct_and_delegate_all_four_providers(self):
        expected={'codex':'gpt-6.1-sol','claude':'claude-sonnet-5-5','grok':'grok-4.7','agy':'gemini-3.8-flash-medium'}
        for provider,model in expected.items():
            for route in ('DIRECT','DELEGATE'):
                with self.subTest(provider=provider,route=route):
                    result=self.run_route(provider,route)
                    self.assertEqual(result['route'],route,result)
                    self.assertEqual(result['model'],model,result)
                    self.assertEqual(result['effort'],'medium')
                    self.assertEqual(result['vendor'],{'codex':'openai','claude':'anthropic','grok':'xai','agy':'google'}[provider])
                    self.assertEqual(result['surface'],{'codex':'codex-cli','claude':'claude-code','grok':'grok-cli','agy':'agy-cli'}[provider])
                    self.assertNotIn('require --surface',result['reason'])
                    self.assertEqual(result['model_family'],result['provider_catalog_binding']['family'])
                    self.assertEqual(result['decision_source'],'policy_family_current_catalog')
                    if route=='DIRECT' and provider!='codex':
                        self.assertEqual(result['execution_contract']['fallback_argv'],[])
                        self.assertFalse(result['execution_contract']['headless_fallback_supported'])
                    self.assertEqual(result['selection_stages'][0]['model'],model)
                    self.assertEqual(result['provider_catalog_binding']['provider'],provider)
        calls=[json.loads(x) for x in (self.root/'metadata-invocations.jsonl').read_text().splitlines()]
        homes={r['CODEX_HOME'] for r in calls if r['provider']=='codex'}
        self.assertIn(str((self.root/'conductor-home').resolve()),homes)
        self.assertIn(str((self.root/'.codex').resolve()),homes)
        self.assertFalse((self.root/'empty-registry.jsonl').exists())

    def test_mechanical_catalog_roles_do_not_use_fixed_fleet_preference_gate(self):
        for provider,role in (('claude','general'),('agy','compatibility'),('grok','adversarial')):
            with self.subTest(provider=provider):
                r=self.run_route(provider,'DELEGATE',('--role',role,'--axes','verifiable=yes,failcost=low,volume=high,depth=shallow'))
                self.assertEqual(r['route'],'DELEGATE',r)
                self.assertNotIn('every worker is pinned',json.dumps(r))
                self.assertEqual(r['cost_comparison'],'unmeasured')

    def test_claude_proof_required_alias_only_delegate_refused(self):
        catalog=pc.parse_claude_live(json.loads((FIX/'claude-control-init-metadata.json').read_text())['models'])
        axes={'verifiable':'yes','failcost':'mid','volume':'low','depth':'mid'}
        ext={'handoff_cost':'low','spec_readiness':'executable','decomposability':'independent','context_dependency':'low','verifier_available':'yes'}
        r=router.recommend('bounded review',axes,ext,surface='claude',records=[],catalogs={'claude':catalog},backends_path=self.backends)
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG',r)
        self.assertEqual(r['reason'],'CLAUDE_MODEL_USAGE_IDENTITY_UNRESOLVED')
        ext['handoff_cost']='high';ext['context_dependency']='high';ext['decomposability']='single'
        r=router.recommend('bounded review',axes,ext,surface='claude',records=[],catalogs={'claude':catalog},backends_path=self.backends)
        self.assertEqual(r['route'],'DIRECT',r)
        self.assertEqual(r['provider_catalog_binding']['model_evidence_keys'],[])

    def test_agy_claude_explicit_vendor_and_cli_label(self):
        r=self.run_route('agy','DELEGATE',('--model','claude-opus-5-5-medium'))
        self.assertEqual(r['vendor'],'anthropic')
        self.assertEqual(r['surface'],'agy-cli')
        self.assertEqual(r['provider_catalog_binding']['cli_model'],'Claude Opus 5.5 (Medium)')

    def test_delegate_codex_role_critic_and_recompute_preserved(self):
        result=self.run_route('codex','DELEGATE')
        self.assertEqual(result['worker'],'codex-critic')
        result=self.run_route('codex','DELEGATE',('--role','recompute'))
        self.assertEqual(result['worker'],'codex-recompute')

    def test_final_model_availability_is_checked(self):
        r=self.run_route('codex','DIRECT',('--model-availability','gpt-6.1-sol=unavailable'))
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')
        self.assertIsNone(r['model'])

    def test_cli_alias_availability_overrides_canonical_binding(self):
        r=self.run_route('claude','DIRECT',('--model','sonnet','--model-availability','sonnet=unavailable'))
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')
        self.assertIsNone(r['model'])

    def test_explicit_weak_model_is_honest_quality_override(self):
        r=self.run_route('codex','DIRECT',('--model','gpt-5.4-mini','--effort','low',
            '--axes','verifiable=yes,failcost=high,volume=low,depth=deep'))
        self.assertEqual(r['model'],'gpt-5.4-mini')
        self.assertTrue(r['explicit_quality_override'])
        self.assertEqual(r['selection_stages'][1]['status'],'EXPLICIT_OVERRIDE_UNVERIFIED')

    def test_resolver_dependency_pin_cannot_drift(self):
        self.catalogs['workers']['codex-critic']['dynamic_loadout']['catalog_resolver_dependencies']['codex_inventory.py']='0'*64
        self.backends.write_text(json.dumps(self.catalogs))
        r=self.run_route('codex','DELEGATE')
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')
        self.assertIn('dependency pin',r['reason'])

    def test_writer_permission_is_not_created_for_grok(self):
        self.catalogs['workers']['grok-adversarial']['trusted_writer_profile']=None
        self.backends.write_text(json.dumps(self.catalogs))
        r=self.run_route('grok','DELEGATE',('--role','implementation_writer'))
        self.assertEqual(r['multiagent_execution_plan']['writer_fit'],'BLOCKED_CONTRACT_MISMATCH')
        self.assertEqual(r['execution_status'],'BLOCKED_CONTRACT_MISMATCH')
