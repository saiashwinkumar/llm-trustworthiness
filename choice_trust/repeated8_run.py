"""Single Qwen collection loop with four independent durable Luna annotation workers."""
from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread
from time import sleep, time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import os

from .development_pilot import digest
from .explanation_annotation import load_guide
from .joint_observation import parse_joint_response
from .luna_annotations import SETTINGS as LUNA_SETTINGS, SDK_SETTINGS, request_for, source_input, output_text_parts
from .luna_batch import edited_input, edited_request, provenance, atomic_bytes, retry_delay, MAX_ATTEMPTS
from .luna_batch_schema import validate_batch_result
from .repeated8 import OUT, ROOT, SOURCE, verify, read, job_id, file_hash, signature
from .test100_execution import lock, write_json, now


def key():
    value = os.environ.get('OPENAI_API_KEY')
    if value:
        return value
    from dotenv import dotenv_values
    for path in (ROOT / '.env.luna', ROOT / '.env', Path('/home/ubuntu/customer-choice-trust/.env')):
        if path.exists():
            value = dotenv_values(path).get('OPENAI_API_KEY')
            if value:
                return value
    return None


class Client:
    def __init__(self):
        self.base = os.environ.get('MODEL_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
        self.secret = os.environ.get('MODEL_API_KEY')
        if not self.secret:
            from dotenv import dotenv_values
            private = ROOT / '.env.repeated8'
            if private.exists():
                self.secret = dotenv_values(private).get('MODEL_API_KEY')
        if not self.secret:
            raise RuntimeError('MODEL_API_KEY unavailable in private EC2 environment')

    def get(self, route, timeout=120):
        with urlopen(Request(self.base + route, headers={'Authorization': 'Bearer ' + self.secret}), timeout=timeout) as r:
            return json.load(r)

    def post(self, route, data, timeout=1200):
        req = Request(self.base + route, data=json.dumps(data).encode(),
                      headers={'Authorization': 'Bearer ' + self.secret, 'Content-Type': 'application/json'})
        with urlopen(req, timeout=timeout) as r:
            return json.load(r)


class Run:
    def __init__(self, out=OUT):
        self.out = Path(out).resolve()
        self.manifest = verify(self.out)
        self.entries = {e['call_id']: e for e in self.manifest['entries']}
        self.by_job = {job_id(e['case_id'], e['call_id'], r): e for e in self.entries.values() if e['applicable'] for r in range(50)}
        self.guide = load_guide(ROOT / 'docs/EXPLANATION_ANNOTATION_GUIDE.md')
        self.supplement = (ROOT / 'docs/LUNA_ANNOTATION_PROMPT_V1.md').read_text()
        self.extension = (ROOT / 'docs/LUNA_EDITED_ANNOTATION_V1.md').read_text()
        self.stop = Event()
        self.queue = Queue(maxsize=8)
        self.progress_lock = Lock()

    def response_path(self, jid): return self.out / 'responses' / f'{jid}.json'
    def annotation_path(self, jid): return self.out / 'annotations' / f'{jid}.json'
    def state(self, stage, jid, status, **fields):
        write_json(self.out / 'states' / stage / f'{jid}.json', {'job_id': jid, 'status': status, 'utc': now(), **fields})

    def check_response(self, jid, record, runtime):
        entry = self.by_job[jid]
        sig = signature(self.manifest, entry, runtime, jid)
        if record['job_id'] != jid or record['call_id'] != entry['call_id'] or record['input_signature'] != sig:
            raise ValueError('Saved Qwen response belongs to another job/input/runtime')
        response = record['response']
        prompts = read(self.out / 'rendered_prompts.json')
        if response['messages'] != entry['messages'] or response['rendered_prompt'] != prompts[entry['call_id']]['rendered_prompt']:
            raise ValueError('Saved Qwen prompt differs')
        if response['generation_metadata']['model'] != runtime['model'] or response['generation_metadata']['effective_settings'] != runtime['effective_settings']:
            raise ValueError('Saved Qwen model/sampling configuration differs')
        actual = response['generation_metadata']['actual_generate_kwargs']
        if any(actual.get(k) != v for k, v in self.manifest['sampling_settings'].items() if k in actual):
            raise ValueError('Actual Qwen generate kwargs differ from frozen sampling settings')
        if actual.get('do_sample') is not True or actual.get('temperature') != 0.7:
            raise ValueError('Qwen generation did not apply stochastic sampling')
        parsed, diagnostics = parse_joint_response(response['raw_response'], entry['observations']['candidates'],
                                                   entry['observations'], truncated=response['diagnostics']['generation_truncated'])
        if parsed != response['parsed_result'] or diagnostics != response['diagnostics']:
            raise ValueError('Saved Qwen raw text/parser mismatch')
        expected_seed = int(sha256((self.manifest['experiment_id'] + '|' + jid).encode()).hexdigest()[:16], 16)
        if response['generation_metadata']['seed'] != expected_seed:
            raise ValueError('Qwen seed differs from frozen job identity')
        if response['generation_metadata'].get('seed_application') != 'torch.random.fork_rng(devices=[]) + torch.manual_seed(seed) under server inference lock':
            raise ValueError('Qwen did not use the documented per-job seed application')
        return record

    def save_response(self, jid, record, runtime):
        self.check_response(jid, record, runtime)
        path = self.response_path(jid)
        if path.exists():
            if read(path) != record:
                raise ValueError('Saved Qwen response would be replaced')
        else:
            write_json(path, record, replace=False)
        self.state('generation', jid, 'completed', source_sha256=file_hash(path))

    def make_annotation_job(self, jid):
        entry = deepcopy(self.by_job[jid])
        record = read(self.response_path(jid))
        source_hash = file_hash(self.response_path(jid))
        entry['call_id'] = jid
        adapted = {'call_id': jid, 'case_id': entry['case_id'], 'response': record['response']}
        try:
            if entry['family'] == 'ORIGINAL':
                try:
                    inp = source_input(entry, adapted)
                    status = {'status': 'complete', 'coverage_scope': 'complete_saved_explanation'}
                except ValueError:
                    inp, status = edited_input(entry, adapted)
                request, schema = request_for(entry, inp, self.guide, self.supplement)
                comparison = None
            else:
                inp, status = edited_input(entry, adapted)
                original = self.entries[f"{entry['case_id']}__with_history__ORIGINAL"]
                request, schema, comparison = edited_request(entry, inp, original, self.guide,
                                                               self.supplement, self.extension, status)
        except ValueError as error:
            return None, {'status': 'source_unassessable', 'reason': str(error), 'source_response_sha256': source_hash}
        job = {'job_id': jid, 'source_response_id': jid, 'case_id': entry['case_id'],
               'family': entry['family'], 'source_response_sha256': source_hash,
               'annotation_input': inp, 'source_explanation': status,
               'comparison_context': comparison,
               'request': request, 'schema': schema,
               'annotation_guide': self.guide, 'requested_settings': LUNA_SETTINGS,
               'sdk_settings': SDK_SETTINGS}
        if entry['family'] != 'ORIGINAL':
            job['patch'] = entry['patch']
        job['job_signature'] = digest(job)
        return job, None

    def annotation(self, jid, secret):
        job, source_issue = self.make_annotation_job(jid)
        if source_issue:
            self.state('annotation', jid, **source_issue)
            return
        path = self.out / 'annotation_jobs' / f'{jid}.json'
        if path.exists():
            if read(path) != job:
                raise ValueError('Frozen Luna request changed')
        else:
            write_json(path, job, replace=False)
        result = self.annotation_path(jid)
        if result.exists():
            saved = read(result)
            if saved['job_signature'] != job['job_signature'] or saved['source_response_sha256'] != job['source_response_sha256']:
                raise ValueError('Saved Luna annotation differs from job')
            return
        attempts = sorted((self.out / 'annotation_attempts' / jid).glob('*.json'))
        for attempt in attempts:
            raw = self.out / 'annotation_raw' / jid / attempt.name
            if raw.exists():
                self.save_annotation(job, raw.read_bytes(), int(attempt.stem))
                return
        if attempts and read(attempts[-1])['status'] in ('started', 'execution_uncertain'):
            self.state('annotation', jid, 'execution_uncertain', reason='Prior API outcome unknown; no automatic resend')
            return
        if attempts and read(attempts[-1])['status'] not in ('retryable_error', 'retry_deferred'):
            return
        from openai import OpenAI, APIStatusError, APIConnectionError, APITimeoutError
        for number in range(len(attempts) + 1, MAX_ATTEMPTS + 1):
            if self.stop.is_set():
                return
            ap = self.out / 'annotation_attempts' / jid / f'{number:02d}.json'
            request_id = 'choice8-' + job['job_signature'][:40] + '-' + str(number)
            started = {'job_id': jid, 'job_signature': job['job_signature'], 'status': 'started',
                       'attempt_number': number, 'utc': now(), 'client_request_id': request_id}
            write_json(ap, started, replace=False)
            self.state('annotation', jid, 'running', attempt_number=number)
            try:
                with OpenAI(api_key=secret, base_url=SDK_SETTINGS['base_url'], max_retries=0,
                            timeout=SDK_SETTINGS['timeout_seconds']) as client:
                    raw = client.responses.with_raw_response.create(**job['request'], extra_headers={'X-Client-Request-Id': request_id})
                    body = raw.content
                    atomic_bytes(self.out / 'annotation_raw' / jid / f'{number:02d}.json', body)
                    write_json(self.out / 'annotation_transport' / jid / f'{number:02d}.json',
                               {'status_code': raw.status_code, 'request_id': raw.headers.get('x-request-id'),
                                'client_request_id': request_id}, replace=False)
                status = self.save_annotation(job, body, number)
                write_json(ap, {**started, 'status': status, 'completed_utc': now()})
                return
            except (APIConnectionError, APITimeoutError) as error:
                write_json(ap, {**started, 'status': 'execution_uncertain', 'error_type': type(error).__name__, 'completed_utc': now()})
                self.state('annotation', jid, 'execution_uncertain', reason='Request outcome unknown; no automatic resend')
                return
            except APIStatusError as error:
                code = error.status_code
                detail = error.body if isinstance(error.body, dict) else {}
                inner = detail.get('error', detail)
                error_code = str(inner.get('code', '') if isinstance(inner, dict) else '')
                fatal = code in (401, 403, 404) or any(s in error_code.lower() for s in ('quota', 'billing', 'credit', 'spend'))
                temporary = code in (429, 500, 502, 503, 504) and not fatal
                delay = retry_delay(error.response.headers, number)
                status = 'retryable_error' if temporary and number < MAX_ATTEMPTS else 'failed'
                if delay > 900 and temporary:
                    status = 'retry_deferred'
                write_json(ap, {**started, 'status': status, 'http_status': code,
                                'error_code': error_code, 'retry_not_before_epoch': time() + delay,
                                'completed_utc': now()})
                self.state('annotation', jid, status, http_status=code, error_code=error_code)
                if fatal or status == 'retry_deferred':
                    self.stop.set()
                    return
                if status != 'retryable_error':
                    return
                sleep(delay)
            except Exception as error:
                # A local error after request start may have consumed a response.
                write_json(ap, {**started, 'status': 'execution_uncertain', 'error_type': type(error).__name__, 'completed_utc': now()})
                self.state('annotation', jid, 'execution_uncertain', reason='Unexpected post-start error; inspect raw response before retry')
                self.stop.set()
                return
        self.state('annotation', jid, 'failed', reason='Bounded retries exhausted')

    def save_annotation(self, job, body, number):
        api = json.loads(body)
        raw_text = ''.join(output_text_parts(api))
        parsed, validation = validate_batch_result(raw_text, job, api)
        status = 'completed' if validation['schema_and_traceability_ok'] else 'completed_with_validation_errors'
        if job['source_explanation']['status'] != 'complete' and status == 'completed':
            status = 'completed_partial_source'
        record = {'job_id': job['job_id'], 'job_signature': job['job_signature'],
                  'source_response_sha256': job['source_response_sha256'], 'source_explanation': job['source_explanation'],
                  'exact_request': job['request'], 'requested_settings': LUNA_SETTINGS,
                  'sdk_settings': SDK_SETTINGS, 'api_response_id': api.get('id'), 'returned_model': api.get('model'),
                  'raw_api_response': body.decode(), 'raw_annotation_response': raw_text,
                  'parsed_annotation': parsed, 'validation': validation, 'usage': api.get('usage'),
                  'status': status, 'human_reviewed': False, 'saved_utc': now(), 'attempt_number': number}
        atomic_bytes(self.annotation_path(job['job_id']), (json.dumps(record, ensure_ascii=False, indent=2) + '\n').encode())
        self.state('annotation', job['job_id'], status, validation_ok=validation['schema_and_traceability_ok'])
        return status

    def worker(self, secret):
        while True:
            jid = self.queue.get()
            if jid is None:
                self.queue.task_done()
                return
            try:
                self.annotation(jid, secret)
            except Exception as error:
                self.state('annotation', jid, 'execution_uncertain', reason='Worker error; inspect saved attempt/raw files', error_type=type(error).__name__)
                self.stop.set()
            finally:
                self.queue.task_done()

    def status(self, job_ids=None):
        generation = Counter(); annotation = Counter()
        jobs = job_ids if job_ids is not None else self.manifest['job_order']
        for jid in jobs:
            generation[read(self.out / 'states/generation' / f'{jid}.json')['status'] if (self.out / 'states/generation' / f'{jid}.json').exists() else 'pending'] += 1
            annotation[read(self.out / 'states/annotation' / f'{jid}.json')['status'] if (self.out / 'states/annotation' / f'{jid}.json').exists() else 'pending'] += 1
        return {'utc': now(), 'experiment_id': self.manifest['experiment_id'], 'jobs': len(jobs),
                'generation': dict(generation), 'annotation': dict(annotation)}

    def run(self, scope=None):
        jobs = scope['job_order'] if scope is not None else self.manifest['job_order']
        state_dir = self.out / scope.get('checkpoint_dir', 'two_case_checkpoint') if scope is not None else self.out
        if scope is not None and (len(jobs) != sum(scope['required_per_case'].values()) or len(scope['selected']) != 2):
            raise ValueError('Two-case scope has an inconsistent job count')
        with lock(self.out / '.runner.lock'):
            secret = key()
            if not secret:
                raise RuntimeError('OPENAI_API_KEY unavailable from existing private EC2 configuration')
            client = Client()
            runtime = client.get('/repeated8/runtime')
            if runtime['experiment_id'] != self.manifest['experiment_id'] or runtime['effective_settings']['do_sample'] is not True or runtime['effective_settings']['temperature'] != 0.7:
                raise ValueError('Server has not verified stochastic settings')
            config_path = self.out / 'runtime.json'
            if config_path.exists() and read(config_path) != runtime:
                raise ValueError('Effective Qwen runtime changed')
            if not config_path.exists():
                write_json(config_path, runtime, replace=False)
            write_json(state_dir / 'runner_state.json', {'status': 'running', 'pid': os.getpid(), 'utc': now(),
                       'experiment_id': self.manifest['experiment_id'], 'scope_id': scope['scope_id'] if scope else None})
            workers = [Thread(target=self.worker, args=(secret,), daemon=True) for _ in range(4)]
            for thread in workers:
                thread.start()
            queued = set()
            try:
                for jid in jobs:
                    if self.response_path(jid).exists():
                        self.check_response(jid, read(self.response_path(jid)), runtime)
                        self.state('generation', jid, 'completed', source_sha256=file_hash(self.response_path(jid)))
                        self.queue.put(jid); queued.add(jid)
                for jid in jobs:
                    if self.stop.is_set():
                        break
                    if self.response_path(jid).exists():
                        continue
                    entry = self.by_job[jid]
                    sig = signature(self.manifest, entry, runtime, jid)
                    prior = self.out / 'states/generation' / f'{jid}.json'
                    state = read(prior)['status'] if prior.exists() else 'pending'
                    if state in ('running', 'uncertain', 'failed'):
                        journal = client.get('/repeated8/attempt/' + jid)
                        if journal['status'] == 'completed':
                            self.save_response(jid, journal['record'], runtime)
                            self.queue.put(jid); queued.add(jid)
                            continue
                        self.state('generation', jid, 'uncertain' if journal['status'] != 'failed' else 'failed', server_status=journal['status'])
                        break
                    self.state('generation', jid, 'running', input_signature=sig)
                    try:
                        record = client.post('/repeated8/generate', {'experiment_id': self.manifest['experiment_id'],
                                          'job_id': jid, 'input_signature': sig})
                        self.save_response(jid, record, runtime)
                    except Exception as error:
                        try:
                            journal = client.get('/repeated8/attempt/' + jid)
                        except Exception:
                            journal = {'status': 'unavailable'}
                        if journal['status'] == 'completed':
                            self.save_response(jid, journal['record'], runtime)
                        else:
                            self.state('generation', jid, 'failed' if journal['status'] == 'failed' else 'uncertain',
                                       server_status=journal['status'], error_type=type(error).__name__)
                            break
                    self.queue.put(jid); queued.add(jid)
                    if len(queued) % 10 == 0:
                        write_json(state_dir / 'progress.json', self.status(jobs))
                        print(json.dumps(self.status(jobs)), flush=True)
                self.queue.join()
            finally:
                for _ in workers:
                    self.queue.put(None)
                for thread in workers:
                    thread.join(timeout=5)
            progress = self.status(jobs)
            from .repeated8_analysis import analyze
            if progress['generation'].get('completed', 0) == len(jobs):
                analyze(self.out, case_ids=[s['case_id'] for s in scope['selected']], destination=state_dir) if scope else analyze(self.out)
                state = 'complete' if progress['annotation'].get('completed', 0) == len(jobs) else 'finished_with_annotation_issues'
            else:
                state = 'stopped_incomplete'
            write_json(state_dir / 'runner_state.json', {'status': state, 'pid': os.getpid(), 'utc': now(),
                       'scope_id': scope['scope_id'] if scope else None, 'progress': progress})
            return progress
