import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

SKILL=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SKILL))
import provider_catalog as pc
import router
FIX=Path(__file__).parent/'fixtures'
NOW=datetime.now(timezone.utc)

def fixture(name):
    data=json.loads((FIX/name).read_text())
    if name=='claude-cc-catalogs.json':
        for c in data:
            c['fetchedAt']=int(NOW.timestamp()*1000)-1000
            c['staleAt']=int((NOW+timedelta(hours=1)).timestamp()*1000)
    return data

def codex_catalog(models=None):
    return pc._finish('codex',[pc._row('codex',m,['low','medium','high']) for m in
        (models or ['gpt-6-luna','gpt-6-sol','gpt-6.1-sol','gpt-6-astra','gpt-5.4-mini'])],
        source='fixture_model_list',fetched_at=NOW.isoformat(),expires_at=(NOW+timedelta(hours=1)).isoformat(),
        account_scope={'kind':'explicit','home_hash':'fixture'},now=NOW)


class CatalogTests(unittest.TestCase):
    def test_all_agy_ids_current_versions_and_embedded_effort(self):
        data=fixture('agy-models.json')
        c=pc.parse_cli_models('agy','\n'.join(data['sanitized_model_lines']),now=NOW)
        self.assertEqual(len(c['models']),18)
        r=pc.resolve('agy','latest:gemini-flash','medium',catalog=c,now=NOW)
        self.assertEqual(r['cli_model'],'Gemini 3.8 Flash (Medium)')
        self.assertEqual(r['effort_binding']['mode'],'embedded')
        self.assertIsNone(r['cli_effort_flag'])
        self.assertEqual(len(r['alternatives']),17)

    def test_agy_nonlatest_kept_and_effort_mismatch_refused(self):
        c=pc.parse_cli_models('agy','\n'.join(fixture('agy-models.json')['sanitized_model_lines']),now=NOW)
        self.assertEqual(pc.resolve('agy','gemini-3.7-flash-low','low',catalog=c,now=NOW)['effort'],'low')
        with self.assertRaises(pc.CatalogError):
            pc.resolve('agy','gemini-3.8-flash-low','high',catalog=c,now=NOW)

    def test_agy_label_mismatch_is_visible_and_ineligible(self):
        c=pc.parse_cli_models('agy','gemini-4-flash-low\tGemini 4 Flash (High)',now=NOW)
        self.assertEqual(len(c['models']),1)
        self.assertFalse(c['models'][0]['eligible'])

    def test_grok_four_models_and_unknown_default_only(self):
        c=pc.parse_cli_models('grok','\n'.join(fixture('grok-models.json')['sanitized_model_lines']),now=NOW)
        self.assertEqual(len(c['models']),4)
        self.assertEqual(pc.resolve('grok','latest','high',catalog=c,now=NOW)['cli_model'],'grok-4.7')
        self.assertEqual(pc.resolve('grok','grok-4.7-build-fast',catalog=c,now=NOW)['effort'],'config')
        with self.assertRaises(pc.CatalogError):
            pc.resolve('grok','grok-4.7-build-fast','high',catalog=c,now=NOW)
        with self.assertRaises(pc.CatalogError):
            pc.resolve('grok','grok-4.5','xhigh',catalog=c,now=NOW)

    def test_future_grok_effort_not_extrapolated(self):
        c=pc.parse_cli_models('grok',' - grok-9.0',now=NOW)
        self.assertEqual(c['models'][0]['supported_efforts'],[])
        with self.assertRaises(pc.CatalogError):
            pc.resolve('grok','grok-9.0','high',catalog=c,now=NOW)

    def test_codex_full_inventory_and_nonlatest(self):
        c=codex_catalog()
        self.assertEqual(len(c['models']),5)
        self.assertEqual(pc.resolve('codex','latest','medium',catalog=c,now=NOW)['cli_model'],'gpt-6.1-sol')
        self.assertEqual(pc.resolve('codex','gpt-5.4-mini','low',catalog=c,now=NOW)['cli_model'],'gpt-5.4-mini')

    def test_future_codex_version_not_static_limited(self):
        c=codex_catalog(['gpt-6-sol','gpt-7.1-sol'])
        self.assertEqual(pc.resolve('codex','latest','high',catalog=c,now=NOW)['cli_model'],'gpt-7.1-sol')

    def test_no_latest_effort_downgrade(self):
        c=codex_catalog()
        c['models'][2]['supported_efforts']=['high']
        with self.assertRaises(pc.CatalogError):
            pc.resolve('codex','latest','medium',catalog=c,now=NOW)

    def test_stale_catalog_refused_even_if_fresh_flag_forged(self):
        c=codex_catalog();c['freshness']['expires_at']=(NOW-timedelta(seconds=1)).isoformat()
        with self.assertRaises(pc.CatalogError):
            pc.resolve('codex','latest','medium',catalog=c,now=NOW)

    def test_unsafe_and_unobserved_model_ids_refused(self):
        c=codex_catalog()
        for model in ['--config','gpt-999-sol','gpt-6-sol;touch /tmp/evil']:
            with self.subTest(model=model),self.assertRaises(pc.CatalogError):
                pc.resolve('codex',model,'low',catalog=c,now=NOW)

    def test_claude_live_alias_and_canonical_mapping(self):
        c=pc.parse_claude_live(fixture('claude-control-init-metadata.json')['models'],
            caches=fixture('claude-cc-catalogs.json'),now=NOW)
        self.assertEqual(len(c['models']),12)
        r=pc.resolve('claude','latest:opus','medium',catalog=c,now=NOW)
        self.assertEqual(r['canonical_model_id'],'claude-opus-5-5')
        self.assertEqual(r['cli_model'],'opus')
        h=pc.resolve('claude','haiku',catalog=c,now=NOW)
        self.assertEqual(h['effort'],'none')
        self.assertIsNone(h['cli_effort_flag'])
        self.assertEqual(c['user_messages_sent'],0)

    def test_live_alias_mapping_requires_single_fresh_cache(self):
        models=fixture('claude-control-init-metadata.json')['models']
        caches=fixture('claude-cc-catalogs.json')
        stale=copy.deepcopy(caches);stale[0]['staleAt']=int((NOW-timedelta(seconds=1)).timestamp()*1000)
        for cc in ([],stale,caches+caches):
            c=pc.parse_claude_live(models,caches=cc,now=NOW)
            r=pc.resolve('claude','opus','medium',catalog=c,now=NOW)
            self.assertEqual(r['canonical_model_id'],'opus')
            self.assertEqual(r['model_evidence_keys'],[])
            self.assertFalse(r['account_identity_verified'])
        r=pc.resolve('claude','opus','medium',catalog=pc.parse_claude_live(models,caches=caches,now=NOW),now=NOW)
        self.assertEqual(r['model_evidence_keys'],['claude-opus-5-5'])
        self.assertEqual(r['identity_source'],'fresh_cc_name_mapping_unverified')
        self.assertFalse(r['account_identity_verified'])

    def test_claude_reads_native_cache_after_live_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);target=directory/'test-cc.json'
            target.write_text('{malformed')
            def probe(*a,**kw):
                target.write_text(json.dumps(fixture('claude-cc-catalogs.json')[0]))
                return fixture('claude-control-init-metadata.json')['models']
            with patch.object(pc,'probe_claude_models',side_effect=probe):
                c=pc.load_catalog('claude',executable='/bin/true',claude_catalog_dir=tmp,now=NOW)
            r=pc.resolve('claude','opus','medium',catalog=c,now=NOW)
            self.assertEqual(r['canonical_model_id'],'claude-opus-5-5')

    def test_patch_versions_are_ordered_numerically(self):
        c=codex_catalog(['gpt-6.1.1-sol','gpt-6.1.2-sol'])
        self.assertEqual(pc.resolve('codex','latest','medium',catalog=c,now=NOW)['canonical_model_id'],'gpt-6.1.2-sol')

    def test_fable_stays_visible_shadow_only(self):
        c=pc.parse_claude_live(fixture('claude-control-init-metadata.json')['models'],now=NOW)
        f=[r for r in c['models'] if 'fable' in (r['cli_model'] or '')]
        self.assertEqual(len(f),2)
        self.assertTrue(all(not r['eligible'] for r in f))
        with self.assertRaises(pc.CatalogError):
            pc.resolve('claude','fable','high',catalog=c,now=NOW)

    def test_cc_native_expiry_and_ambiguity_never_merged(self):
        caches=fixture('claude-cc-catalogs.json')
        t=datetime.fromtimestamp(caches[0]['fetchedAt']/1000,timezone.utc)+timedelta(seconds=1)
        c=pc.parse_claude_caches(caches,now=t,cli_version='2.1.287')
        self.assertEqual(len(c['models']),11)
        self.assertEqual(c['status'],'CACHE_IDENTITY_UNVERIFIED')
        with self.assertRaises(pc.CatalogError):pc.resolve('claude','latest:opus','medium',catalog=c,now=t)
        amb=pc.parse_claude_caches(caches+caches,now=t,cli_version='2.1.287')
        self.assertEqual(amb['status'],'AMBIGUOUS_ACCOUNT')
        self.assertEqual(len(amb['models']),22)
        with self.assertRaises(pc.CatalogError):
            pc.resolve('claude','latest','medium',catalog=amb,now=t)
        stale=pc.parse_claude_caches(caches,now=t+timedelta(days=1),cli_version='2.1.287')
        self.assertEqual(stale['status'],'STALE')
        self.assertTrue(stale['models'])

    def test_ccd_excluded_and_minimum_cli_enforced(self):
        caches=fixture('claude-cc-catalogs.json')
        d=copy.deepcopy(caches[0]);d['catalog']['surface']='ccd'
        t=datetime.fromtimestamp(caches[0]['fetchedAt']/1000,timezone.utc)+timedelta(seconds=1)
        c=pc.parse_claude_caches([d,*caches],now=t,cli_version='2.1.263')
        latest=next(r for r in c['models'] if r['canonical_model_id']=='claude-opus-5-5')
        self.assertFalse(latest['eligible'])
        with self.assertRaises(pc.CatalogError):pc.parse_claude_caches([d],now=t)

    def test_relative_executable_refused_without_launch(self):
        with patch('subprocess.Popen') as launch:
            c=pc.load_catalog('codex',executable='codex')
        self.assertEqual(c['status'],'UNAVAILABLE');launch.assert_not_called()


