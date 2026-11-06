"""Exactly-once-attempt HTTP execution for the frozen 100-case joint study.

No annotation or local model loading. Lost HTTP responses are recovered only by
reading the server journal, never by automatically resending generation requests.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import fcntl
import json
import os
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from .development_pilot import digest, verify_edit
from .joint_observation import JOINT_GENERATION_SETTINGS, JOINT_PROMPT_VERSION, parse_joint_response
from .test100_plan import verify_manifest, DEFAULT_OUT


def now(): return datetime.now(timezone.utc).isoformat()


def write_json(path, value, *, replace=True):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno());temp=f.name
    try:
        if replace:os.replace(temp,path)
        else:os.link(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def event(out, **fields):
    with (Path(out)/'events.jsonl').open('a') as f:
        f.write(json.dumps({'utc':now(),**fields},ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())


@contextmanager
def lock(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another process holds the study run lock') from None
        f.seek(0);f.truncate();f.write(str(os.getpid()));f.flush()
        try:yield
        finally:fcntl.flock(f,fcntl.LOCK_UN)


def execution_hashes():
    root=Path(__file__).resolve().parents[1]
    return {p:sha256((root/p).read_bytes()).hexdigest() for p in
            ['choice_trust/test100_execution.py','choice_trust/test100_server.py','scripts/run_test100.py']}


def signature(manifest,entry,runtime,rendered):
    return digest({'plan_id':manifest['plan_id'],'entry':entry,'runtime':runtime,'rendered_prompt':rendered})


class HTTPClient:
    def __init__(self, base='http://127.0.0.1:8000', key=None, timeout=900):
        self.base=base.rstrip('/');self.key=key or os.environ.get('MODEL_API_KEY');self.timeout=timeout
        if not self.key:raise ValueError('MODEL_API_KEY is unavailable; use the existing secure mechanism')
    def request(self,route,payload=None):
        req=Request(self.base+route,data=None if payload is None else json.dumps(payload).encode(),
          headers={'Authorization':'Bearer '+self.key,'Content-Type':'application/json'})
        # Deliberately one HTTP request, with no retry loop.
        with urlopen(req,timeout=self.timeout) as r:return json.load(r)


def original_candidates(root):
    root=Path(root)
    archived_path=root/'choice_study/development_counterfactual_v1/manifest.json'
    archived=json.loads(archived_path.read_text()) if archived_path.exists() else {}
    archive_entries={e['call_id']:e for e in archived.get('entries',[])}
    paths=list((root/'choice_study/joint_observation_runs').glob('*/*.json'))
    paths+=list((root/'choice_study/development_counterfactual_v1/responses').glob('*__ORIGINAL.json'))
    for path in sorted(paths):
        try:
            outer=json.loads(path.read_text());r=outer.get('response',outer)
            if outer.get('condition')!='with_history' or outer.get('family','ORIGINAL')!='ORIGINAL':continue
            if r.get('prompt_version')!=JOINT_PROMPT_VERSION:continue
            observations=outer.get('observation_result')
            if observations is None and outer.get('call_id') in archive_entries:
                observations=archive_entries[outer['call_id']].get('observations')
            provenance={'source_path':str(path),'sha256':sha256(path.read_bytes()).hexdigest()}
            if outer.get('call_id') in archive_entries:
                provenance['observation_manifest']={'path':str(archived_path),'sha256':sha256(archived_path.read_bytes()).hexdigest()}
            yield path,{**outer,'_matched_observations':observations,'_reuse_provenance':provenance},r
        except (ValueError,OSError):continue


def model_matches(model,expected):
    revision=expected['revision'];tokenizer=model.get('tokenizer','')
    return (all(model.get(k)==expected.get(k) for k in ('model_id','revision','device','dtype','torch','transformers'))
            and (model.get('tokenizer_revision')==revision or revision in tokenizer))


def original_matches(entry,outer,r,runtime,rendered):
    model=r.get('generation_metadata',{}).get('model',{})
    expected=runtime['model']
    # Missing tokenizer provenance or settings is a reason to generate, never guess.
    tokenizer=model.get('tokenizer','')
    revision=expected['revision']
    identity=model_matches(model,expected)
    return bool(identity and r.get('messages')==entry['messages'] and r.get('rendered_prompt')==rendered
                and outer.get('_matched_observations')==entry['observations']
                and r.get('observation_version')==entry['observations']['version']
                and r.get('generation_metadata',{}).get('effective_settings')==runtime['effective_settings']
                and all(model.get(k)==expected.get(k) for k in ('torch','transformers')))


class Study:
    def __init__(self,out=DEFAULT_OUT):
        self.out=Path(out);self.manifest=verify_manifest(self.out)
        self.entries={e['call_id']:e for e in self.manifest['entries']}
    def state(self,cid,**fields):
        write_json(self.out/'items'/f'{cid}.json',{'call_id':cid,'utc':now(),**fields})
    def initialize(self):
        for cid,e in self.entries.items():
            p=self.out/'items'/f'{cid}.json'
            if not p.exists():self.state(cid,status='not_applicable' if e['skip_reason'] else 'pending',skip_reason=e['skip_reason'])
    def bind(self,client):
        runtime=client.request('/test100/runtime')
        if runtime['plan_id']!=self.manifest['plan_id']:raise ValueError('Server loaded a different study manifest')
        for k,v in self.manifest['joint_settings'].items():
            if runtime['effective_settings'].get(k)!=v:raise ValueError('Server joint generation settings differ: '+k)
        prompts=json.loads((self.out/'rendered_prompts.json').read_text())
        if digest(prompts)!=runtime['rendered_prompts_digest']:raise ValueError('Rendered prompt cache does not match server')
        config={'plan_id':self.manifest['plan_id'],'runtime':runtime,'execution_hashes':execution_hashes(),
                'annotation_policy':'No bulk annotation; unchecked pilot labels are not evaluation labels',
                'retry_policy':'No automatic generation retries; recover completed server records read-only'}
        p=self.out/'execution_config.json'
        if p.exists() and json.loads(p.read_text())!=config:raise ValueError('Frozen execution configuration changed')
        if not p.exists():write_json(p,config,replace=False)
        self.runtime,self.prompts=runtime,prompts
    def consume(self,entry,server_record,*,status='completed',reuse=None):
        cid=entry['call_id'];r=server_record['response'];expected=signature(self.manifest,entry,self.runtime,self.prompts[cid]['rendered_prompt'])
        if server_record['input_signature']!=expected:raise ValueError('Response input signature mismatch')
        if r['messages']!=entry['messages'] or r['rendered_prompt']!=self.prompts[cid]['rendered_prompt']:raise ValueError('Response prompt mismatch')
        if r['generation_metadata']['effective_settings']!=self.runtime['effective_settings']:raise ValueError('Response settings mismatch')
        if not model_matches(r['generation_metadata']['model'],self.runtime['model']):raise ValueError('Response model/tokenizer identity mismatch')
        parsed,diagnostics=parse_joint_response(r['raw_response'],entry['observations']['candidates'],entry['observations'],truncated=r['diagnostics']['generation_truncated'])
        if parsed!=r['parsed_result'] or diagnostics!=r['diagnostics']:raise ValueError('Raw response/parsed diagnostics mismatch')
        answer=parsed.get('prediction') if isinstance(parsed,dict) else None
        inverse={v:k for k,v in entry['presentation']['answer_mapping'].items()}
        decoded=inverse.get(answer) if isinstance(answer,str) else None
        record={'call_id':cid,'case_id':entry['case_id'],'condition':'with_history','family':entry['family'],
                'input_signature':expected,'plan_id':self.manifest['plan_id'],'decoded_product_id':decoded,
                'response':r,'review_status':'not_annotated; no human review claimed','reuse_provenance':reuse}
        p=self.out/'responses'/f'{cid}.json'
        if p.exists():
            if json.loads(p.read_text())!=record:raise ValueError('Completed record would be overwritten')
        else:write_json(p,record,replace=False)
        self.state(cid,status=status,input_signature=expected,parsing_valid=diagnostics['parse_ok'],
                   prediction_valid=diagnostics['prediction_valid'],reuse_provenance=reuse)
        event(self.out,event=status,call_id=cid,input_signature=expected)
    def status(self):
        self.initialize()
        counts={};families={}
        for cid,e in self.entries.items():
            s=json.loads((self.out/'items'/f'{cid}.json').read_text())['status']
            counts[s]=counts.get(s,0)+1
            families.setdefault(e['family'],{});families[e['family']][s]=families[e['family']].get(s,0)+1
        return {'plan_id':self.manifest['plan_id'],'selected_cases':len(self.manifest['selected_cases']),
                'planned_items':len(self.entries),'status_counts':counts,'families':families,
                'complete':all(k in ('reused','completed','not_applicable') for k in counts),
                'annotation_status':'not launched; automatic pilot annotations not accepted as labels'}
    def run(self,client,search_root=None):
        with lock(self.out/'.runner.lock'):
            self.initialize();self.bind(client)
            event(self.out,event='runner_started',pid=os.getpid(),plan_id=self.manifest['plan_id'])
            write_json(self.out/'runner_state.json',{'status':'running','pid':os.getpid(),'started_utc':now(),'plan_id':self.manifest['plan_id']})
            roots=[Path(search_root)] if search_root else [Path(p) for p in json.loads(os.environ.get('TEST100_REUSE_ROOTS',json.dumps([str(Path(__file__).resolve().parents[1])])))]
            originals=[];seen=set()
            for root in roots:
                for candidate in original_candidates(root):
                    if str(candidate[0].resolve()) not in seen:
                        seen.add(str(candidate[0].resolve()));originals.append(candidate)
            event(self.out,event='original_reuse_search',roots=[str(p) for p in roots],joint_original_candidates=len(originals))
            try:
                for cid,e in self.entries.items():
                    s=json.loads((self.out/'items'/f'{cid}.json').read_text())
                    path=self.out/'responses'/f'{cid}.json'
                    if s['status']=='not_applicable':continue
                    verify_edit(e,self.manifest['development_price_bounds_cents'])
                    expected=signature(self.manifest,e,self.runtime,self.prompts[cid]['rendered_prompt'])
                    if path.exists():
                        record=json.loads(path.read_text())
                        if record['input_signature']!=expected:raise ValueError('Saved record signature changed')
                        self.consume(e,{'response':record['response'],'input_signature':expected},
                                     status='reused' if record.get('reuse_provenance') else 'completed',reuse=record.get('reuse_provenance'))
                        event(self.out,event='verified_existing',call_id=cid,source=str(path),signature=expected)
                        continue
                    if s['status'] in ('uncertain','running','completed','reused'):
                        journal=client.request('/test100/attempt/'+cid)
                        if journal['status']=='completed':self.consume(e,journal['record']);continue
                        if journal['status']=='failed':self.state(cid,status='failed',error=journal.get('error'),recovery='Server journal confirms failed attempt');continue
                        self.state(cid,status='uncertain',error='Prior request unresolved; no repeat was issued');continue
                    if s['status']=='failed':continue
                    if e['family']=='ORIGINAL':
                        match=next(((p,o,r) for p,o,r in originals if o.get('case_id')==e['case_id'] and original_matches(e,o,r,self.runtime,self.prompts[cid]['rendered_prompt'])),None)
                        if match:
                            p,o,r=match;self.consume(e,{'response':r,'input_signature':expected},status='reused',reuse={**o['_reuse_provenance'],'exact_input_and_configuration_match':True});continue
                    self.state(cid,status='running',input_signature=expected)
                    event(self.out,event='request_started',call_id=cid,input_signature=expected)
                    print(now(),'GENERATE',cid,flush=True)
                    try:
                        result=client.request('/test100/generate',{'plan_id':self.manifest['plan_id'],'call_id':cid,'input_signature':expected})
                        # Preserve transport payload even if subsequent validation detects a discrepancy.
                        write_json(self.out/'received'/f'{cid}.json',result,replace=False)
                        self.consume(e,result)
                    except Exception as error:
                        # One read-only reconciliation; never resend generation.
                        try:journal=client.request('/test100/attempt/'+cid)
                        except Exception:journal={'status':'unavailable'}
                        if journal.get('status')=='completed':
                            self.consume(e,journal['record']);event(self.out,event='recovered_server_completion',call_id=cid)
                        else:
                            definite=journal.get('status')=='failed' or (isinstance(error,HTTPError) and error.code in (400,401,403,404,422) and journal.get('status')=='not_started')
                            self.state(cid,status='failed' if definite else 'uncertain',error_type=type(error).__name__,
                                       error='Generation or transport failed; inspect server journal. No automatic retry.',server_status=journal.get('status'))
                            event(self.out,event='infrastructure_failure',call_id=cid,error_type=type(error).__name__,server_status=journal.get('status'))
                            raise RuntimeError('Study stopped after an infrastructure/transport failure; completed work is preserved') from None
                final=self.status();write_json(self.out/'runner_state.json',{'status':'complete' if final['complete'] else 'incomplete','pid':os.getpid(),'ended_utc':now(),**final})
                print(json.dumps(final,indent=2),flush=True)
                return final
            except BaseException as error:
                if 'cid' in locals():
                    state_path=self.out/'items'/f'{cid}.json'
                    if state_path.exists() and json.loads(state_path.read_text())['status']=='running':
                        self.state(cid,status='uncertain',error_type=type(error).__name__,
                                   error='Stopped before trustworthy completion; recover server journal without repeating the request')
                write_json(self.out/'runner_state.json',{'status':'stopped_incomplete','pid':os.getpid(),'ended_utc':now(),'error_type':type(error).__name__,'progress':self.status()})
                raise
