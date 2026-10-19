"""Manual, resumable CPU study. Historical filename; NEW v4 output defaults.

Run smoke, validation, freeze --ack-validation-review, test, then report.
Status is read-only. No AWS resources are provisioned or managed here.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiment import append_jsonl, digest, read_jsonl
from choice_trust.runner import selection
from choice_trust.schema import validate_cases
from choice_trust.storage import atomic_json, code_hash, load_run, output_snapshot
from choice_trust.interventions import planned_specs
from choice_trust.citations import response_issues, CITATION_POLICY_VERSION
from collections import Counter

MODEL = 'Qwen/Qwen3-1.7B'
REVISION = '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e'
CONDITIONS = ['no_history', 'with_history']
DEFAULT_CASES = ROOT / 'data_v2/yogurt/cases.jsonl'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stage_definitions():
    stages = []
    for phase, split, limit in [('validation', 'validation', 20), ('test', 'test', 100)]:
        for suffix, command, n, suite in [('predictions', 'predict', 0, 'all'), ('explanations', 'explain', limit, 'all'), ('explanation_tests', 'counterfactuals', limit, 'explanation')]:
            stages.append(dict(name=phase+'_'+suffix, phase=phase, command=command, split=split, limit=n, suite=suite, conditions=CONDITIONS))
    stages.append(dict(name='test_systematic_with_history', phase='test', command='counterfactuals', split='test', limit=30, suite='systematic', conditions=['with_history']))
    return stages


def make_plan(cases, cases_path, mock=False, smoke_limit=None):
    from choice_trust.model import PROMPT_VERSION
    stages = stage_definitions()
    if smoke_limit is not None:
        stages = [dict(name='smoke_'+c, phase='smoke', command=c, split='validation', limit=smoke_limit, suite='explanation', conditions=CONDITIONS) for c in ('predict','explain','counterfactuals')]
    for stage in stages:
        stage['case_ids'] = [c['case_id'] for c in selection(cases, stage['split'], stage['limit'], 42)]
        if not stage['case_ids']:
            raise ValueError('No cases available for '+stage['name'])
    return dict(schema_version=2, study_version='cpu-follow-up-v4', role='validation_smoke' if smoke_limit is not None else 'formal_follow_up',
        label='SYNTHETIC SOFTWARE CHECK' if mock else 'NEW REAL-MODEL EXPLORATORY FOLLOW-UP',
        interpretation=('SYNTHETIC SOFTWARE CHECK; never report these as LLM findings.' if mock else 'Prior pilot test results have already been inspected. This is an exploratory follow-up, not an untouched confirmatory test. Legacy and synthetic records are not pooled.'),
        seed=42, conditions=CONDITIONS, random_controls=1 if smoke_limit is not None else 5, permutations=1 if smoke_limit is not None else 2,
        synthetic=mock, expected_backend=({'backend':'mock_NOT_LLM_RESULTS'} if mock else dict(model_id=MODEL, revision=REVISION, device='cpu', dtype='torch.float32')),
        prompt_version=PROMPT_VERSION, citation_policy_version=CITATION_POLICY_VERSION, stages=stages,
        manual_review_cases_per_condition=0 if smoke_limit is not None else 20,
        manual_review_case_ids=[] if smoke_limit is not None else [c['case_id'] for c in selection(cases,'test',20,42)],
        integrity=dict(cases_hash=digest(cases), cases_file_sha256=sha(cases_path), dataset_manifest_sha256=sha(Path(cases_path).with_name('manifest.json')),
            framework_code_hash=code_hash(), orchestrator_sha256=sha(__file__), shared_helpers_sha256=sha(ROOT/'experiment.py')))


def ensure_plan(path, expected, write=True):
    if path.exists():
        if json.loads(path.read_text()) != expected:
            raise ValueError(f'Plan/data/code changed: {path}. Keep the old run intact and choose NEW --out and --control directories.')
    elif write:
        atomic_json(path, expected)
    return expected


@contextmanager
def phase_lock(control):
    control.mkdir(parents=True, exist_ok=True)
    with (control/'.orchestrator.lock').open('a+') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another study phase is running. Use status; do not start a second writer.') from None
        handle.seek(0); handle.truncate(); handle.write(str(os.getpid())); handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def verify_server():
    from choice_trust.model import RemoteBackend
    from scripts.verify_cpu_server import validate_health
    backend=RemoteBackend(); validate_health(backend.health)
    print('PASS: pinned CPU server, saved settings, upgraded capabilities and server source hashes.', flush=True)


def read_snapshot(out, cases, plan):
    if not (out/'run_manifest.json').exists():
        return None, dict(predictions=[], explanations=[], interventions=[])
    for attempt in range(3):
        try:
            manifest,saved,data=load_run(out, repair=False)
            break
        except ValueError as exc:
            if 'Invalid JSON' not in str(exc) or attempt==2:
                raise
            time.sleep(.1)
    if digest(saved)!=digest(cases) or manifest.get('study_plan')!=plan:
        raise ValueError('Output folder belongs to a different dataset/plan. Choose a fresh output folder.')
    return manifest,data


def audit_state(out, data, plan):
    wanted={(cid,cond) for cid in plan['manual_review_case_ids'] for cond in CONDITIONS}
    hashes={e['record_hash']:(e['case_id'],e['condition']) for e in data['explanations'] if e['split']=='test' and (e['case_id'],e['condition']) in wanted}
    reviewed=set(); errors=[]; seen=set(); path=out/'manual_audit.csv'
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                h=row.get('explanation_hash')
                if h not in hashes:
                    continue
                if h in seen:
                    errors.append('Duplicate audit row: '+row.get('case_id','unknown')); continue
                seen.add(h)
                a=str(row.get('supported_claims','')).strip(); b=str(row.get('total_factual_claims','')).strip()
                if not a and not b:
                    continue
                try:
                    if not a or not b or not 0<=int(a)<=int(b):
                        raise ValueError()
                except ValueError:
                    errors.append('Invalid or partial claim counts: '+row.get('case_id','unknown')); continue
                reviewed.add(hashes[h])
    return dict(planned=len(wanted), available_explanations=len(hashes), reviewed=len(reviewed), missing=len(wanted)-len(reviewed), invalid_reviews=errors,
        complete=bool(wanted) and len(reviewed)==len(wanted) and not errors,
        note='Preselected test explanations only; blanks are unreviewed. Count completion does not certify reviewer accuracy.')


def summarize(out, cases, plan, control=None):
    _,data=read_snapshot(out,cases,plan)
    preds={(r['case_id'],r['condition']):r for r in data['predictions']}
    exps={(r['case_id'],r['condition']):r for r in data['explanations']}
    interventions={r['record_id']:r for r in data['interventions']}; index={c['case_id']:c for c in cases}; rows=[]
    for stage in plan['stages']:
        for condition in stage['conditions']:
            completed=invalid=abstained=truncated=measured=skipped=known=recorded=pending=0; unresolved=[]; issues=Counter()
            for cid in stage['case_ids']:
                key=(cid,condition)
                if stage['command'] in ('predict','explain'):
                    row=(preds if stage['command']=='predict' else exps).get(key)
                    if row:
                        completed+=1
                        if stage['command']=='explain':
                            issues.update(response_issues(row))
                            invalid+=int(not row['parse_ok'] or not row['citation_valid']); abstained+=int(row['abstained']); truncated+=int(row.get('truncated',False))
                    else:
                        unresolved.append(cid)
                    continue
                p=preds.get(key); e=exps.get(key)
                if p is None or e is None:
                    pending+=1; unresolved.append(cid); continue
                specs=planned_specs(index[cid],condition,e,plan['random_controls'],plan['seed'],plan['permutations'],stage['suite'])
                known+=len(specs)
                found=[interventions.get(digest([p['record_id'],spec])) for spec in specs]; present=[r for r in found if r is not None]
                recorded+=len(present); measured+=sum(r['status']=='measured' for r in present); skipped+=sum(r['status']=='skipped' for r in present)
                if len(present)==len(specs):
                    completed+=1
                else:
                    unresolved.append(cid)
            intervention=stage['command']=='counterfactuals'
            rows.append(dict(stage=stage['name'], phase=stage['phase'], condition=condition, planned=len(stage['case_ids']), completed=completed, missing=len(stage['case_ids'])-completed,
                invalid=invalid,assessment_issues=dict(issues),abstained=abstained,truncated=truncated,
                planned_measurements=(None if pending else known) if intervention else None, known_planned_measurements=known if intervention else None,
                recorded_measurements=recorded if intervention else None, missing_measurements=(None if pending else known-recorded) if intervention else None,
                prerequisite_missing_cases=pending, measured=measured if intervention else None, skipped=skipped, unresolved_case_ids=unresolved))
    automated=all(r['missing']==0 for r in rows); audit=audit_state(out,data,plan); failures=[]
    if control and (control/'stage_events.jsonl').exists():
        try:
            failures=[r for r in read_jsonl(control/'stage_events.jsonl') if r.get('event') in ('failed','interrupted') and r.get('role')==plan['role']]
        except ValueError:
            pass
    return dict(updated_utc=now(),label=plan['label'],role=plan['role'],rows=rows,failed_stage_attempts=len(failures),failure_events=failures,
        record_snapshot=output_snapshot(out,data),study_plan_hash=digest(plan),
        automated_execution_complete=automated,manual_grounding=audit,full_study_complete=automated and audit['complete'],dashboard=str(out/'dashboard.html'),
        note='Complete means planned attempts are accounted for, including explicit skips and responses with recorded issues. It does not mean explanations passed. Shared presentation rows are deduplicated; do not sum overlapping suite counts. Undetermined intervention totals are null, not zero.')


def write_summary(out, summary):
    if not (out/'run_manifest.json').exists():
        return
    atomic_json(out/'execution_summary.json',summary)
    fields=['stage','condition','planned','completed','missing','invalid','truncated','measured','skipped','missing_measurements','prerequisite_missing_cases']
    with (out/'completeness.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields,extrasaction='ignore'); writer.writeheader(); writer.writerows(summary['rows'])
    lines=['# CPU study completeness','',summary['label'],'','| Stage | Condition | Planned cases | Completed attempts | Missing | Assessment issues | Skipped measurements |','|---|---|---:|---:|---:|---:|---:|']
    for r in summary['rows']:
        lines.append(f"| {r['stage']} | {r['condition']} | {r['planned']} | {r['completed']} | {r['missing']} | {r['assessment_issues']} | {r['skipped']} |")
    a=summary['manual_grounding']
    lines+=['',f"Automated execution complete: {summary['automated_execution_complete']}",f"Manual grounding: {a['reviewed']}/{a['planned']} preselected test explanations reviewed.",f"Full study including planned review complete: {summary['full_study_complete']}",'',summary['note']]
    (out/'completeness.md').write_text('\n'.join(lines)+'\n')


def review_sample(out, data, plan):
    main=out/'manual_audit.csv'; sample=out/'manual_review_sample.csv'
    if not main.exists() or not plan['manual_review_case_ids']:
        return
    with main.open(newline='',encoding='utf-8-sig') as handle:
        reader=csv.DictReader(handle); fields=reader.fieldnames; rows=list(reader)
    eligible={e['record_hash'] for e in data['explanations'] if e['split']=='test' and e['case_id'] in plan['manual_review_case_ids'] and e['condition'] in CONDITIONS}
    by_hash={r['explanation_hash']:r for r in rows}; changed=False; seen=set()
    if sample.exists():
        with sample.open(newline='',encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                h=row.get('explanation_hash')
                if h not in eligible or h not in by_hash or h in seen:
                    raise ValueError('Review sample has a stale, duplicate or unplanned explanation hash; keep original source rows.')
                seen.add(h)
                a=str(row.get('supported_claims','')).strip(); b=str(row.get('total_factual_claims','')).strip()
                if not a and not b:
                    continue
                try:
                    if not a or not b or not 0<=int(a)<=int(b):
                        raise ValueError()
                except ValueError:
                    raise ValueError('Complete both review counts with valid integers for '+row.get('case_id','unknown')) from None
                target=by_hash[h]; existing=(str(target.get('supported_claims','')).strip(),str(target.get('total_factual_claims','')).strip())
                if existing!=('','') and existing!=(a,b):
                    raise ValueError('Conflicting completed review in main audit and sample for '+row['case_id'])
                target.update(supported_claims=a,total_factual_claims=b,reviewer_notes=row.get('reviewer_notes','')); changed=True
    def write_csv(path,values):
        tmp=path.with_suffix('.csv.tmp')
        with tmp.open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader(); writer.writerows(values)
        tmp.replace(path)
    if changed:
        write_csv(main,rows)
    write_csv(sample,[r for r in rows if r['explanation_hash'] in eligible])


def print_status(summary):
    print('\n'+summary['label'],flush=True)
    for r in summary['rows']:
        extra=f"; assessment issues={r['assessment_issues']}" if 'explanations' in r['stage'] else ''
        print(f"{r['stage']} / {r['condition']}: {r['completed']}/{r['planned']} accounted for; missing={r['missing']}{extra}",flush=True)
    print(f"Automated complete: {summary['automated_execution_complete']}; manual review: {summary['manual_grounding']['reviewed']}/{summary['manual_grounding']['planned']}; full study complete: {summary['full_study_complete']}",flush=True)


def run_stage(stage,args,out,plan,plan_path):
    cmd=[sys.executable,'-u','-m','choice_trust',stage['command'],'--cases',str(args.cases),'--out',str(out),'--split',stage['split'],'--limit',str(stage['limit']),
         '--conditions',*CONDITIONS,'--only-conditions',*stage['conditions'],'--random-controls',str(plan['random_controls']),'--permutations',str(plan['permutations']),
         '--seed',str(plan['seed']),'--suite',stage['suite'],'--plan',str(plan_path)]
    if args.mock:
        cmd.append('--mock')
    log=args.control/(stage['name']+'-'+str(time.time_ns())+'.log')
    event=dict(stage=stage['name'],role=plan['role'],utc=now(),command=cmd,log=str(log))
    append_jsonl(args.control/'stage_events.jsonl',dict(event,event='start'))
    print(f"\n{now()} START {stage['name']} — log: {log}",flush=True); process=None
    try:
        with log.open('w',encoding='utf-8') as handle:
            process=subprocess.Popen(cmd,cwd=ROOT,env=dict(os.environ,MODEL_TIMEOUT_SECONDS=str(args.timeout),PYTHONUNBUFFERED='1'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
            for line in process.stdout:
                handle.write(line); handle.flush(); print(line,end='',flush=True)
            result=process.wait()
    except KeyboardInterrupt:
        if process and process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
        append_jsonl(args.control/'stage_events.jsonl',dict(event,event='interrupted',ended_utc=now()))
        raise
    if result:
        append_jsonl(args.control/'stage_events.jsonl',dict(event,event='failed',returncode=result,ended_utc=now()))
        raise ValueError(f"Stage {stage['name']} stopped (exit {result}). Check {log}. Restore server/tunnel if needed; repeat the SAME phase to resume.")
    summary=summarize(out,args.case_rows,plan,args.control)
    relevant=[r for r in summary['rows'] if r['stage']==stage['name']]
    if not relevant or any(r['missing'] for r in relevant):
        append_jsonl(args.control/'stage_events.jsonl',dict(event,event='failed',returncode=0,reason='Saved coverage does not meet plan',ended_utc=now()))
        raise ValueError('Command exited but saved stage coverage is incomplete: '+stage['name'])
    append_jsonl(args.control/'stage_events.jsonl',dict(event,event='complete',returncode=0,ended_utc=now()))
    write_summary(out,summary)


def checkpoint(out,cases,plan,plan_path):
    manifest,_=read_snapshot(out,cases,plan)
    if not manifest:
        raise ValueError('No formal run exists yet')
    return dict(run_manifest_hash=digest(manifest),plan_hash=sha(plan_path),framework_code_hash=code_hash(),orchestrator_sha256=sha(__file__),
                cases_hash=digest(cases),shared_helpers_sha256=sha(ROOT/'experiment.py'))


def report(out,cases,plan,control,bootstrap):
    _,data=read_snapshot(out,cases,plan); review_sample(out,data,plan)
    summary=summarize(out,cases,plan,control); write_summary(out,summary)
    subprocess.run([sys.executable,'-u','-m','choice_trust','dashboard','--out',str(out),'--bootstrap',str(bootstrap)],cwd=ROOT,check=True)
    print_status(summary); print('Dashboard: '+str(out/'dashboard.html'),flush=True)
    return summary


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['smoke','validation','freeze','test','report','status'])
    parser.add_argument('--out',type=Path,default=ROOT/'outputs_cpu_real_v4')
    parser.add_argument('--control',type=Path,default=ROOT/'execution_cpu_real_v4')
    parser.add_argument('--cases',type=Path,default=DEFAULT_CASES)
    parser.add_argument('--smoke-limit',type=int,default=2)
    parser.add_argument('--timeout',type=int,default=900)
    parser.add_argument('--bootstrap',type=int,default=500)
    parser.add_argument('--ack-validation-review',action='store_true')
    parser.add_argument('--review-note',default='Validation parsing, citations and coverage inspected; failures retained as outcomes.')
    parser.add_argument('--mock',action='store_true',help='Synthetic software check only; refuses real cases.')
    args=parser.parse_args(argv)
    if min(args.smoke_limit,args.timeout,args.bootstrap)<1:
        parser.error('Smoke limit, timeout and bootstrap must be positive')
    args.cases=args.cases.resolve(); args.out=args.out.resolve(); args.control=args.control.resolve()
    if args.control==args.out or args.control.is_relative_to(args.out) or args.out.is_relative_to(args.control):
        parser.error('Output and control folders must be separate, non-nested directories')
    return args


def main(argv=None):
    args=parse_args(argv); cases=validate_cases(read_jsonl(args.cases)); args.case_rows=cases
    if not cases:
        raise ValueError('No prepared cases')
    if args.mock and not all(c.get('synthetic') for c in cases):
        raise ValueError('--mock refuses real data')
    if not args.mock and any(c.get('synthetic') for c in cases):
        raise ValueError('Use --mock for synthetic fixtures; real study requires real cases')
    dataset=json.loads(args.cases.with_name('manifest.json').read_text())
    if dataset['cases_hash']!=digest(cases):
        raise ValueError('Prepared dataset and manifest disagree')
    if not args.mock and args.cases==DEFAULT_CASES.resolve():
        counts={s:sum(c['split']==s for c in cases) for s in ('validation','test')}
        if counts!={'validation':306,'test':804}:
            raise ValueError('Default yogurt case counts changed; review the data/protocol first')
    smoke=args.phase=='smoke'; out=args.out.with_name(args.out.name+'_smoke') if smoke else args.out
    path=args.control/('smoke_study_plan.json' if smoke else 'study_plan.json')
    plan=make_plan(cases,args.cases,args.mock,args.smoke_limit if smoke else None)
    if args.phase=='status':
        ensure_plan(path,plan,write=False); print_status(summarize(out,cases,plan,args.control)); return
    with phase_lock(args.control):
        ensure_plan(path,plan)
        if args.phase in ('smoke','validation','test') and not args.mock:
            verify_server()
        if args.phase=='test':
            frozen=args.control/'protocol_frozen.json'
            if not frozen.exists():
                raise ValueError('Run validation, inspect results, then freeze --ack-validation-review before test')
            if json.loads(frozen.read_text())['integrity']!=checkpoint(out,cases,plan,path):
                raise ValueError('Frozen data/model/code/plan changed. Test refused; preserve this run and use fresh folders.')
        if args.phase=='freeze':
            summary=summarize(out,cases,plan,args.control)
            if any(r['missing'] for r in summary['rows'] if r['phase']=='validation'):
                raise ValueError('Validation stages are incomplete')
            if not args.ack_validation_review:
                raise ValueError('Inspect validation invalid/abstention/truncation counts, then repeat freeze with --ack-validation-review')
            value=dict(frozen_utc=now(),integrity=checkpoint(out,cases,plan,path),review_note=args.review_note)
            frozen=args.control/'protocol_frozen.json'
            if frozen.exists():
                if json.loads(frozen.read_text())['integrity']!=value['integrity']:
                    raise ValueError('An incompatible freeze checkpoint exists')
            else:
                atomic_json(frozen,value)
            print('Protocol frozen. Responses with recorded issues remain in the data.',flush=True)
        elif args.phase in ('smoke','validation','test'):
            for stage in plan['stages']:
                if stage['phase']==args.phase:
                    actual=[c['case_id'] for c in selection(cases,stage['split'],stage['limit'],plan['seed'])]
                    if actual!=stage['case_ids']:
                        raise ValueError('Stage selection differs from the frozen plan')
                    run_stage(stage,args,out,plan,path)
        report(out,cases,plan,args.control,args.bootstrap)


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('Interrupted. Saved records retained; repeat the same phase to resume.')
    except (ValueError,OSError,RuntimeError,subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
