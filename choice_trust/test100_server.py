"""Authenticated joint transport on the existing model-server application.

Run this wrapper instead of server:app, with the SAME environment/port/venv.
It loads one model through the original lifespan and calls the existing frozen
joint generator. It does not use the incompatible legacy /explain endpoint.
"""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import re

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from server import app, authenticate
from .joint_observation import JOINT_GENERATION_SETTINGS, generate_joint_response
from .development_pilot import digest, verify_edit
from .test100_plan import verify_manifest, DEFAULT_OUT
from .test100_execution import write_json, signature, lock, now

ROOT=Path(__file__).resolve().parents[1]
OUT=Path(os.environ.get('TEST100_OUT',str(DEFAULT_OUT))).resolve()
MODEL='Qwen/Qwen3-1.7B';REVISION='70d244cc86ccca08cf5af4e1e306ecf908b1ad5e'
CACHE={}


def context(request):
    engine=request.app.state.engine
    if 'runtime' in CACHE:return CACHE
    import torch,transformers
    from transformers import GenerationConfig
    manifest=verify_manifest(OUT)
    metadata={'model_id':engine.settings.model_id,'revision':engine.revision,
      'tokenizer':engine.tokenizer.name_or_path,'tokenizer_revision':engine.revision,
      'device':str(engine.device),'dtype':str(engine.dtype),
      'torch':torch.__version__,'transformers':transformers.__version__}
    if metadata['model_id']!=MODEL or metadata['revision']!=REVISION or metadata['device']!='cpu' or metadata['dtype']!='torch.float32':
        raise HTTPException(409,'Existing model does not match the frozen CPU joint protocol')
    config=GenerationConfig(do_sample=False,max_new_tokens=512,num_beams=1,
        eos_token_id=engine.model.generation_config.eos_token_id,pad_token_id=engine.tokenizer.eos_token_id)
    effective={**JOINT_GENERATION_SETTINGS,'eos_token_id':config.eos_token_id,'pad_token_id':config.pad_token_id,
               'use_cache':config.use_cache,'max_input_tokens':4096}
    prompts={};entries={e['call_id']:e for e in manifest['entries']}
    for e in entries.values():
        if e['skip_reason']:continue
        verify_edit(e,manifest['development_price_bounds_cents'])
        rendered=engine.tokenizer.apply_chat_template(e['messages'],tokenize=False,add_generation_prompt=True,enable_thinking=False)
        n=len(engine.tokenizer.encode(rendered,add_special_tokens=False))
        if n>4096:raise HTTPException(409,'A prepared prompt exceeds the frozen input limit; no truncation allowed')
        prompts[e['call_id']]={'rendered_prompt':rendered,'input_tokens':n}
    path=OUT/'rendered_prompts.json'
    if path.exists():
        if json.loads(path.read_text())!=prompts:raise HTTPException(409,'Frozen rendered prompt cache changed')
    else:write_json(path,prompts,replace=False)
    runtime={'plan_id':manifest['plan_id'],'model':metadata,'effective_settings':effective,
        'generation_config':config.to_dict(),'tokenizer_chat_template_sha256':sha256(engine.tokenizer.chat_template.encode()).hexdigest(),
        'rendered_prompts_digest':digest(prompts),'max_input_tokens':max(p['input_tokens'] for p in prompts.values()),
        'joint_generator_sha256':sha256((ROOT/'choice_trust/joint_observation.py').read_bytes()).hexdigest(),
        'server_wrapper_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'base_server_sha256':sha256((ROOT/'server.py').read_bytes()).hexdigest()}
    CACHE.update(manifest=manifest,entries=entries,prompts=prompts,runtime=runtime,config=config)
    return CACHE


class GenerateRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    plan_id:str
    call_id:str
    input_signature:str


def checked_id(cid):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,180}',cid):raise HTTPException(400,'Invalid call identifier')
    return cid


@app.get('/test100/runtime',dependencies=[Depends(authenticate)])
def runtime(request:Request):
    # No inference: only render/verify all frozen prompts with existing tokenizer.
    with request.app.state.engine.lock:return context(request)['runtime']


@app.get('/test100/attempt/{call_id}',dependencies=[Depends(authenticate)])
def attempt(call_id:str):
    cid=checked_id(call_id);response=OUT/'server_responses'/f'{cid}.json';state=OUT/'server_attempts'/f'{cid}.json'
    if response.exists():return {'status':'completed','record':json.loads(response.read_text())}
    if state.exists():return json.loads(state.read_text())
    return {'status':'not_started'}


@app.post('/test100/generate',dependencies=[Depends(authenticate)])
def generate(payload:GenerateRequest,request:Request):
    cid=checked_id(payload.call_id);engine=request.app.state.engine
    with engine.lock:
        c=context(request);entry=c['entries'].get(cid)
        if payload.plan_id!=c['manifest']['plan_id'] or entry is None or entry['skip_reason']:
            raise HTTPException(400,'Request is outside the frozen applicable study plan')
        expected=signature(c['manifest'],entry,c['runtime'],c['prompts'][cid]['rendered_prompt'])
        if expected!=payload.input_signature:raise HTTPException(400,'Input/runtime signature mismatch')
        state=OUT/'server_attempts'/f'{cid}.json'
        with lock(OUT/'.server_generation.lock'):
            if state.exists() or (OUT/'server_responses'/f'{cid}.json').exists():
                raise HTTPException(409,'Prior attempt exists; inspect journal instead of repeating generation')
            verify_edit(entry,c['manifest']['development_price_bounds_cents'])
            write_json(state,{'status':'running','call_id':cid,'started_utc':now(),'input_signature':expected},replace=False)
            try:
                result=generate_joint_response(entry['observations'],entry['observations']['candidates'],
                    model=engine.model,tokenizer=engine.tokenizer,device=engine.device,
                    generation_config=c['config'],model_metadata=c['runtime']['model'])
                record={'call_id':cid,'plan_id':payload.plan_id,'input_signature':expected,'response':result}
                write_json(OUT/'server_responses'/f'{cid}.json',record,replace=False)
                write_json(state,{'status':'completed','call_id':cid,'ended_utc':now(),'input_signature':expected})
                return record
            except Exception as error:
                write_json(state,{'status':'failed','call_id':cid,'ended_utc':now(),'error_type':type(error).__name__,
                                  'error':'Model/infrastructure exception; no automatic retry','input_signature':expected})
                raise HTTPException(500,'Generation failed; server journal preserved the attempt') from None