class RouterCatalogTests(unittest.TestCase):
    def setUp(self):
        self.axes={'verifiable':'yes','failcost':'mid','volume':'low','depth':'mid'}
        self.ext={'handoff_cost':'high','spec_readiness':'executable','decomposability':'single',
                  'context_dependency':'high','verifier_available':'yes'}

    def test_direct_latest_and_explicit_models_use_same_catalog(self):
        c=codex_catalog()
        r=router.recommend('bounded change',self.axes,self.ext,surface='codex',records=[],
                           catalogs={'codex':c},requested_model='latest')
        self.assertEqual(r['model'],'gpt-6.1-sol')
        self.assertIn('model_reasoning_effort=medium',r['execution_contract']['fallback_argv'])
        r=router.recommend('bounded change',self.axes,self.ext,surface='codex',records=[],
                           catalogs={'codex':c},requested_model='gpt-5.4-mini',requested_effort='low')
        self.assertEqual(r['model'],'gpt-5.4-mini')

    def test_claude_no_effort_router_omits_flag(self):
        c=pc.parse_claude_live(fixture('claude-control-init-metadata.json')['models'],
            caches=fixture('claude-cc-catalogs.json'),now=NOW)
        r=router.recommend('simple text',self.axes,self.ext,surface='claude',records=[],
                           catalogs={'claude':c},requested_model='haiku')
        self.assertEqual(r['effort'],'none')
        self.assertNotIn('--effort',r['execution_contract']['fallback_argv'])
        self.assertNotIn('exec',r['execution_contract']['fallback_argv'])

    def test_direct_other_providers_supported(self):
        for provider in ['grok','agy']:
            c=pc.parse_cli_models(provider,'\n'.join(fixture(provider+'-models.json')['sanitized_model_lines']),now=NOW)
            r=router.recommend('compatibility check',self.axes,self.ext,surface=provider,records=[],catalogs={provider:c})
            self.assertEqual(r['route'],'DIRECT',r)
            self.assertEqual(r['provider_catalog_binding']['provider'],provider)
            self.assertNotIn('--config',r['execution_contract']['fallback_argv'])

    def test_future_grok_automatic_choice_uses_default_effort(self):
        c=pc.parse_cli_models('grok',' - grok-4.7\n - grok-4.8',now=NOW)
        r=router.recommend('bounded change',self.axes,self.ext,surface='grok',records=[],catalogs={'grok':c})
        self.assertEqual(r['model'],'grok-4.8')
        self.assertEqual(r['effort'],'config')
        self.assertIsNone(r['provider_catalog_binding']['cli_effort_flag'])
        r=router.recommend('bounded change',self.axes,self.ext,surface='grok',records=[],catalogs={'grok':c},requested_effort='medium')
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')

    def test_unavailable_model_fails_without_registry_mutation(self):
        c=codex_catalog()
        r=router.recommend('bounded change',self.axes,self.ext,surface='codex',records=[],
                           catalogs={'codex':c},requested_model='gpt-99-sol')
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')
        self.assertIsNone(r['model'])

    def test_experimental_general_model_option_cannot_bypass_shadow(self):
        c=pc.parse_claude_live(fixture('claude-control-init-metadata.json')['models'],now=NOW)
        r=router.recommend('bounded change',self.axes,self.ext,surface='claude',records=[],
                           catalogs={'claude':c},requested_model='fable')
        self.assertEqual(r['route'],'BLOCKED_PROVIDER_CATALOG')
