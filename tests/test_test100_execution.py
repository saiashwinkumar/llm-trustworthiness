"""Synthetic transport fixtures only; never model results or inference."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from choice_trust.test100_execution import Study,write_json,signature,original_matches
from choice_trust.joint_observation import parse_joint_response,JOINT_GENERATION_SETTINGS

class FakeClient:
    def __init__(self,out,manifest,lose_first=False):
        self.manifest=manifest;self.calls=[];self.journal={};self.lose_first=lose_first
        model={'model_id':'fixture','revision':'fixed-revision','tokenizer_revision':'fixed-revision','tokenizer':'fixture/fixed-revision','device':'cpu','dtype':'torch.float32','torch':'fixture','transformers':'fixture'}
        effective={**JOINT_GENERATION_SETTINGS,'eos_token_id':[1],'pad_token_id':1,'use_cache':True,'max_input_tokens':4096}
        self.runtime={'plan_id':manifest['plan_id'],'model':model,'effective_settings':effective}
        self.prompts={e['call_id']:{'rendered_prompt':'SYNTHETIC TRANSPORT FIXTURE\n'+e['messages'][0]['content']} for e in manifest['entries']}
        from choice_trust.development_pilot import digest
        self.runtime['rendered_prompts_digest']=digest(self.prompts)
        write_json(Path(out)/'rendered_prompts.json',self.prompts)
    def make(self,e):
        raw=json.dumps({'explanation':'Synthetic transport fixture, not an LLM response.','evidence_ids':['P_A'],'prediction':'A'})
        parsed,d=parse_joint_response(raw,e['observations']['candidates'],e['observations'],truncated=False)
        r={'prompt_version':'joint-compact-factual-observation-v2','observation_version':e['observations']['version'],
           'messages':e['messages'],'rendered_prompt':self.prompts[e['call_id']]['rendered_prompt'],'raw_response':raw,
           'parsed_result':parsed,'diagnostics':d,'generation_metadata':{'model':self.runtime['model'],'effective_settings':self.runtime['effective_settings']}}
        return {'response':r,'input_signature':signature(self.manifest,e,self.runtime,self.prompts[e['call_id']]['rendered_prompt'])}
    def request(self,route,payload=None):
        if route=='/test100/runtime':return self.runtime
        if route.startswith('/test100/attempt/'):return self.journal.get(route.rsplit('/',1)[1],{'status':'not_started'})
        cid=payload['call_id'];self.calls.append(cid)
        e=next(e for e in self.manifest['entries'] if e['call_id']==cid);result=self.make(e)
        self.journal[cid]={'status':'completed','record':result}
        if self.lose_first and len(self.calls)==1:raise TimeoutError('synthetic lost HTTP response')
        return result

class ExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m=json.loads(Path('choice_study/test_with_history_100_v1/manifest.json').read_text())
        case=m['selected_cases'][0]['case_id']
        cls.m={**m,'entries':[e for e in m['entries'] if e['case_id']==case and e['family'] in ('ORIGINAL','CURRENT_PRICE','ANSWER_MAPPING_CONTROL')]}
    def create(self,out,lose_first=False):
        client=FakeClient(out,copy.deepcopy(self.m),lose_first)
        with patch('choice_trust.test100_execution.verify_manifest',return_value=client.manifest):study=Study(out)
        return study,client
    def test_repeat_and_lost_http_do_not_repeat_calls(self):
        with tempfile.TemporaryDirectory() as t:
            study,c=self.create(t,True);self.assertTrue(study.run(c,search_root=t)['complete']);self.assertEqual(len(c.calls),3)
            before={p.name:p.read_bytes() for p in (Path(t)/'responses').glob('*')}
            self.assertTrue(study.run(c,search_root=t)['complete']);self.assertEqual(len(c.calls),3)
            self.assertEqual(before,{p.name:p.read_bytes() for p in (Path(t)/'responses').glob('*')})
    def test_missing_completed_file_recovers_or_stays_uncertain(self):
        with tempfile.TemporaryDirectory() as t:
            s,c=self.create(t);s.run(c,search_root=t);cid=c.calls[0];p=Path(t)/'responses'/f'{cid}.json';p.unlink()
            self.assertTrue(s.run(c,search_root=t)['complete']);self.assertEqual(len(c.calls),3)
            p.unlink();c.journal.pop(cid)
            self.assertFalse(s.run(c,search_root=t)['complete']);self.assertEqual(len(c.calls),3)
            self.assertEqual(json.loads((Path(t)/'items'/f'{cid}.json').read_text())['status'],'uncertain')
    def test_tampered_body_is_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as t:
            s,c=self.create(t);s.run(c,search_root=t);p=Path(t)/'responses'/f'{c.calls[0]}.json';r=json.loads(p.read_text());r['decoded_product_id']='tampered';write_json(p,r)
            before=p.read_bytes()
            with self.assertRaisesRegex(ValueError,'overwritten'):s.run(c,search_root=t)
            self.assertEqual(p.read_bytes(),before);self.assertEqual(len(c.calls),3)
    def test_reuse_requires_source_and_tokenizer_and_settings(self):
        with tempfile.TemporaryDirectory() as t:
            s,c=self.create(t);e=self.m['entries'][0];r=c.make(e)['response'];outer={'_matched_observations':e['observations']}
            rendered=c.prompts[e['call_id']]['rendered_prompt']
            self.assertTrue(original_matches(e,outer,r,c.runtime,rendered))
            altered=copy.deepcopy(outer);altered['_matched_observations']['audit']['source_values']['current.prices.A']=999
            self.assertFalse(original_matches(e,altered,r,c.runtime,rendered))
            bad=copy.deepcopy(r);bad['generation_metadata']['model']['tokenizer_revision']='other';bad['generation_metadata']['model']['tokenizer']='unknown'
            self.assertFalse(original_matches(e,outer,bad,c.runtime,rendered))

if __name__=='__main__':unittest.main()
