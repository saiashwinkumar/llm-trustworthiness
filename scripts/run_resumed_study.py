"""Provenance-preserving continuation: prepare/status are offline; phases resume by ID."""
import argparse
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiment import digest, read_jsonl
from choice_trust.model import prompt, parse_explanation, PROMPT_VERSION, RemoteBackend
from choice_trust.citations import CITATION_POLICY_VERSION
from choice_trust.runner import selection
from choice_trust.interventions import explanation_tests, apply, measurements
from choice_trust.schema import visible_evidence, validate_cases
from choice_trust.scoring import validate_prediction
from choice_trust.storage import load_run, init_run, append, writer_lock, atomic_json, code_hash
from scripts.run_cpu_real_v2 import sha, phase_lock, summarize, print_status, run_stage, report, checkpoint
from scripts.verify_cpu_server import validate_health

SOURCE_RUNS = ['outputs_cpu_real_v3', 'outputs_cpu_real_v3_smoke',
               'outputs_cpu_real_v2_smoke', 'outputs_development_check_v1']


def source_data():
    sources = {}
    hashes = {}
    for name in SOURCE_RUNS:
        path = ROOT/name
        if not (path/'run_manifest.json').exists():
            if name == 'outputs_development_check_v1':
                raise ValueError('Complete the bounded development check before preparing continuation')
            continue
        sources[name] = load_run(path, repair=False)
        for filename in ('run_manifest.json', 'cases.jsonl', 'predictions.jsonl', 'explanations.jsonl', 'interventions.jsonl'):
            p = path/filename
            if p.exists(): hashes[str(p.relative_to(ROOT))] = sha(p)
    check = ROOT/'outputs_development_check_v1/execution_check.json'
    if not check.exists() or not json.loads(check.read_text()).get('completed'):
        raise ValueError('Development execution check has not completed')
    hashes[str(check.relative_to(ROOT))] = sha(check)
    return sources, hashes


def compatible_prediction(p, case, backend):
    return (p.get('case_hash') == digest(case) and p.get('prompt') == prompt(case, p['condition'])
        and p.get('score_method') == 'candidate_sequence_conditional_likelihood_v2'
        and p.get('raw', {}).get('model_id') == backend['model_id']
        and p.get('raw', {}).get('revision') == backend['revision'])


def select_sources(cases, sources):
    index = {c['case_id']: c for c in cases}
    backend = sources['outputs_cpu_real_v3'][0]['backend']
    predictions, explanations, effects = {}, {}, []
    for name in SOURCE_RUNS:
        if name not in sources: continue
        manifest, _, data = sources[name]
        if manifest['cases_hash'] != digest(cases) or manifest['backend'] != backend:
            raise ValueError('Source dataset/backend differs: ' + name)
        for p in data['predictions']:
            if not compatible_prediction(p, index[p['case_id']], backend):
                raise ValueError('Prediction prompt/scoring/evidence mismatch: ' + name + '/' + p['case_id'])
            key = p['case_id'], p['condition']
            if key in predictions and predictions[key][1]['scores'] != p['scores']:
                raise ValueError('Conflicting repeated prediction scores; review before selecting a source')
            predictions.setdefault(key, (name, p))
        # Priority is formal, latest smoke, prior smoke, then development check.
        for e in data['explanations']:
            explanations.setdefault((e['case_id'], e['condition']), (name, e))
    for name in SOURCE_RUNS:
        if name not in sources: continue
        _, _, data = sources[name]
        for row in data['interventions']:
            key = row['case_id'], row['condition']
            chosen = explanations.get(key)
            if (row['status'] == 'measured' and chosen and chosen[0] == name
                    and row['explanation_hash'] == chosen[1]['record_hash']):
                p = predictions[key][1]
                if row['before']['scores'] != p['scores'] or row['before']['prompt'] != p['prompt']:
                    raise ValueError('Measurement baseline differs from selected prediction')
                effects.append((name, row))
    return predictions, explanations, effects, backend


