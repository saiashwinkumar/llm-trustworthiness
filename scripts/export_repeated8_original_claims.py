#!/usr/bin/env python3
"""Export one complete original response and its verified Luna claim labels per case."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, file_hash, job_id, read, verify
from choice_trust.test100_execution import write_json


def main():
    manifest = verify(OUT)
    scopes = [read(OUT / name / 'scope.json') for name in
              ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')]
    selected = [item for scope in scopes for item in scope['selected']]
    if len(selected) != 4 or len({item['case_id'] for item in selected}) != 4:
        raise ValueError('Expected four distinct completed checkpoint examples')
    cases = []
    for item in selected:
        cid = item['case_id']
        entry = next(entry for entry in manifest['entries'] if entry['case_id'] == cid and entry['family'] == 'ORIGINAL')
        jid = job_id(cid, entry['call_id'], 0)
        response_path = OUT / 'responses' / f'{jid}.json'
        annotation_path = OUT / 'annotations' / f'{jid}.json'
        response = read(response_path)
        annotation = read(annotation_path)
        if annotation['status'] != 'completed' or not annotation['validation']['schema_and_traceability_ok']:
            raise ValueError(f'Original r00 annotation is not valid for {cid}')
        parsed = response['response']['parsed_result']
        if not isinstance(parsed, dict) or not isinstance(parsed.get('explanation'), str):
            raise ValueError(f'Original r00 explanation is unavailable for {cid}')
        claims = annotation['parsed_annotation']['claims']
        if any(claim['exact_quote'] not in parsed['explanation'] for claim in claims):
            raise ValueError(f'Annotation quote is not in the saved explanation for {cid}')
        cases.append({'case_id': cid, 'household_id': item['household_id'], 'job_id': jid,
                      'repetition': 0, 'candidate_names': {c['id']: c['name'] for c in entry['observations']['candidates']},
                      'original_prompt': entry['messages'][0]['content'],
                      'prediction': parsed['prediction'], 'evidence_ids': parsed['evidence_ids'],
                      'explanation': parsed['explanation'], 'claims': claims,
                      'rules': annotation['parsed_annotation']['rules'],
                      'response_sha256': file_hash(response_path),
                      'annotation_sha256': file_hash(annotation_path),
                      'annotation_model': annotation['returned_model']})
    result = {'experiment_id': manifest['experiment_id'],
              'manifest_sha256': file_hash(OUT / 'manifest.json'),
              'scope_ids': [scope['scope_id'] for scope in scopes],
              'sample_rule': 'Original repetition r00 for each of the four cases; all four saved annotations completed and passed schema/traceability validation.',
              'cases': cases}
    path = OUT / 'four_concept_sensitivity_v1' / 'representative_original_claims.json'
    write_json(path, result)
    print(json.dumps({'path': str(path), 'cases': [case['case_id'] for case in cases],
                      'claim_counts': {case['case_id']: len(case['claims']) for case in cases}}))


if __name__ == '__main__':
    main()
