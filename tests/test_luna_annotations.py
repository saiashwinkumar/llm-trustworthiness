"""Offline protocol tests. No SDK client is constructed and no outputs are fabricated.

Negative JSON fixtures and an archived foreign claim are used only in memory to
exercise rejection, never saved as annotations for the selected test cases.
"""
import inspect,json,random,shutil,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from jsonschema import Draft202012Validator
from openai.resources.responses.responses import Responses
from choice_trust.luna_annotations import LunaInspection,DEFAULT_OUT,STUDY,MODEL,SETTINGS,redact_credentials,output_text_parts
from choice_trust.luna_schema import validate_result


def copy_prepared_plan(destination):
    """Isolate credential tests from real executions already saved in DEFAULT_OUT."""
    destination.mkdir()
    for name in ('manifest.json','selection.json'):
        shutil.copy2(DEFAULT_OUT/name,destination/name)
    shutil.copytree(DEFAULT_OUT/'jobs',destination/'jobs')
    (destination/'states').mkdir()
    for path in (destination/'jobs').glob('*.json'):
        job=json.loads(path.read_text())
        state={'job_id':job['job_id'],'source_response_id':job['source_response_id'],'status':'pending','api_attempted':False}
        (destination/'states'/path.name).write_text(json.dumps(state))


class LunaOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inspection=LunaInspection(DEFAULT_OUT)
        cls.job=cls.inspection.jobs[0]
    def test_exact_ten_seeded_original_sources(self):
        manifest=json.loads((STUDY/'manifest.json').read_text());pool=sorted([e['case_id'] for e in manifest['entries'] if e['family']=='ORIGINAL'],key=lambda c:int(c.removeprefix('row-')))
        self.assertEqual([j['case_id'] for j in self.inspection.jobs],random.Random(42).sample(pool,10))
        self.assertEqual(len({j['case_id'] for j in self.inspection.jobs}),10)
        self.assertTrue(all(j['source_response_id'].endswith('__with_history__ORIGINAL') for j in self.inspection.jobs))
    def test_allowlisted_input_no_hidden_target_outcomes_or_prior_labels(self):
        expected={'case_id','source_response_id','candidates','exact_factual_input','predictor_factual_instructions','original_prediction','exact_generated_explanation','predictor_original_citations','observation_provenance'}
        for j in self.inspection.jobs:
            data=json.loads(j['request']['input'][1]['content'].split('\n',1)[1])
            self.assertEqual(set(data),expected);self.assertEqual(data['exact_generated_explanation'],j['annotation_input']['explanation'])
            self.assertEqual(data['exact_factual_input'],j['annotation_input']['observations']['text'])
            self.assertNotIn('target',j['source_values']);self.assertNotIn('counterfactual_outcomes',data)
    def test_official_sdk_arguments_and_strict_schema(self):
        params=set(inspect.signature(Responses.create).parameters)
        for j in self.inspection.jobs:
            self.assertTrue(set(j['request'])<=params);self.assertEqual(j['request']['model'],MODEL)
            self.assertEqual(j['request']['reasoning'],{'effort':'high'});self.assertEqual(j['request']['max_output_tokens'],32768)
            self.assertFalse(set(j['request'])&{'generation_config','top_k','num_beams','max_new_tokens','temperature'})
            Draft202012Validator.check_schema(j['schema'])
            def check(v):
                if isinstance(v,dict):
                    if v.get('type')=='object':self.assertFalse(v['additionalProperties']);self.assertEqual(set(v['required']),set(v['properties']))
                    for value in v.values():check(value)
                elif isinstance(v,list):
                    for value in v:check(value)
            check(j['schema'])
    def test_missing_key_and_remaining_guard_never_create_client(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'inspection';copy_prepared_plan(out)
            i=LunaInspection(out)
            with patch('choice_trust.luna_annotations.load_openai_key',return_value=None),patch('openai.OpenAI',side_effect=AssertionError('No API client allowed')) as client:
                result=i.annotate_first();self.assertEqual(result['status'],'credentials_required');client.assert_not_called()
                self.assertEqual(i.annotate_remaining()['status'],'first_example_required')
            self.assertFalse((out/'attempts').exists());self.assertFalse((out/'records').exists())
            self.assertTrue(all(r['status']=='pending' for r in i.status()))
    def test_only_frozen_jobs_can_be_called(self):
        with patch('openai.OpenAI',side_effect=AssertionError('No API client allowed')) as client:
            with self.assertRaisesRegex(ValueError,'outside'):self.inspection.annotate_one('row-2002__with_history__CURRENT_PRICE')
            client.assert_not_called()
    def test_bad_json_and_incomplete_api_remain_invalid_without_repair(self):
        api={'model':MODEL,'status':'incomplete','incomplete_details':{'reason':'max_output_tokens'},'error':None,'output':[]}
        for raw in ('{','[]'):
            original=raw;parsed,d=validate_result(raw,self.job,api)
            self.assertFalse(d['schema_and_traceability_ok']);self.assertFalse(d['api_completed']);self.assertTrue(d['generation_truncated']);self.assertEqual(raw,original)
    def test_foreign_annotation_quote_is_rejected_and_not_repaired(self):
        path=Path('choice_study/development_counterfactual_v1/annotations/row-1289__no_history__ORIGINAL.json')
        foreign=json.loads(path.read_text())['result']['parsed_annotations']['claims']
        payload={'claims':foreign,'rules':[],'coverage':{'all_substantive_claims_addressed':True,'omitted_quotes':[],'notes':'NEGATIVE TEST INPUT, not a new annotation'}}
        raw=json.dumps(payload);api={'model':MODEL,'status':'completed','output':[],'incomplete_details':None,'error':None}
        parsed,d=validate_result(raw,self.job,api)
        self.assertFalse(d['schema_and_traceability_ok']);self.assertTrue(any('Quote' in s or 'quote' in s for s in d['issues']))
        self.assertEqual(parsed['claims'][0]['exact_quote'],foreign[0]['exact_quote'])
    def test_secret_redaction_and_unmodified_text_parts(self):
        safe,redacted=redact_credentials('API error sk-TESTSECRET123 token','sk-TESTSECRET123')
        self.assertTrue(redacted);self.assertNotIn('sk-TESTSECRET123',safe)
        api={'output':[{'type':'message','content':[{'type':'output_text','text':' \n{'},{'type':'output_text','text':' }\n'}]}]}
        self.assertEqual(output_text_parts(api),[' \n{',' }\n'])
    def test_plan_tampering_is_not_silently_reused(self):
        with tempfile.TemporaryDirectory() as t:
            out=Path(t)/'inspection';copy_prepared_plan(out)
            path=next((out/'jobs').glob('*.json'));job=json.loads(path.read_text());job['request']['model']='some-other-model';path.write_text(json.dumps(job))
            with self.assertRaisesRegex(ValueError,'changed'):LunaInspection(out)
    def test_preview_configuration_and_summary_have_no_api_method(self):
        with patch('openai.OpenAI',side_effect=AssertionError('No API client allowed')) as client:
            self.assertEqual(self.inspection.preview()['model'],MODEL)
            self.assertEqual(len(self.inspection.status()),10);client.assert_not_called()

if __name__=='__main__':unittest.main()