def origin(name, kind, row, sources):
    return dict(source_file=name+'/'+kind+'.jsonl', source_record_hash=row['record_hash'],
                source_run_id=row['run_id'], source_prompt_version=sources[name][0]['prompt_version'],
                source_settings=sources[name][0]['settings'])


def prepare(args, cases):
    sources, hashes = source_data()
    predictions, explanations, effects, backend = select_sources(cases, sources)
    old_path = ROOT/'execution_cpu_real_v3/study_plan.json'
    plan = json.loads(old_path.read_text())
    plan.update(study_version='resumed-study-v1', role='formal_follow_up',
        prompt_version=PROMPT_VERSION, citation_policy_version=CITATION_POLICY_VERSION,
        parent_plan=str(old_path.relative_to(ROOT)), parent_plan_sha256=sha(old_path),
        source_sha256=hashes, interpretation=(
            'Exploratory follow-up. Exact-compatible predictions and measurements are reused with source hashes. '
            'Historical and new explanation prompt cohorts remain identifiable; legacy pilot and notebook predictions are separate.'),
        source_selection='Formal predictions first; explanations: v3 smoke before v2 smoke. Preserve all other attempts in their original folders.',
        excluded_prediction_cohorts={
            'outputs_cpu_pilot': 'Different prediction prompt; 20 test predictions per condition remain separate, not subtracted from 804.',
            'outputs_cpu_smoke': 'Different prediction prompt.',
            'choice_study': 'Different prompt, support/query allocation and local inference implementation; not interchangeable.'})
    development = dict(name='development_predictions', phase='development', command='predict', split='development',
        limit=0, suite='all', conditions=plan['conditions'],
        case_ids=[c['case_id'] for c in selection(cases, 'development', 0, 42)])
    plan['stages'].insert(0, development)
    plan['integrity'] = dict(cases_hash=digest(cases), cases_file_sha256=sha(args.cases),
        dataset_manifest_sha256=sha(args.cases.with_name('manifest.json')), framework_code_hash=code_hash(),
        resumed_runner_sha256=sha(__file__), phase_runner_sha256=sha(ROOT/'scripts/run_cpu_real_v2.py'),
        shared_helpers_sha256=sha(ROOT/'experiment.py'))
    # Recover the source smoke protocol (one control, one permutation); its matching
    # measurements also satisfy the corresponding formal five-control tasks.
    index = {c['case_id']: c for c in cases}
    recovery = []
    for key, (name, e) in explanations.items():
        if name != 'outputs_cpu_real_v3_smoke': continue
        if e.get('parse_error') != 'Expected 0–3 unique string evidence IDs': continue
        new = dict(e, **parse_explanation(e['raw'], visible_evidence(index[key[0]], key[1])))
        if not new['usable_for_evidence_interventions']: continue
        for spec in explanation_tests(index[key[0]], key[1], new, 1, 42):
            if spec['kind'] not in ('cited_remove', 'cited_retain', 'random_remove', 'random_retain'): continue
            recovery.append(dict(case_id=key[0], condition=key[1], spec=spec,
                source_explanation_hash=e['record_hash'], source_run=name,
                reason='Previously blocked solely by the three-citation limit'))
    plan['citation_recovery_tasks'] = recovery
    plan['development_explanation_scope'] = dict(case_ids=[selection(cases,'development',1,42)[0]['case_id']],
        conditions=plan['conditions'], purpose='Execution check only, not all development occasions')
    args.control.mkdir(parents=True, exist_ok=True)
    plan_path = args.control/'study_plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('Prepared plan changed; preserve the existing plan and use fresh directories')
    atomic_json(plan_path, plan)
    settings = dict(seed=42, random_controls=5, permutations=2, conditions=plan['conditions'], intervention_grid='adapter-predefined-v2')
    with writer_lock(args.out):
        run_id = init_run(args.out, cases, json.loads(args.cases.with_name('manifest.json').read_text()),
                          SimpleNamespace(metadata=backend), settings, plan)
        _, _, existing = load_run(args.out)
        saved = {kind:{r['record_id']:r for r in rows} for kind,rows in existing.items()}
        for key, (name, p) in predictions.items():
            if p['record_id'] in saved['predictions']: continue
            row = dict(p, run_id=run_id, reuse_origin=origin(name,'predictions',p,sources), original_record=p)
            row.pop('record_hash')
            saved['predictions'][p['record_id']] = append(args.out/'predictions.jsonl', row)
        for key, (name, e) in explanations.items():
            if e['record_id'] in saved['explanations']: continue
            p = saved['predictions'][e['prediction_id']]
            row = dict(e, **parse_explanation(e['raw'],visible_evidence(index[key[0]],key[1])))
            row.update(run_id=run_id, prediction_hash=p['record_hash'],
                reuse_origin=origin(name,'explanations',e,sources), original_record=e,
                prompt_version=sources[name][0]['prompt_version'])
            row.pop('record_hash')
            saved['explanations'][e['record_id']] = append(args.out/'explanations.jsonl', row)
        for name, effect in effects:
            if effect['record_id'] in saved['interventions']: continue
            p=saved['predictions'][effect['prediction_id']]
            e=saved['explanations'][effect['explanation_id']]
            row=dict(effect, run_id=run_id, prediction_hash=p['record_hash'], explanation_hash=e['record_hash'],
                before=p, reuse_origin=origin(name,'interventions',effect,sources), original_record=effect)
            row.pop('record_hash')
            saved['interventions'][effect['record_id']]=append(args.out/'interventions.jsonl',row)
    load_run(args.out)
    return plan


