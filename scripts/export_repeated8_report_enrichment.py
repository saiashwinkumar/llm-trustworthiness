#!/usr/bin/env python3
"""Export saved annotation summaries and edit definitions for the four-case HTML."""
from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, file_hash, job_id, read, verify
from choice_trust.test100_execution import write_json

PARENTS = ('CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY')
FAMILIES = ('ORIGINAL', 'CURRENT_PRICE', 'CURRENT_ADVERTISING', 'SUPPORT_PURCHASE',
            'HISTORICAL_OFFER_REMOVAL', 'PRODUCT_ORDER_CONTROL', 'ANSWER_MAPPING_CONTROL')


def summarize(out, entry):
    status = Counter()
    influence = Counter()
    patterns = Counter()
    stale = contradicted = unsupported = 0
    saved = valid = 0
    for repetition in range(50):
        jid = job_id(entry['case_id'], entry['call_id'], repetition)
        if not (out / 'responses' / f'{jid}.json').exists():
            raise ValueError(f'Missing Qwen response for {jid}')
        path = out / 'annotations' / f'{jid}.json'
        if path.exists():
            annotation = read(path)
            saved += 1
            state = annotation['status']
            good = state == 'completed' and annotation['validation']['schema_and_traceability_ok']
        else:
            state_path = out / 'states' / 'annotation' / f'{jid}.json'
            state = read(state_path)['status'] if state_path.exists() else 'unavailable'
            good = False
        status[state] += 1
        if not good:
            continue
        valid += 1
        claims = annotation['parsed_annotation']['claims']
        groups = {group for claim in claims if claim['claimed_role'] in ('decisive', 'contributing')
                  for group in claim['concept_groups']}
        influence.update(groups)
        patterns[tuple(group for group in PARENTS if group in groups)] += 1
        stale += any(claim.get('comparison_assessment', {}).get('stale_status') == 'stale' for claim in claims)
        contradicted += any(claim['factual_status'] == 'contradicted' for claim in claims)
        unsupported += any(claim['factual_status'] == 'unsupported_by_supplied_information' for claim in claims)
    return {'total_draws': 50, 'saved_annotations': saved, 'valid_annotations': valid,
            'annotation_statuses': dict(status),
            'claimed_influence': {concept: influence[concept] for concept in PARENTS},
            'influence_patterns': [{'concepts': list(pattern), 'count': count}
                                   for pattern, count in patterns.most_common()],
            'responses_with_stale_claim': stale,
            'responses_with_contradicted_claim': contradicted,
            'responses_with_unsupported_claim': unsupported}


def main():
    manifest = verify(OUT)
    scopes = [read(OUT / name / 'scope.json') for name in
              ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')]
    analyses = [read(OUT / name / 'analysis.json') for name in
                ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')]
    selected = [item for scope in scopes for item in scope['selected']]
    by_analysis = {case['case_id']: case for analysis in analyses for case in analysis['cases']}
    if len(selected) != 4 or len(by_analysis) != 4:
        raise ValueError('Expected four completed cases')
    cases = []
    for selection in selected:
        cid = selection['case_id']
        entries = {entry['family']: entry for entry in manifest['entries'] if entry['case_id'] == cid}
        conditions = {}
        for family in FAMILIES:
            entry = entries[family]
            if not entry['applicable']:
                raise ValueError(f'Expected applicable {family} for {cid}')
            conditions[family] = {'call_id': entry['call_id'], 'patch': entry['patch'],
                                  'edit_details': entry['edit_details'],
                                  'annotations': summarize(OUT, entry)}
        skipped = [{'family': family, 'reason': entry['skip_reason']}
                   for family, entry in entries.items() if not entry['applicable']]
        original = conditions['ORIGINAL']['annotations']
        analysis = by_analysis[cid]
        for concept in PARENTS:
            coverage = analysis['annotation_coverage'][concept]
            if (original['valid_annotations'] != coverage['assessable_original_explanations']
                    or original['claimed_influence'][concept] != coverage['presenting_as_influential']):
                raise ValueError(f'Original annotation counts disagree with saved EE for {cid}/{concept}')
        cases.append({'case_id': cid, 'household_id': selection['household_id'],
                      'conditions': conditions, 'skipped_edits': skipped})
    result = {'experiment_id': manifest['experiment_id'],
              'manifest_sha256': file_hash(OUT / 'manifest.json'),
              'scope_ids': [scope['scope_id'] for scope in scopes],
              'annotation_rule': 'A concept is claimed in one response if any valid annotation claim for it is decisive or contributing. The three original concept counts reproduce saved EE. Edited annotation summaries are descriptive diagnostics, not the original EE denominator.',
              'cases': cases}
    path = OUT / 'four_concept_sensitivity_v1' / 'report_enrichment.json'
    write_json(path, result)
    print(json.dumps({'path': str(path), 'cases': [case['case_id'] for case in cases],
                      'valid_original_annotations': {case['case_id']: case['conditions']['ORIGINAL']['annotations']['valid_annotations']
                                                     for case in cases}}))


if __name__ == '__main__':
    main()
