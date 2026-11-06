"""Authenticated single-model stochastic endpoint with one-attempt job journaling."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import os
import re

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from transformers import GenerationConfig

from server import app, authenticate
from .development_pilot import digest, verify_edit
from .repeated8 import OUT, MODEL, SETTINGS, verify, job_id, read, signature
from .repeated8_generation import generate as sample
from .test100_execution import lock, write_json, now

SERVER_OUT = Path(os.environ.get('REPEATED8_OUT', OUT)).resolve()
CACHE = {}


def context(request):
    if CACHE:
        return CACHE
    import torch, transformers
    engine = request.app.state.engine
    manifest = verify(SERVER_OUT)
    model = {'model_id': engine.settings.model_id, 'revision': engine.revision,
             'tokenizer_revision': engine.revision, 'tokenizer': engine.tokenizer.name_or_path,
             'device': str(engine.device), 'dtype': str(engine.dtype),
             'torch': torch.__version__, 'transformers': transformers.__version__}
    if any(model[k] != v for k, v in MODEL.items()):
        raise HTTPException(409, 'Qwen model, revision or precision differs from frozen protocol')
    config = GenerationConfig(do_sample=True, temperature=0.7, top_p=1.0, top_k=50,
                              num_beams=1, max_new_tokens=512,
                              eos_token_id=engine.model.generation_config.eos_token_id,
                              pad_token_id=engine.tokenizer.eos_token_id)
    if any(getattr(config, k) != SETTINGS[k] for k in ('do_sample', 'temperature', 'top_p', 'top_k', 'num_beams', 'max_new_tokens')):
        raise HTTPException(409, 'Server generation configuration does not apply sampling')
    entries = {e['call_id']: e for e in manifest['entries']}
    jobs = {job_id(e['case_id'], e['call_id'], r): e for e in entries.values() if e['applicable'] for r in range(50)}
    if set(jobs) != set(manifest['job_order']):
        raise HTTPException(409, 'Server job set differs from frozen manifest')
    prompts = {}
    bounds = read(Path(__file__).resolve().parents[1] / 'choice_study/test_with_history_100_v1/manifest.json')['development_price_bounds_cents']
    for entry in entries.values():
        if not entry['applicable']:
            continue
        verify_edit(entry, bounds)
        prompt = engine.tokenizer.apply_chat_template(entry['messages'], tokenize=False, add_generation_prompt=True, enable_thinking=False)
        count = len(engine.tokenizer.encode(prompt, add_special_tokens=False))
        if count > 4096:
            raise HTTPException(409, 'Frozen prompt exceeds input limit')
        prompts[entry['call_id']] = {'rendered_prompt': prompt, 'input_tokens': count}
    runtime = {'experiment_id': manifest['experiment_id'], 'model': model,
               'effective_settings': {**SETTINGS, 'eos_token_id': config.eos_token_id,
                                      'pad_token_id': config.pad_token_id, 'use_cache': config.use_cache},
               'generation_config': config.to_dict(), 'rendered_prompts_digest': digest(prompts),
               'chat_template_sha256': sha256(engine.tokenizer.chat_template.encode()).hexdigest(),
               'generation_code_sha256': sha256((Path(__file__).parent / 'repeated8_generation.py').read_bytes()).hexdigest()}
    saved = SERVER_OUT / 'rendered_prompts.json'
    if saved.exists() and read(saved) != prompts:
        raise HTTPException(409, 'Rendered prompts changed')
    if not saved.exists():
        write_json(saved, prompts, replace=False)
    CACHE.update(manifest=manifest, entries=entries, jobs=jobs, prompts=prompts, runtime=runtime, config=config)
    return CACHE


class GenerationJob(BaseModel):
    model_config = ConfigDict(extra='forbid')
    experiment_id: str
    job_id: str
    input_signature: str


def checked_id(value):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise HTTPException(400, 'Invalid job ID')
    return value


@app.get('/repeated8/runtime', dependencies=[Depends(authenticate)])
def runtime(request: Request):
    with request.app.state.engine.lock:
        return context(request)['runtime']


@app.get('/repeated8/attempt/{jid}', dependencies=[Depends(authenticate)])
def attempt(jid: str):
    jid = checked_id(jid)
    response = SERVER_OUT / 'server_responses' / f'{jid}.json'
    state = SERVER_OUT / 'server_attempts' / f'{jid}.json'
    if response.exists():
        return {'status': 'completed', 'record': read(response)}
    if state.exists():
        return read(state)
    return {'status': 'not_started'}


@app.post('/repeated8/generate', dependencies=[Depends(authenticate)])
def generate(payload: GenerationJob, request: Request):
    jid = checked_id(payload.job_id)
    engine = request.app.state.engine
    with engine.lock:
        c = context(request)
        entry = c['jobs'].get(jid)
        if payload.experiment_id != c['manifest']['experiment_id'] or entry is None:
            raise HTTPException(400, 'Job is outside frozen experiment')
        sig = signature(c['manifest'], entry, c['runtime'], jid)
        if sig != payload.input_signature:
            raise HTTPException(400, 'Input signature mismatch')
        state = SERVER_OUT / 'server_attempts' / f'{jid}.json'
        with lock(SERVER_OUT / '.generation.lock'):
            if state.exists() or (SERVER_OUT / 'server_responses' / f'{jid}.json').exists():
                raise HTTPException(409, 'Prior attempt exists; inspect journal')
            seed = int(sha256((c['manifest']['experiment_id'] + '|' + jid).encode()).hexdigest()[:16], 16)
            write_json(state, {'status': 'running', 'job_id': jid, 'input_signature': sig,
                               'seed': seed, 'started_utc': now()}, replace=False)
            try:
                result = sample(entry, model=engine.model, tokenizer=engine.tokenizer,
                                device=engine.device, config=c['config'], metadata=c['runtime']['model'], seed=seed)
                if result['rendered_prompt'] != c['prompts'][entry['call_id']]['rendered_prompt']:
                    raise ValueError('Actual generation prompt changed')
                record = {'job_id': jid, 'call_id': entry['call_id'], 'case_id': entry['case_id'],
                          'family': entry['family'], 'experiment_id': payload.experiment_id,
                          'input_signature': sig, 'response': result, 'saved_utc': now()}
                write_json(SERVER_OUT / 'server_responses' / f'{jid}.json', record, replace=False)
                write_json(state, {'status': 'completed', 'job_id': jid, 'input_signature': sig,
                                   'ended_utc': now(), 'seed': seed})
                return record
            except Exception as error:
                write_json(state, {'status': 'failed', 'job_id': jid, 'input_signature': sig,
                                   'ended_utc': now(), 'error_type': type(error).__name__,
                                   'error_message': str(error)[:500],
                                   'reason': 'Generation failed; no automatic retry'})
                raise HTTPException(500, 'Generation failed; inspect server journal') from None
