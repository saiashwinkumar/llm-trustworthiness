"""Stages save original predictions before explanations, then fresh interventions."""
import csv
import json
from pathlib import Path
from experiment import digest, read_jsonl
from .schema import validate_cases, visible_evidence
from .model import MockBackend, RemoteBackend, parse_explanation, explanation_prompt, PROMPT_VERSION
from .storage import init_run, load_run, append, writer_lock, atomic_json
from .interventions import systematic, explanation_tests, apply, measurements, planned_specs
from .scoring import answer_labels, validate_prediction


def selection(cases,split,limit,seed):
    rows=sorted((c for c in cases if split=='all' or c['split']==split),key=lambda c:digest([seed,c['case_id']]))
    return rows[:limit] if limit else rows


def export_audit(out,data,cases):
    path=out/'manual_audit.csv'; old={}
    if path.exists():
        with path.open(newline='',encoding='utf-8-sig') as f: old={r['explanation_hash']:r for r in csv.DictReader(f)}
    fields=['case_id','condition','explanation_hash','correct','provided_evidence','explanation','supported_claims','total_factual_claims','reviewer_notes']
    predictions={r['record_id']:r for r in data['predictions']}
    index={c['case_id']:c for c in cases}
    tmp=path.with_suffix('.csv.tmp')
    with tmp.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        for e in data['explanations']:
            p=predictions[e['prediction_id']]; c=index[e['case_id']]
            row=dict(case_id=e['case_id'],condition=e['condition'],explanation_hash=e['record_hash'],
                     correct=p['correct'],provided_evidence=json.dumps(visible_evidence(c,e['condition']),ensure_ascii=False),
                     explanation=e['raw'].get('text',''),supported_claims='',total_factual_claims='',reviewer_notes='')
            for key in ('supported_claims','total_factual_claims','reviewer_notes'): row[key]=old.get(e['record_hash'],{}).get(key,'')
            # Prevent spreadsheet formula evaluation when audit templates are opened.
            for key,value in row.items():
                if isinstance(value,str) and value.startswith(('=','+','-','@','\t','\r')): row[key]="'"+value
            writer.writerow(row)
    tmp.replace(path)


def run(args):
    cases=validate_cases(read_jsonl(args.cases))
    if not cases: raise ValueError('No prepared cases')
    if args.mock and not all(c.get('synthetic') for c in cases): raise ValueError('Mock refuses real data')
    dataset_manifest=json.loads(args.cases.with_name('manifest.json').read_text())
    if dataset_manifest['cases_hash']!=digest(cases): raise ValueError('Prepared cases changed since preparation')
    execution_conditions=getattr(args,'only_conditions',None) or args.conditions
    if not set(execution_conditions)<=set(args.conditions):
        raise ValueError('--only-conditions must be a subset of the fixed --conditions protocol')
    plan_path=getattr(args,'plan',None)
    study_plan=json.loads(plan_path.read_text()) if plan_path else None
    backend=MockBackend() if args.mock else RemoteBackend()
    settings=dict(seed=args.seed,random_controls=args.random_controls,permutations=args.permutations,
                  conditions=sorted(args.conditions),intervention_grid='adapter-predefined-v2')
    with writer_lock(args.out):
        run_id=init_run(args.out,cases,dataset_manifest,backend,settings,study_plan)
        manifest,_,data=load_run(args.out,repair=True)
        existing={name:{r['record_id']:r for r in rows} for name,rows in data.items()}
        selected=selection(cases,args.split,args.limit,args.seed)
        count=0
        for c in selected:
            for condition in execution_conditions:
                pid=digest([c['case_id'],condition,'prediction'])
                common=dict(case_id=c['case_id'],condition=condition,split=c['split'],group_id=c.get('group_id') or c['case_id'],
                            dataset_id=c['dataset_id'],run_id=run_id,synthetic=bool(c.get('synthetic')))
                if args.command=='predict':
                    if pid in existing['predictions']: continue
                    result=backend.predict(c,condition)
                    validate_prediction(result,[x['id'] for x in c['candidates']])
                    row=append(args.out/'predictions.jsonl',dict(common,record_id=pid,**result,
                        outcome=c.get('outcome'),correct=None if c.get('outcome') is None else result['prediction']==c['outcome'],
                        answer_mapping=answer_labels([x['id'] for x in c['candidates']]),case_hash=digest(c)))
                    existing['predictions'][pid]=row; count+=1
                    print(f'Saved prediction: {c["case_id"]}/{condition}',flush=True)
                    continue
                p=existing['predictions'].get(pid)
                if p is None: raise ValueError(f'Missing original prediction for {c["case_id"]}/{condition}; run predict first')
                common.update(prediction_id=pid,prediction_hash=p['record_hash'])
                eid=digest([pid,'explanation'])
                if args.command=='explain':
                    if eid in existing['explanations']: continue
                    raw=backend.explain(c,condition,p['prediction'])
                    status=parse_explanation(raw,visible_evidence(c,condition))
                    row=append(args.out/'explanations.jsonl',dict(common,record_id=eid,raw=raw,**status,
                        prompt_version=PROMPT_VERSION,truncated=raw.get('finish_reason')=='length',prompt=explanation_prompt(c,condition,p['prediction'])))
                    existing['explanations'][eid]=row; count+=1
                    print(f'Saved explanation: {c["case_id"]}/{condition}; parse={status["parse_ok"]}, citations={status["citation_valid"]}, abstained={status["abstained"]}',flush=True)
                    continue
                e=existing['explanations'].get(eid)
                if e is None:
                    raise ValueError('Run explain first; missing/invalid model explanations are retained as records before intervention testing')
                # All systematic edits are defined without reading explanation contents.
                specs=planned_specs(c,condition,e,args.random_controls,args.seed,args.permutations,getattr(args,'suite','all'))
                for spec in specs:
                    iid=digest([pid,spec])
                    if iid in existing['interventions']: continue
                    changed,reason=apply(c,spec)
                    result=backend.predict(changed,condition,spec.get('order')) if changed else None
                    if result: validate_prediction(result,[x['id'] for x in c['candidates']])
                    effects=measurements(p,result)
                    claim=e['parsed'].get('counterfactual') if e and e['citation_valid'] and not e.get('claim_error') and not e.get('truncated') else None
                    applicable=bool(claim and spec['kind'] in ('attribute_sweep','categorical_toggle','explicit_claim') and
                        spec['evidence_ids']==[claim['evidence_id']] and spec.get('value')==claim['value'])
                    delta=effects['score_change']
                    agreement=(delta>1e-6 if claim['expected_direction']=='increase' else delta< -1e-6) if applicable and delta is not None else None
                    row=append(args.out/'interventions.jsonl',dict(common,record_id=iid,spec=spec,
                        explanation_id=eid if e else None,explanation_hash=e['record_hash'] if e else None,
                        status='skipped' if reason else 'measured',skip_reason=reason,before=p,after=result,
                        original_evidence=list(visible_evidence(c,condition).values()),
                        edited_evidence=list(visible_evidence(changed,condition).values()) if changed else None,
                        edited_outcome=None,**effects,was_cited=bool(e and e['citation_valid'] and set(spec['evidence_ids']) & set(e['parsed']['evidence_ids'])),
                        claim_applicable=applicable,claim_agreement=agreement))
                    existing['interventions'][iid]=row; count+=1
                print(f'Saved interventions: {c["case_id"]}/{condition}',flush=True)
        _,_,data=load_run(args.out)
        export_audit(args.out,data,cases)
        print(f'{args.command}: {count} new records in {args.out}; completed records reused.')