def verify_plan(args, cases):
    plan=json.loads((args.control/'study_plan.json').read_text())
    checks=dict(cases_hash=digest(cases), cases_file_sha256=sha(args.cases),
        dataset_manifest_sha256=sha(args.cases.with_name('manifest.json')), framework_code_hash=code_hash(),
        resumed_runner_sha256=sha(__file__), phase_runner_sha256=sha(ROOT/'scripts/run_cpu_real_v2.py'),
        shared_helpers_sha256=sha(ROOT/'experiment.py'))
    if checks != plan['integrity']: raise ValueError('Frozen code/data changed; preserve this run')
    for path, expected in plan['source_sha256'].items():
        if sha(ROOT/path) != expected: raise ValueError('Original source changed: '+path)
    if sha(ROOT/plan['parent_plan']) != plan['parent_plan_sha256']: raise ValueError('Parent plan changed')
    return plan


def recovery_status(args, plan):
    _, _, data=load_run(args.out)
    preds={(p['case_id'],p['condition']):p for p in data['predictions']}
    measured={r['record_id'] for r in data['interventions'] if r['status']=='measured'}
    return dict(planned=len(plan['citation_recovery_tasks']), measured=sum(
        digest([preds[t['case_id'],t['condition']]['record_id'],t['spec']]) in measured for t in plan['citation_recovery_tasks']))


