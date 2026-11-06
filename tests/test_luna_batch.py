"""Offline execution/traceability tests; OpenAI is always replaced by a fake."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import threading
import time
import unittest
from unittest.mock import patch

import httpx2 as httpx
from openai import APITimeoutError, RateLimitError
from choice_trust import luna_batch as module
from choice_trust.luna_batch import LunaBatch, retry_delay
from choice_trust.luna_annotations import SETTINGS, SDK_SETTINGS, read
from choice_trust.luna_schema import annotation_schema
from choice_trust.luna_batch_schema import edited_schema, validate_batch_result
from choice_trust.test100_execution import lock, write_json


def fixture_job(index=1):
    candidates = [{'id': 'A', 'name': 'fixture'}]
    prov = {'P_A': {'concept_groups': ['CURRENT_PRICES'], 'source_fields': ['current.prices.A'], 'dependencies': []}}
    inp = {'explanation': 'A is $1.00.', 'candidates': candidates, 'provenance': prov,
           'observations': {'text': 'CURRENT_PRICES\n[P_A] A: $1.00'}, 'predicted_candidate': 'A', 'model_citations': ['P_A']}
    return {'job_id': f'fixture-{index}', 'source_response_id': f'fixture-{index}', 'job_signature': f'fixture-signature-{index}',
            'study_plan_id': 'fixture-study', 'case_id': f'fixture-{index}', 'query_id': f'fixture-{index}', 'household_id': 'fixture-household',
            'condition': 'with_history', 'family': 'ORIGINAL', 'edit_id': None, 'source_response_path': 'fixture', 'source_response_sha256': 'fixture-hash',
            'annotation_prompt_version': 'fixture', 'schema_version': 'fixture', 'configuration_version': 'fixture',
            'source_explanation': {'status': 'complete'}, 'annotation_input': inp,
            'annotation_guide': {'version': 'fixture', 'sha256': 'fixture'}, 'reuse': None,
            'request': deepcopy(SETTINGS), 'schema': annotation_schema(candidates, prov), 'patch': []}


def fixture_api():
    parsed = {'claims': [{'claim_id': 'C1', 'exact_quote': 'A is $1.00.', 'concept_groups': ['CURRENT_PRICES'],
        'relationship_type': 'current_price', 'claimed_role': 'descriptive_only', 'direction': {'favors': [], 'disfavors': []},
        'mapped_evidence_ids': ['P_A'], 'source_fields': ['current.prices.A'], 'factual_status': 'supported', 'annotation_note': 'A: $1.00.'}],
        'rules': [], 'coverage': {'all_substantive_claims_addressed': True, 'omitted_quotes': [], 'notes': 'Fixture.'}}
    # Use the actual established enum rather than a newly invented label.
    from choice_trust.explanation_annotation import RELATIONSHIPS
    parsed['claims'][0]['relationship_type'] = 'none' if 'none' in RELATIONSHIPS else 'other_or_unclear'
    return {'id': 'resp_fixture', 'status': 'completed', 'model': 'gpt-6-luna', 'error': None, 'incomplete_details': None,
            'reasoning': SETTINGS['reasoning'], 'max_output_tokens': SETTINGS['max_output_tokens'],
            'output': [{'type': 'message', 'status': 'completed', 'content': [{'type': 'output_text', 'text': json.dumps(parsed)}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30}}


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / 'annotations'
        self.out.mkdir()
        self.jobs = [fixture_job(i) for i in range(4)]
        self.batch = LunaBatch.__new__(LunaBatch)
        b = self.batch
        b.out = self.out
        b.jobs = self.jobs
        b.stop = threading.Event()
        b.rate_lock = threading.Lock()
        b.not_before = 0
        b.progress_lock = threading.Lock()
        b.manifest = {'inventory': {'total': 4}, 'annotation_manifest_id': 'fixture', 'study_plan_id': 'fixture-study', 'counts_by_family': {'ORIGINAL': 4}}
        for j in self.jobs:
            b.state(j, 'pending')
        self.addCleanup(patch.stopall)
        patch('choice_trust.luna_batch.STUDY', self.root / 'study').start()

    def fake_client(self, callback):
        class Client:
            def __init__(self, **kwargs):
                if kwargs['max_retries'] != 0:
                    raise AssertionError('SDK retry multiplication')
                self.responses = self
                self.with_raw_response = self
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def create(self, **kwargs): return callback(kwargs)
        return patch('openai.OpenAI', Client)

    def raw(self, api=None):
        class Raw:
            content = json.dumps(api or fixture_api()).encode()
            status_code = 200
            headers = {'x-request-id': 'req_fixture'}
        return Raw()

    def test_four_workers_live_check_and_no_duplicate_resume(self):
        active = maximum = calls = 0
        guard = threading.Lock()
        def call(kwargs):
            nonlocal active, maximum, calls
            self.assertEqual({k: kwargs[k] for k in SETTINGS}, SETTINGS)
            with guard:
                active += 1; maximum = max(maximum, active); calls += 1
            time.sleep(.05)
            with guard: active -= 1
            return self.raw()
        with self.fake_client(call), patch.object(self.batch, 'key', return_value='fixture-private-key'):
            self.batch.run()
            self.batch.run()
        self.assertEqual(calls, 4)
        self.assertEqual(maximum, 4)
        self.assertEqual(read(self.out / 'live_check.json')['status'], 'passed')
        self.assertEqual(self.batch.summary()['full_explanation_success'], 4)
        self.assertEqual(sum(len(self.batch.attempt_paths(j)) for j in self.jobs), 4)

    def test_timeout_is_uncertain_and_never_automatically_repeated(self):
        calls = []
        def call(kwargs):
            calls.append(kwargs)
            raise APITimeoutError(request=httpx.Request('POST', 'https://api.openai.com/v1/responses'))
        with self.fake_client(call):
            self.batch.process(self.jobs[0], 'fixture-private-key')
            self.batch.process(self.jobs[0], 'fixture-private-key')
        self.assertEqual(len(calls), 1)
        self.assertEqual(read(self.out / 'states/fixture-0.json')['status'], 'execution_uncertain')

    def test_rate_limit_is_bounded_and_exact_error_retained(self):
        calls = []
        def call(kwargs):
            calls.append(kwargs)
            response = httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'),
                                     headers={'retry-after': '0'}, json={'error': {'code': 'rate_limit_exceeded'}})
            raise RateLimitError('temporary', response=response, body={'code': 'rate_limit_exceeded'})
        with self.fake_client(call), patch.object(self.batch, 'delay'):
            self.batch.process(self.jobs[0], 'fixture-private-key')
        self.assertEqual(len(calls), 4)
        self.assertEqual(read(self.out / 'states/fixture-0.json')['status'], 'failed')
        self.assertIn('rate_limit_exceeded', read(self.batch.attempt_paths(self.jobs[0])[0])['raw_error_body'])

    def test_billing_stops_scheduling_without_retry(self):
        calls = []
        def call(kwargs):
            calls.append(kwargs)
            response = httpx.Response(429, request=httpx.Request('POST', 'https://api.openai.com/v1/responses'), json={'error': {'code': 'insufficient_quota'}})
            raise RateLimitError('billing', response=response, body={'code': 'insufficient_quota'})
        with self.fake_client(call):
            self.batch.process(self.jobs[0], 'fixture-private-key')
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.batch.stop.is_set())

    def test_raw_saved_recovery_makes_no_call(self):
        j = self.jobs[0]
        write_json(self.out / 'attempts' / j['job_id'] / '01.json', {'status': 'started'})
        module.atomic_bytes(self.out / 'raw_api' / j['job_id'] / '01.json', self.raw().content)
        with self.fake_client(lambda kwargs: self.fail('Recovery sent a duplicate request')):
            self.batch.process(j, 'fixture-private-key')
        self.assertTrue(self.batch.get_record(j)['validation']['schema_and_traceability_ok'])

    def test_bad_quote_preserved_not_exported_or_retried(self):
        api = fixture_api(); parsed = json.loads(api['output'][0]['content'][0]['text'])
        parsed['claims'][0]['exact_quote'] = 'not in explanation'
        api['output'][0]['content'][0]['text'] = json.dumps(parsed)
        calls = []
        def call(kwargs): calls.append(kwargs); return self.raw(api)
        with self.fake_client(call):
            self.batch.process(self.jobs[0], 'fixture-private-key')
            self.batch.process(self.jobs[0], 'fixture-private-key')
        record = self.batch.get_record(self.jobs[0])
        self.assertEqual(len(calls), 1)
        self.assertFalse(record['validation']['schema_and_traceability_ok'])
        self.assertEqual(record['parsed_annotation']['claims'][0]['exact_quote'], 'not in explanation')
        self.assertFalse(list((self.root / 'study/annotations').rglob('*.json')))

    def test_duplicate_runner_lock(self):
        with lock(self.out / '.runner.lock'):
            with self.assertRaises(RuntimeError):
                with lock(self.out / '.runner.lock'): pass

    def test_retry_after_minimum_and_defer(self):
        self.assertGreaterEqual(retry_delay({'retry-after': '1800'}, 1), 1800)
        self.assertGreaterEqual(retry_delay({'retry-after-ms': '12500'}, 1), 12.5)

    def test_stale_extension_requires_old_evidence_and_patch(self):
        j = deepcopy(self.jobs[0]); j['family'] = 'CURRENT_PRICE'
        j['patch'] = [{'field': 'current.prices.A', 'before': 1, 'after': 2}]
        j['comparison_context'] = {'observation_provenance': j['annotation_input']['provenance']}
        j['schema'] = edited_schema(j['annotation_input']['candidates'], j['annotation_input']['provenance'], j['annotation_input']['provenance'], j['patch'])
        api = fixture_api(); parsed = json.loads(api['output'][0]['content'][0]['text'])
        parsed['claims'][0]['comparison_assessment'] = {'temporal_scope': 'current_edited', 'stale_status': 'stale',
            'original_evidence_ids': ['P_A'], 'original_source_fields': ['current.prices.A'], 'changed_patch_fields': ['current.prices.A'], 'reason': 'Old $1.00; current $2.00.'}
        raw = json.dumps(parsed)
        _, diagnostics = validate_batch_result(raw, j, api)
        self.assertTrue(diagnostics['schema_and_traceability_ok'], diagnostics)
        parsed['claims'][0]['comparison_assessment']['changed_patch_fields'] = []
        _, diagnostics = validate_batch_result(json.dumps(parsed), j, api)
        self.assertFalse(diagnostics['schema_and_traceability_ok'])


if __name__ == '__main__':
    unittest.main()
