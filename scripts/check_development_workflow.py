"""Six-call, resumable real development check; success concerns execution only."""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiment import digest, read_jsonl
from choice_trust.runner import run, selection
from choice_trust.model import RemoteBackend, prompt
from choice_trust.interventions import systematic, apply, measurements
from choice_trust.storage import load_run, append, writer_lock, atomic_json
from choice_trust.schema import visible_evidence
from choice_trust.scoring import validate_prediction
from scripts.verify_cpu_server import validate_health


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'outputs_development_check_v1')
    args = parser.parse_args()
    cases_path = ROOT/'data_v2/yogurt/cases.jsonl'
    case = selection(read_jsonl(cases_path), 'development', 1, 42)[0]
    args.out.mkdir(parents=True, exist_ok=True)
    # Standard runner requires a clean output directory for first initialization.
    backend = RemoteBackend()
    validate_health(backend.health)
    settings = dict(cases=cases_path, out=args.out, split='development', limit=1,
                    mock=False, conditions=['no_history', 'with_history'], seed=42,
                    random_controls=5, permutations=2, plan=None, only_conditions=None)
    for command in ('predict', 'explain'):
        run(SimpleNamespace(command=command, **settings))
    with writer_lock(args.out):
        manifest, _, data = load_run(args.out)
        if backend.metadata != manifest['backend']:
            raise ValueError('Server metadata changed; preserve this check and investigate')
        # Select one admissible price edit without using the explanation or outcome.
        spec = next(s for s in systematic(case, 'no_history', 42, 2)
                    if s['kind'] == 'attribute_sweep' and apply(case, s)[0] is not None)
        for condition in settings['conditions']:
            p = next(r for r in data['predictions'] if r['condition'] == condition)
            e = next(r for r in data['explanations'] if r['condition'] == condition)
            iid = digest([p['record_id'], spec])
            if any(r['record_id'] == iid for r in data['interventions']):
                continue
            changed, reason = apply(case, spec)
            result = backend.predict(changed, condition)
            validate_prediction(result, [c['id'] for c in case['candidates']])
            append(args.out/'interventions.jsonl', dict(
                case_id=case['case_id'], condition=condition, split='development',
                group_id=case['group_id'], dataset_id=case['dataset_id'], run_id=digest(manifest),
                synthetic=False, prediction_id=p['record_id'], prediction_hash=p['record_hash'],
                record_id=iid, spec=spec, explanation_id=e['record_id'], explanation_hash=e['record_hash'],
                status='measured', skip_reason=reason, before=p, after=result,
                original_evidence=list(visible_evidence(case, condition).values()),
                edited_evidence=list(visible_evidence(changed, condition).values()),
                edited_outcome=None, **measurements(p, result), was_cited=None,
                claim_applicable=False, claim_agreement=None,
                purpose='Development execution check: predetermined edit, not a favorable-result test'))
            print('Saved edited-input prediction:', case['case_id'], condition, flush=True)
    _, _, data = load_run(args.out)
    complete = all(len(data[k]) == 2 for k in ('predictions', 'explanations', 'interventions'))
    atomic_json(args.out/'execution_check.json', dict(
        completed=complete, case_id=case['case_id'], split='development',
        prediction_calls_saved=len(data['predictions']), explanation_calls_saved=len(data['explanations']),
        edited_prediction_calls_saved=len(data['interventions']),
        criterion='Calls returned and records/measurements saved; no requirement for correctness, changed answer, or explanation quality'))
    lines = ['# Real development execution check', '',
             f"Case: {case['case_id']}; household: {case['group_id']}; observed outcome: {case['outcome']}.", '',
             'The observed outcome is evaluation-only and is excluded from model prompts.', '',
             'The edit was predefined independently of explanation quality and the observed outcome.', '']
    for condition in settings['conditions']:
        p = next(r for r in data['predictions'] if r['condition'] == condition)
        e = next(r for r in data['explanations'] if r['condition'] == condition)
        i = next(r for r in data['interventions'] if r['condition'] == condition)
        lines += ['## '+condition, '', '### Actual prediction input', '', '```text', p['prompt'], '```', '',
                  '### Actual prediction response', '', '```json', json.dumps(p['raw'], indent=2), '```', '',
                  '### Actual explanation input', '', '```text', e['prompt'], '```', '',
                  '### Actual explanation response', '', '```json', json.dumps(e['raw'], indent=2), '```', '',
                  '### Actual edited-input prediction input', '', '```text', i['after']['prompt'], '```', '',
                  '### Actual edited prediction response and measurement', '', '```json',
                  json.dumps(dict(spec=i['spec'], raw=i['after']['raw'], score_change=i['score_change'],
                                  margin_change=i['margin_change'], winner_changed=i['winner_changed']), indent=2), '```', '',
                  f"Record hashes: prediction `{p['record_hash']}`, explanation `{e['record_hash']}`, intervention `{i['record_hash']}`.", '']
    (args.out/'execution_check.md').write_text('\n'.join(lines)+'\n')
    print('Execution check complete:', complete, 'Report:', args.out/'execution_check.md', flush=True)


if __name__ == '__main__':
    main()
