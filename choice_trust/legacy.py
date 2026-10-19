"""Read-only conversion of historical four-choice results into a separate run."""
import hashlib
import json
import csv
from pathlib import Path
from experiment import digest, read_jsonl
from .adapters import yogurt,fit_policies
from .storage import atomic_json,write_jsonl,append,load_run
from .runner import export_audit
from .scoring import validate_prediction


def unique(rows):
    index={}
    for r in rows:
        key=(r['case_id'],r['condition'])
        if key in index: raise ValueError('Duplicate legacy rows require explicit resolution before import')
        index[key]=r
    return index


def import_legacy(source,case_path,out):
    if out.exists(): raise ValueError('Legacy import requires a NEW output directory')
    old_manifest=json.loads((source/'run_manifest.json').read_text()) if (source/'run_manifest.json').exists() else {}
    source_hash=hashlib.sha256(case_path.read_bytes()).hexdigest()
    if old_manifest.get('case_file_sha256') and old_manifest['case_file_sha256']!=source_hash:
        raise ValueError('Legacy dataset hash mismatch')
    mp=case_path.with_name('manifest.json')
    cases=fit_policies(yogurt(read_jsonl(case_path),json.loads(mp.read_text()) if mp.exists() else None))
    index={c['case_id']:c for c in cases}
    predictions=unique(read_jsonl(source/'predictions.jsonl'))
    explanations=unique(read_jsonl(source/'faithfulness.jsonl'))
    warnings=['LEGACY IMPORT: historical records are readable, but original code execution and unrecorded raw calls cannot be independently verified.',
              'Legacy interventions did not save complete edited score vectors. These remain not measured/unavailable; no vectors are reconstructed.',
              'This is a separate read-only conversion. New experiments must use a new run directory.']
    manifest=dict(schema_version=2,protocol_version='legacy-import-v2',cases_hash=digest(cases),
                  backend={k:old_manifest.get(k) for k in ('backend','model_id','revision','server_settings')},
                  legacy_manifest=old_manifest,warnings=warnings,
                  source_hashes={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in
                                 ('predictions.jsonl','faithfulness.jsonl','run_manifest.json') if (source/name).exists()})
    # Validate joins before creating anything.
    for key,p in predictions.items():
        if p['case_id'] not in index: raise ValueError('Legacy prediction missing its case')
        c=index[p['case_id']]
        if p['target']!=c['outcome'] or p['split']!=c['split']: raise ValueError('Legacy target/split mismatch')
        if p.get('prompt_sha256') and digest(p['prompt'])!=p['prompt_sha256']: raise ValueError('Legacy prompt changed')
        for field in ('model_id','revision'):
            if old_manifest.get(field) and p.get('metadata',{}).get(field)!=old_manifest[field]: raise ValueError('Legacy model provenance mismatch')
        if key in explanations:
            e=explanations[key]
            if e['original_prediction']!=p['prediction'] or e['target']!=p['target'] or abs(e['original_probability']-p['probabilities'][p['prediction']])>1e-7:
                raise ValueError('Legacy explanation references changed original prediction')
    if set(explanations)-set(predictions): raise ValueError('Legacy explanations lack original predictions')
    out.mkdir(parents=True); write_jsonl(out/'cases.jsonl',cases); atomic_json(out/'run_manifest.json',manifest)
    run_id=digest(manifest)
    imported={}
    for key,p in predictions.items():
        c=index[p['case_id']]; pid=digest([p['case_id'],p['condition'],'prediction'])
        validate_prediction(dict(prediction=p['prediction'],scores=p['probabilities']),[x['id'] for x in c['candidates']])
        common=dict(case_id=p['case_id'],condition=p['condition'],split=p['split'],group_id=c['group_id'],
                    dataset_id=c['dataset_id'],run_id=run_id,synthetic=c['synthetic'])
        original=append(out/'predictions.jsonl',dict(common,record_id=pid,prediction=p['prediction'],scores=p['probabilities'],
            outcome=p['target'],correct=p['prediction']==p['target'],prompt=p.get('prompt'),raw={'legacy_record':p},case_hash=digest(c)))
        if key not in explanations: continue
        e=explanations[key]; eid=digest([pid,'explanation'])
        common.update(prediction_id=pid,prediction_hash=original['record_hash'])
        exp=append(out/'explanations.jsonl',dict(common,record_id=eid,raw=dict(text=e['raw_explanation'],finish_reason=e.get('explanation_finish_reason')),
            parsed=e.get('parsed_explanation'),parse_ok=e['parse_ok'],citation_valid=e['citation_valid'],abstained=e['abstained'],
            parse_error=e.get('parse_error'),claim_error=None,truncated=e.get('explanation_finish_reason')=='length',legacy=True))
        imported[key]=exp
        specs=[('cited_remove',e.get('comprehensiveness'),e.get('margin_drop')),
               ('cited_retain',e.get('sufficiency_gap'),None)]
        for i,control in enumerate(e.get('random_controls',[])):
            specs += [(f'random_remove:{i}',control.get('comprehensiveness'),control.get('margin_drop')),
                      (f'random_retain:{i}',control.get('sufficiency_gap'),None)]
        specs += [('presentation',None,None),('explicit_claim',None,None)]
        for name,drop,margin in specs:
            kind=name.split(':')[0]
            measured=drop is not None or (kind=='presentation' and e.get('order_flip') is not None) or (kind=='explicit_claim' and e.get('counterfactual_agreement') is not None)
            append(out/'interventions.jsonl',dict(common,record_id=digest([pid,name]),explanation_id=eid,explanation_hash=exp['record_hash'],
                spec={'kind':kind,'evidence_ids':e.get('selected_ids',[]) if kind.startswith('cited') else [],'legacy_test':name},
                status='measured' if measured else 'skipped',skip_reason=None if measured else e.get('counterfactual_skip_reason') or 'Not recorded in historical file',
                before=original,after=None,original_evidence=list(c['evidence']),edited_evidence=None,edited_outcome=None,
                reference_candidate=p['prediction'],fixed_rival=e.get('runner_up'),score_change=-drop if drop is not None else e.get('counterfactual_probability_change') if kind=='explicit_claim' else None,
                margin_change=-margin if margin is not None else None,winner_changed=e.get('order_flip') if kind=='presentation' else None,
                claim_agreement=e.get('counterfactual_agreement') if kind=='explicit_claim' else None,
                was_cited=None,claim_applicable=None,legacy=True,scores_unavailable_reason='Full edited scores were not retained by the legacy protocol'))
    _,_,data=load_run(out); export_audit(out,data,cases)
    old_audit=source/'manual_audit.csv'
    if old_audit.exists():
        with old_audit.open(newline='',encoding='utf-8') as f: audit=unique(list(csv.DictReader(f)))
        path=out/'manual_audit.csv'
        with path.open(newline='',encoding='utf-8') as f: rows=list(csv.DictReader(f))
        for row in rows:
            old=audit.get((row['case_id'],row['condition']))
            if old and old.get('explanation')==explanations[(row['case_id'],row['condition'])]['raw_explanation']:
                for key in ('supported_claims','total_factual_claims','reviewer_notes'): row[key]=old.get(key,'')
        if rows:
            with path.open('w',newline='',encoding='utf-8') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'Imported {len(predictions)} predictions and {len(explanations)} explanations to {out}. Source files unchanged.')
