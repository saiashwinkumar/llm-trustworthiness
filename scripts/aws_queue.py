"""Persistent EC2-only sequential queue; no model, prompt or scoring changes."""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from experiment import append_jsonl, read_jsonl
from choice_trust.storage import atomic_json, load_run
from scripts.run_resumed_study import verify_plan, recovery_status
from scripts.run_cpu_real_v2 import summarize
from scripts.verify_cpu_server import validate_health
from types import SimpleNamespace

CONTROL=ROOT/'execution_resumed_v1'
OUT=ROOT/'outputs_resumed_v1'
PHASES=['recovery','development','validation','freeze','test','report']
CHILD=None


def now():return datetime.now(timezone.utc).isoformat()


def processes():
    for path in Path('/proc').glob('[0-9]*'):
        try:
            args=path.joinpath('cmdline').read_bytes().split(b'\0')
            args=[x.decode(errors='replace') for x in args if x]
            yield int(path.name),args,path.joinpath('cwd').resolve()
        except (FileNotFoundError,PermissionError,ProcessLookupError):continue


def configure_server():
    servers=[(pid,args,cwd) for pid,args,cwd in processes()
             if 'uvicorn' in args and 'server:app' in args]
    if len(servers)!=1:raise ValueError(f'Expected one existing model server; found {len(servers)}')
    pid,_,cwd=servers[0]
    env=dict(x.split(b'=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in x)
    key=env.get(b'MODEL_API_KEY',b'').decode()
    if not key:raise ValueError('Existing server has no reusable MODEL_API_KEY in its environment')
    os.environ.update(MODEL_API_KEY=key,MODEL_BASE_URL='http://127.0.0.1:8000',
                      MODEL_TIMEOUT_SECONDS='900',PYTHONUNBUFFERED='1',PYTHONDONTWRITEBYTECODE='1')
    from choice_trust.model import RemoteBackend
    backend=RemoteBackend();validate_health(backend.health)
    if backend.metadata!=load_run(OUT)[0]['backend']:raise ValueError('Server metadata differs from saved run')
    return dict(pid=pid,cwd=str(cwd),base_url=os.environ['MODEL_BASE_URL'],health=backend.health,
                credential='Reused privately from existing server process; not copied to disk')


def no_competing_runner():
    matches=[]
    for pid,args,cwd in processes():
        if pid==os.getpid():continue
        scripts={'run_resumed_study.py','run_cpu_real_v2.py','check_development_workflow.py','experiment.py'}
        if ('choice_trust' in args or any(Path(a).name in scripts for a in args[1:])):
            matches.append(dict(pid=pid,args=args,cwd=str(cwd)))
    if matches:raise ValueError('Another experiment runner is active: '+json.dumps(matches))
    # The flock below handles .orchestrator.lock. The low-level writer uses an
    # exclusive PID file; only remove a demonstrably dead local PID's stale lock.
    lock=OUT/'.writer.lock'
    if lock.exists():
        pid=int(lock.read_text())
        if Path(f'/proc/{pid}').exists():raise ValueError(f'Writer PID {pid} still exists; do not remove its lock')
        append_jsonl(CONTROL/'queue_events.jsonl',dict(event='removed_dead_writer_lock',pid=pid,utc=now()))
        lock.unlink()


def snapshot(args,plan):
    cases=read_jsonl(args.cases)
    summary=summarize(OUT,cases,plan,CONTROL)
    summary['citation_recovery']=recovery_status(args,plan)
    return summary


def phase_complete(phase,s):
    if phase=='recovery':return s['citation_recovery']['measured']==s['citation_recovery']['planned']
    if phase in ('development','validation','test'):
        rows=[r for r in s['rows'] if r['phase']==phase]
        return bool(rows) and all(r['missing']==0 for r in rows)
    return False


def stop(signum,frame):
    if CHILD and CHILD.poll() is None:
        os.killpg(CHILD.pid,signal.SIGINT)
    raise KeyboardInterrupt


def run_queue():
    global CHILD
    args=SimpleNamespace(out=OUT,control=CONTROL,cases=ROOT/'data_v2/yogurt/cases.jsonl')
    cases=read_jsonl(args.cases);plan=verify_plan(args,cases)
    CONTROL.mkdir(exist_ok=True)
    with (CONTROL/'.queue.lock').open('a+') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('An EC2 queue already holds the lock') from None
        no_competing_runner()
        server=configure_server()
        atomic_json(CONTROL/'aws_server_verified.json',dict(utc=now(),**server))
        state=dict(status='running',queue_pid=os.getpid(),server_pid=server['pid'],started_utc=now(),
                   phases=PHASES,completed_phases=[],base_url=server['base_url'])
        atomic_json(CONTROL/'queue_state.json',state)
        for sig in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(sig,stop)
        try:
            for phase in PHASES:
                before=snapshot(args,plan)
                if phase_complete(phase,before):
                    state['completed_phases'].append(phase)
                    append_jsonl(CONTROL/'queue_events.jsonl',dict(event='already_complete',phase=phase,utc=now()))
                    atomic_json(CONTROL/f'queue_{phase}_completion.json',dict(phase=phase,status='already_complete',utc=now(),summary=before))
                    continue
                if phase=='freeze':
                    if not phase_complete('validation',before):raise ValueError('Validation is incomplete')
                    atomic_json(CONTROL/'automated_validation_review.json',dict(
                        utc=now(),review_type='Automated accounting and diagnostics; not a human factual-grounding review',
                        authorization='User requested autonomous execution of the prepared fixed protocol on AWS, including test.',
                        criterion='All planned validation attempts accounted for, including explicit skips; no favorable-result threshold.',
                        validation_rows=[r for r in before['rows'] if r['phase']=='validation'],
                        manual_grounding=before['manual_grounding']))
                attempt=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                log=CONTROL/f'queue_{phase}_{attempt}.log'
                command=[sys.executable,'-B','-u',str(ROOT/'scripts/run_resumed_study.py'),phase]
                if phase=='freeze':command.append('--ack-validation-review')
                state.update(current_phase=phase,current_log=str(log),phase_started_utc=now(),status='running')
                atomic_json(CONTROL/'queue_state.json',state)
                append_jsonl(CONTROL/'queue_events.jsonl',dict(event='start',phase=phase,utc=now(),log=str(log)))
                start=time.monotonic()
                print(now(),'START',phase,'log:',log,flush=True)
                with log.open('x') as output:
                    CHILD=subprocess.Popen(command,cwd=ROOT,env=os.environ.copy(),stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
                    state['child_pid']=CHILD.pid;atomic_json(CONTROL/'queue_state.json',state)
                    rc=CHILD.wait()
                CHILD=None
                after=snapshot(args,plan)
                success=rc==0 and (phase not in ('recovery','development','validation','test') or phase_complete(phase,after))
                completion=dict(phase=phase,status='complete' if success else 'failed',returncode=rc,
                    ended_utc=now(),elapsed_seconds=time.monotonic()-start,log=str(log),summary=after)
                atomic_json(CONTROL/f'queue_{phase}_completion.json',completion)
                append_jsonl(CONTROL/'queue_events.jsonl',{k:v for k,v in completion.items() if k!='summary'})
                if not success:raise RuntimeError(f'{phase} failed; see {log}. Repeat the same queue command to resume.')
                state['completed_phases'].append(phase)
                print(now(),'COMPLETE',phase,flush=True)
            state.update(status='automated_execution_complete',current_phase=None,finished_utc=now(),
                         manual_grounding_note='Manual review is separate; see execution_summary.json')
            atomic_json(CONTROL/'queue_state.json',state)
        except BaseException as exc:
            if CHILD and CHILD.poll() is None:
                os.killpg(CHILD.pid,signal.SIGINT)
                try:CHILD.wait(timeout=30)
                except subprocess.TimeoutExpired:os.killpg(CHILD.pid,signal.SIGTERM)
            state.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed',
                         stopped_utc=now(),error=str(exc))
            atomic_json(CONTROL/'queue_state.json',state)
            append_jsonl(CONTROL/'queue_events.jsonl',dict(event=state['status'],phase=state.get('current_phase'),utc=now(),error=str(exc)))
            raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',action='store_true')
    args=parser.parse_args()
    if args.preflight:
        no_competing_runner()
        server=configure_server()
        print(json.dumps(server,indent=2))
    else:run_queue()
