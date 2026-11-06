#!/usr/bin/env python3
"""Export saved original explanation text for a four-concept presentation audit."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, verify, read, job_id, file_hash
from choice_trust.test100_execution import write_json


def main():
    manifest = verify(OUT)
    scopes = [read(OUT / name / 'scope.json') for name in
              ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')]
    if any(scope['source_experiment_id'] != manifest['experiment_id'] for scope in scopes):
        raise ValueError('Checkpoint belongs to another experiment')
    selected = [item for scope in scopes for item in scope['selected']]
    ids = [item['case_id'] for item in selected]
    if len(ids) != 4 or len(set(ids)) != 4:
        raise ValueError('Expected four distinct completed checkpoint cases')
    rows = []
    for cid in ids:
        entry = next(entry for entry in manifest['entries'] if entry['case_id'] == cid and entry['family'] == 'ORIGINAL')
        for repetition in range(50):
            jid = job_id(cid, entry['call_id'], repetition)
            path = OUT / 'responses' / f'{jid}.json'
            record = read(path)
            parsed = record['response']['parsed_result']
            if not isinstance(parsed, dict) or not isinstance(parsed.get('explanation'), str) or not parsed['explanation'].strip():
                raise ValueError(f'Original explanation unavailable for {jid}')
            annotation_path = OUT / 'annotations' / f'{jid}.json'
            annotation = read(annotation_path) if annotation_path.exists() else None
            rows.append({'case_id': cid, 'job_id': jid, 'repetition': repetition,
                         'explanation': parsed['explanation'],
                         'annotation_status': annotation['status'] if annotation else 'unavailable',
                         'annotation_valid': bool(annotation and annotation['status'] == 'completed'
                                                  and annotation['validation']['schema_and_traceability_ok']),
                         'response_sha256': file_hash(path)})
    result = {'experiment_id': manifest['experiment_id'],
              'scope_ids': [scope['scope_id'] for scope in scopes],
              'case_ids': ids, 'original_explanations': rows}
    destination = OUT / 'four_concept_sensitivity_v1' / 'source_explanations.json'
    write_json(destination, result)
    print(json.dumps({'path': str(destination), 'cases': ids, 'original_explanations': len(rows)}))


if __name__ == '__main__':
    main()