def recover(args, cases, plan):
    backend=RemoteBackend(); validate_health(backend.health)
    with writer_lock(args.out):
        manifest,_,data=load_run(args.out)
        if backend.metadata!=manifest['backend']: raise ValueError('Server inference metadata changed')
        index={c['case_id']:c for c in cases}
        preds={(r['case_id'],r['condition']):r for r in data['predictions']}
        exps={(r['case_id'],r['condition']):r for r in data['explanations']}
        existing={r['record_id'] for r in data['interventions']}
        for task in plan['citation_recovery_tasks']:
            key=task['case_id'],task['condition']; c=index[key[0]];p=preds[key];e=exps[key];spec=task['spec']
            iid=digest([p['record_id'],spec])
            if iid in existing: continue
            changed,reason=apply(c,spec)
            if reason: raise ValueError('Recovery edit no longer admissible: '+reason)
            result=backend.predict(changed,key[1]);validate_prediction(result,[x['id'] for x in c['candidates']])
            row=dict(case_id=key[0],condition=key[1],split=c['split'],group_id=c['group_id'],dataset_id=c['dataset_id'],
                run_id=digest(manifest),synthetic=False,record_id=iid,prediction_id=p['record_id'],prediction_hash=p['record_hash'],
                explanation_id=e['record_id'],explanation_hash=e['record_hash'],spec=spec,status='measured',skip_reason=None,
                before=p,after=result,original_evidence=list(visible_evidence(c,key[1]).values()),
                edited_evidence=list(visible_evidence(changed,key[1]).values()),edited_outcome=None,
                **measurements(p,result),was_cited=bool(set(spec['evidence_ids'])&set(e['parsed']['evidence_ids'])),
                claim_applicable=False,claim_agreement=None,recovery_source=task)
            append(args.out/'interventions.jsonl',row);existing.add(iid)
            print('Saved recovered measurement:',key,spec['kind'],flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','status','development','validation','recovery','freeze','test','report'])
    parser.add_argument('--out',type=Path,default=ROOT/'outputs_resumed_v1')
    parser.add_argument('--control',type=Path,default=ROOT/'execution_resumed_v1')
    parser.add_argument('--timeout',type=int,default=900)
    parser.add_argument('--bootstrap',type=int,default=500)
    parser.add_argument('--ack-validation-review',action='store_true')
    args=parser.parse_args();args.out=args.out.resolve();args.control=args.control.resolve();args.mock=False
    args.cases=ROOT/'data_v2/yogurt/cases.jsonl'
    cases=validate_cases(read_jsonl(args.cases));args.case_rows=cases
    if args.out==args.control or args.out.is_relative_to(args.control) or args.control.is_relative_to(args.out):
        raise ValueError('Use separate output and control folders')
    if args.phase=='status':
        plan=verify_plan(args,cases);print_status(summarize(args.out,cases,plan,args.control))
        print('Citation recovery:',recovery_status(args,plan));return
    with phase_lock(args.control):
        plan=prepare(args,cases) if args.phase=='prepare' else verify_plan(args,cases)
        plan_path=args.control/'study_plan.json'
        if args.phase=='recovery': recover(args,cases,plan)
        if args.phase=='freeze':
            summary=summarize(args.out,cases,plan,args.control)
            if any(r['missing'] for r in summary['rows'] if r['phase']=='validation'):
                raise ValueError('Validation calls/recorded skips are not yet accounted for')
            if not args.ack_validation_review: raise ValueError('Review recorded outcomes, then use --ack-validation-review')
            atomic_json(args.control/'protocol_frozen.json',dict(integrity=checkpoint(args.out,cases,plan,plan_path),
                criterion='Calls accounted for, including poor responses; no favorable-result threshold'))
        if args.phase=='test':
            frozen=args.control/'protocol_frozen.json'
            if not frozen.exists() or json.loads(frozen.read_text())['integrity']!=checkpoint(args.out,cases,plan,plan_path):
                raise ValueError('Complete validation and freeze before test')
        if args.phase in ('development','validation','test'):
            backend=RemoteBackend();validate_health(backend.health)
            if backend.metadata!=load_run(args.out)[0]['backend']: raise ValueError('Server settings changed')
            for stage in plan['stages']:
                if stage['phase']==args.phase:
                    if [c['case_id'] for c in selection(cases,stage['split'],stage['limit'],42)]!=stage['case_ids']:
                        raise ValueError('Selected cases differ from saved plan')
                    run_stage(stage,args,args.out,plan,plan_path)
        report(args.out,cases,plan,args.control,args.bootstrap)
        atomic_json(args.control/'recovery_status.json',recovery_status(args,plan))


if __name__=='__main__':
    try: main()
    except (ValueError,OSError,RuntimeError) as exc: raise SystemExit(str(exc))
