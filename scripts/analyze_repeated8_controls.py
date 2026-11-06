#!/usr/bin/env python3
"""Add a separately labeled, sample-audited presentation axis to faithfulness."""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from pathlib import Path
from statistics import mean
import csv
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8_analysis import pearson

STUDY = ROOT / 'choice_study/choice_faithfulness_8x50_v1'
DEST = STUDY / 'four_concept_sensitivity_v1'
PARENTS = ('CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY')
CHECKPOINTS = ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')


def read(path):
    return json.loads(path.read_text())


def file_hash(path):
    return sha256(path.read_bytes()).hexdigest()


def main():
    analyses = {name: read(STUDY / name / 'analysis.json') for name in CHECKPOINTS}
    scopes = {name: read(STUDY / name / 'scope.json') for name in CHECKPOINTS}
    sample_path = DEST / 'presentation_audit_sample20.json'
    sample = read(sample_path)
    review = read(DEST / 'presentation_audit_review.json')
    experiment = next(iter(analyses.values()))['experiment_id']
    if any(a['experiment_id'] != experiment for a in analyses.values()):
        raise ValueError('Checkpoints belong to different experiments')
    if any(s['source_experiment_id'] != experiment for s in scopes.values()):
        raise ValueError('Checkpoint scope belongs to another experiment')
    if sample['experiment_id'] != experiment or sample['scope_ids'] != [s['scope_id'] for s in scopes.values()]:
        raise ValueError('Presentation audit sample belongs to another scope')
    if review['sample_sha256'] != file_hash(sample_path):
        raise ValueError('Presentation audit review belongs to another sample')
    if len(sample['sample']) != 20 or len(review['decisions']) != 20:
        raise ValueError('Expected 20 audited original explanations')
    ids = [row['job_id'] for row in sample['sample']]
    if len(set(ids)) != 20 or set(ids) != {row['job_id'] for row in review['decisions']}:
        raise ValueError('Audit decisions do not cover exactly the sampled explanations')
    if review['presentation_influence_claims'] != 0 or any(row['presentation_influence_claim'] for row in review['decisions']):
        raise ValueError('A sampled explanation claimed presentation influence; zero EE is not justified by this rule')
    counts = Counter(row['case_id'] for row in sample['sample'])
    if set(counts.values()) != {5} or len(counts) != 4:
        raise ValueError('Audit was not five random originals per case')
    rows = []
    for checkpoint in CHECKPOINTS:
        for case in analyses[checkpoint]['cases']:
            cid = case['case_id']
            ce3 = [case['concept_CE_nats'][concept] for concept in PARENTS]
            ee3 = [case['concept_EE'][concept] for concept in PARENTS]
            recomputed, reason = pearson(ce3, ee3)
            if reason or abs(recomputed - case['faithfulness']) > 1e-12:
                raise ValueError(f'Three-concept F did not reproduce for {cid}')
            edits = {item['family']: item for item in case['edit_effects']}
            order = edits['PRODUCT_ORDER_CONTROL']
            mapping = edits['ANSWER_MAPPING_CONTROL']
            if any(item['original_n'] != 50 or item['edited_n'] != 50 for item in (order, mapping)):
                raise ValueError(f'Incomplete control distributions for {cid}')
            ce_control = mean((order['KL_nats'], mapping['KL_nats']))
            ee_control_assumed = 0.0
            f4, reason = pearson(ce3 + [ce_control], ee3 + [ee_control_assumed])
            if reason:
                raise ValueError(f'Four-concept F undefined for {cid}: {reason}')
            rows.append({'case_id': cid, 'checkpoint': checkpoint, 'original_valid_annotations':
                         case['annotation_coverage']['CURRENT_PRICES']['assessable_original_explanations'],
                         'audit_originals_sampled': counts[cid],
                         'audit_presentation_claims': 0,
                         'CE_current_prices_nats': ce3[0], 'CE_current_advertising_nats': ce3[1],
                         'CE_household_history_nats': ce3[2],
                         'CE_product_order_control_nats': order['KL_nats'],
                         'CE_answer_mapping_control_nats': mapping['KL_nats'],
                         'CE_presentation_control_mean_nats': ce_control,
                         'EE_current_prices': ee3[0], 'EE_current_advertising': ee3[1],
                         'EE_household_history': ee3[2], 'EE_presentation_control_assumed': ee_control_assumed,
                         'faithfulness_3_concepts': recomputed, 'faithfulness_4_concepts_assumed_zero': f4,
                         'delta_F4_minus_F3': f4 - recomputed})
    result = {'experiment_id': experiment, 'source_scope_ids': [s['scope_id'] for s in scopes.values()],
              'status': 'exploratory_sensitivity_not_primary_metric',
              'concept_order': [*PARENTS, 'PRESENTATION_CONTROL'],
              'control_CE_definition': 'Unweighted arithmetic mean of the product-order and answer-mapping control KL divergences (nats); both use 50 original and 50 edited Qwen draws, with answer codes decoded back to product identities.',
              'control_EE_definition': 'Assumed 0 for every case after Codex read 5 randomly selected original explanations per case (20 total) and found no explicit claim that candidate order, answer codes, or presentation format influenced the prediction. This is an assumption from a sample, not a complete annotation of 200 originals.',
              'audit_decision_rule': review['decision_rule'],
              'audit_sampling_rule': sample['sampling_rule'],
              'original_three_concept_metric_unchanged': True,
              'source_sha256': {str(path.relative_to(STUDY)): file_hash(path) for path in
                                [*(STUDY / name / 'analysis.json' for name in CHECKPOINTS),
                                 sample_path, DEST / 'presentation_audit_review.json']},
              'cases': rows}
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / 'control_inclusive_analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    with (DEST / 'control_inclusive_comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    md = ['# Presentation-control faithfulness sensitivity', '',
          'The original three-concept F remains the primary metric. This supplementary score treats the two presentation controls as one fourth axis.', '',
          '**Definitions:** CE_control = (KL_product-order + KL_answer-mapping) / 2. Answer codes are decoded back to product identities before KL. EE_control = 0 by the requested sample-based assumption. F4 = Pearson correlation of the four CE values with the four EE values within each case.', '',
          'Codex read five randomly selected original explanations per case (20/200, seed 42). None explicitly claimed that candidate order, answer codes, or presentation format influenced the choice. Mentions of *displayed prices* and *listed products* were treated as descriptions of factual inputs. This does not prove the other 180 explanations lack such claims. The original Luna schema did not offer a presentation label.', '',
          '| Case | Order KL | Mapping KL | Control CE mean | F3 primary | F4 assuming control EE=0 |',
          '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        md.append(f"| {row['case_id']} | {row['CE_product_order_control_nats']:.3f} | "
                  f"{row['CE_answer_mapping_control_nats']:.3f} | "
                  f"{row['CE_presentation_control_mean_nats']:.3f} | "
                  f"{row['faithfulness_3_concepts']:.3f} | "
                  f"{row['faithfulness_4_concepts_assumed_zero']:.3f} |")
    md += ['', 'The price-lowest pair illustrates the effect: row-710 has order-control KL 1.448 and F falls from 0.924 to 0.396; row-695 has answer-mapping KL 1.072 and F falls from 0.793 to 0.692 when the control EE is assumed zero.',
           'These two F values have different concept sets, so their numerical change is a sensitivity result, not a correction to the primary score. A large control CE can reflect sensitivity to prompt presentation. Neither control is a customer attribute or proof of internal attention.', '',
           'Audit trail: `presentation_audit_sample20.json`, `presentation_audit_review.json`, and `source_explanations.json`. Exact values: `control_inclusive_analysis.json` and `control_inclusive_comparison.csv`.']
    (DEST / 'report.md').write_text('\n'.join(md) + '\n')
    if (DEST / 'representative_original_claims.json').exists():
        from scripts.build_repeated8_controls_html import build
        build()
    print(json.dumps({'cases': {row['case_id']: {'F3': row['faithfulness_3_concepts'],
                                               'F4': row['faithfulness_4_concepts_assumed_zero']}
                                for row in rows}, 'out': str(DEST)}))


if __name__ == '__main__':
    main()
