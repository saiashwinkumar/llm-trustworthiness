"""Saved-record distributions, CE/EE, within-case faithfulness and uncertainty."""
from __future__ import annotations

from collections import Counter, defaultdict
from math import log, sqrt
from pathlib import Path
import csv
import json
import random
from statistics import mean

from .repeated8 import OUT, verify, read, job_id, CROSSWALK, SUBTYPES
from .test100_execution import write_json

PARENTS = ('CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY')
ALPHA = 0.5
OUTCOMES = ('dannon', 'hiland', 'weight', 'yoplait', 'INVALID')


def quantile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    x = (len(ordered) - 1) * p
    low = int(x); high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (x - low)


def interval(values): return {'lower': quantile(values, .025), 'upper': quantile(values, .975), 'replicates_defined': len(values)}


def distribution(values, outcomes):
    counts = Counter(values)
    n = len(values)
    return {'n': n, 'counts': {x: counts[x] for x in outcomes},
            'frequency': {x: counts[x] / n if n else None for x in outcomes},
            'smoothed_probability': {x: (counts[x] + ALPHA) / (n + ALPHA * len(outcomes)) for x in outcomes},
            'invalid': counts['INVALID']}


def distribution_rows(rows, outcomes):
    result = distribution([row['outcome'] for row in rows], outcomes)
    result['parse_ok_count'] = sum(row.get('parse_ok') is True for row in rows)
    result['prediction_valid_count'] = sum(row.get('prediction_valid') is True for row in rows)
    result['truncated_count'] = sum(row.get('truncated') is True for row in rows)
    return result


def kl(edited, original, outcomes):
    p = original['smoothed_probability']; q = edited['smoothed_probability']
    return sum(q[x] * log(q[x] / p[x]) for x in outcomes)


def pearson(x, y):
    if any(v is None for v in x + y):
        return None, 'missing_concept_pair'
    ax = mean(x); ay = mean(y)
    vx = sum((v - ax) ** 2 for v in x); vy = sum((v - ay) ** 2 for v in y)
    if vx == 0 or vy == 0:
        return None, 'constant_CE' if vx == 0 else 'constant_EE'
    return sum((a - ax) * (b - ay) for a, b in zip(x, y)) / sqrt(vx * vy), None


def annotation_groups(annotation):
    if not annotation or annotation.get('status') != 'completed' or not annotation['validation']['schema_and_traceability_ok']:
        return None
    claims = annotation['parsed_annotation']['claims']
    return {group for claim in claims if claim['claimed_role'] in ('decisive', 'contributing') for group in claim['concept_groups']}


def output_for(record, entry):
    response = record['response']
    parsed = response['parsed_result']
    answer = parsed.get('prediction') if isinstance(parsed, dict) else None
    inverse = {v: k for k, v in entry['presentation']['answer_mapping'].items()}
    source_id = inverse.get(answer) if isinstance(answer, str) else None
    names = {c['id']: c['name'] for c in entry['original_source']['candidates']}
    return names.get(source_id, 'INVALID')


def calculate_case(case_id, entries, records, outcomes):
    original = next(e for e in entries if e['family'] == 'ORIGINAL')
    baseline = distribution_rows(records[original['call_id']], outcomes)
    dists = {original['family']: baseline}
    edits = []; families = defaultdict(list); coverage = []
    for entry in entries:
        if entry['family'] == 'ORIGINAL':
            continue
        family = entry['family']
        if not entry['applicable']:
            coverage.append({'family': family, 'applicable': False, 'reason': entry['skip_reason']})
            continue
        rows = records[entry['call_id']]
        dist = distribution_rows(rows, outcomes)
        dists[family] = dist
        value = kl(dist, baseline, outcomes) if rows and baseline['n'] else None
        edits.append({'case_id': case_id, 'edit_id': entry['call_id'], 'family': family,
                      'parent_concept': CROSSWALK[family], 'KL_nats': value,
                      'original_n': baseline['n'], 'edited_n': dist['n']})
        if value is not None:
            families[family].append(value)
        coverage.append({'family': family, 'applicable': True, 'saved_draws': len(rows),
                         'missing_draws': 50 - len(rows)})
    family_effects = {family: mean(vals) for family, vals in families.items()}
    weights = {}; ce = {}
    for concept in PARENTS:
        relevant = [f for f in family_effects if CROSSWALK[f] == concept]
        ce[concept] = mean(family_effects[f] for f in relevant) if relevant else None
        weights[concept] = {f: {'family_weight': 1 / len(relevant),
                                'each_edit_weight': 1 / (len(relevant) * len(families[f]))}
                            for f in relevant}
    original_rows = records[original['call_id']]
    ee = {}; annotation_coverage = {}
    for concept in PARENTS:
        assessable = [row['groups'] for row in original_rows if row['groups'] is not None]
        hits = sum(concept in groups for groups in assessable)
        ee[concept] = hits / len(assessable) if assessable else None
        annotation_coverage[concept] = {'presenting_as_influential': hits,
                                         'assessable_original_explanations': len(assessable),
                                         'original_draws': len(original_rows),
                                         'unavailable_annotations': len(original_rows) - len(assessable)}
    faithfulness, reason = pearson([ce[c] for c in PARENTS], [ee[c] for c in PARENTS])
    return {'case_id': case_id, 'distributions': dists, 'edit_effects': edits,
            'family_effects_nats': family_effects, 'concept_CE_nats': ce, 'weights': weights,
            'concept_EE': ee, 'annotation_coverage': annotation_coverage,
            'faithfulness': faithfulness, 'faithfulness_NA_reason': reason,
            'intervention_coverage': coverage}


def write_csv(path, rows):
    rows = list(rows)
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        fields = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)


def plot_svg(path, cases, key, title, ylim):
    width, height = 920, 420
    colors = {'CURRENT_PRICES': '#2764a5', 'CURRENT_ADVERTISING': '#d78c22', 'HOUSEHOLD_HISTORY': '#3f8c64'}
    labels = [case['case_id'] for case in cases]
    bars = []
    for i, case in enumerate(cases):
        for j, concept in enumerate(PARENTS):
            value = case[key][concept]
            if value is None:
                continue
            x = 75 + i * 102 + j * 25
            h = min(285, max(0, value / ylim * 285))
            bars.append(f'<rect x="{x}" y="{330-h:.1f}" width="22" height="{h:.1f}" fill="{colors[concept]}"/><title>{labels[i]} {concept}: {value:.4f}</title>')
    ticks = ''.join(f'<text x="{82+i*102}" y="355" font-size="12">{label}</text>' for i, label in enumerate(labels))
    legend = ''.join(f'<rect x="{75+i*275}" y="386" width="13" height="13" fill="{colors[c]}"/><text x="{93+i*275}" y="397" font-size="12">{c}</text>' for i,c in enumerate(PARENTS))
    body = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><text x="30" y="25" font-size="18" font-family="sans-serif">{title}</text><line x1="65" x2="900" y1="330" y2="330" stroke="#777"/><text x="25" y="333" font-size="12">0</text><text x="15" y="50" font-size="12">{ylim:g}</text>{"".join(bars)}{ticks}{legend}</svg>'
    path.write_text(body)


def distribution_plot(path, cases, outcomes):
    colors = ['#2764a5', '#d78c22', '#3f8c64', '#8e5796', '#888888']
    rows = [(case['case_id'], family, dist) for case in cases for family, dist in case['distributions'].items()]
    height = 90 + 24 * len(rows)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{height}" viewBox="0 0 1100 {height}"><rect width="100%" height="100%" fill="white"/><text x="20" y="28" font-family="sans-serif" font-size="18">Decoded product distributions (empirical shares)</text>']
    for i, (cid, family, dist) in enumerate(rows):
        y = 55 + 24 * i
        parts.append(f'<text x="20" y="{y+13}" font-size="11" font-family="sans-serif">{cid} · {family}</text>')
        x = 360
        for j, outcome in enumerate(outcomes):
            fraction = dist['frequency'][outcome] or 0
            width = fraction * 690
            parts.append(f'<rect x="{x:.1f}" y="{y}" width="{width:.1f}" height="17" fill="{colors[j % len(colors)]}"/><title>{cid} {family} {outcome}: {dist["counts"][outcome]}/{dist["n"]}</title>')
            x += width
    parts.append('<text x="20" y="'+str(height-15)+'" font-size="12" font-family="sans-serif">'+
                 ' · '.join(f'<tspan fill="{colors[i % len(colors)]}">■</tspan> {outcome}' for i, outcome in enumerate(outcomes)) + '</text></svg>')
    path.write_text(''.join(parts))


def comparison_plot(path, cases):
    colors = {'CURRENT_PRICES': '#2764a5', 'CURRENT_ADVERTISING': '#d78c22', 'HOUSEHOLD_HISTORY': '#3f8c64'}
    values = [v for case in cases for v in case['concept_CE_nats'].values() if v is not None]
    limit = max(.05, max(values, default=0) * 1.1)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="720" height="500" viewBox="0 0 720 500"><rect width="100%" height="100%" fill="white"/><text x="30" y="30" font-size="18" font-family="sans-serif">CE–EE comparison across case and parent concept</text><line x1="75" y1="425" x2="650" y2="425" stroke="#555"/><line x1="75" y1="65" x2="75" y2="425" stroke="#555"/><text x="280" y="475" font-size="13">CE (KL nats)</text><text x="10" y="55" font-size="13">EE</text>']
    for case in cases:
        for concept in PARENTS:
            ce, ee = case['concept_CE_nats'][concept], case['concept_EE'][concept]
            if ce is None or ee is None: continue
            x, y = 75 + ce / limit * 575, 425 - ee * 360
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{colors[concept]}" opacity=".8"/><title>{case["case_id"]} {concept}: CE={ce:.4f} nats, EE={ee:.4f}</title>')
    for i, concept in enumerate(PARENTS):
        parts.append(f'<rect x="{88+i*205}" y="447" width="12" height="12" fill="{colors[concept]}"/><text x="{105+i*205}" y="458" font-size="12">{concept}</text>')
    parts.append('</svg>'); path.write_text(''.join(parts))


def analyze(out=OUT, case_ids=None, destination=None):
    out = Path(out); manifest = verify(out)
    selected = [case for case in manifest['selected'] if case_ids is None or case['case_id'] in case_ids]
    if case_ids is not None and (len(selected) != len(case_ids) or len(selected) == 0):
        raise ValueError('Analysis case selection differs from the frozen manifest')
    selected_ids = {case['case_id'] for case in selected}
    destination = Path(destination) if destination is not None else out
    entries = defaultdict(list)
    for entry in manifest['entries']:
        if entry['case_id'] in selected_ids:
            entries[entry['case_id']].append(entry)
    all_names = {c['name'] for e in manifest['entries'] if e['case_id'] in selected_ids
                 for c in e['original_source']['candidates']}
    outcomes = tuple(sorted(all_names)) + ('INVALID',)
    records = defaultdict(list)
    review = []
    edited_diagnostics = defaultdict(lambda: {'saved_annotations': 0, 'valid_annotations': 0,
        'invalid_or_unassessable_annotations': 0, 'claim_roles': Counter(),
        'factual_statuses': Counter(), 'stale_statuses': Counter(), 'rule_count': 0})
    for jid in manifest['job_order']:
        if jid.split('__')[1] not in selected_ids:
            continue
        entry = next(e for e in entries[jid.split('__')[1]] if e['family'] == jid.rsplit('__', 2)[-2])
        response_path = out / 'responses' / f'{jid}.json'
        if not response_path.exists():
            continue
        response = read(response_path)
        annotation_path = out / 'annotations' / f'{jid}.json'
        annotation = read(annotation_path) if annotation_path.exists() else None
        groups = annotation_groups(annotation) if entry['family'] == 'ORIGINAL' else None
        row = {'job_id': jid, 'outcome': output_for(response, entry), 'groups': groups,
               'annotation_status': annotation['status'] if annotation else 'unavailable',
               'parse_ok': response['response']['diagnostics']['parse_ok'],
               'prediction_valid': response['response']['diagnostics']['prediction_valid'],
               'truncated': response['response']['diagnostics']['generation_truncated']}
        records[entry['call_id']].append(row)
        if annotation:
            review.append({'job_id': jid, 'case_id': entry['case_id'], 'family': entry['family'],
                           'annotation_path': str(annotation_path.relative_to(out)),
                           'source_response_path': str(response_path.relative_to(out)),
                           'parsed_annotation': annotation['parsed_annotation'],
                           'validation_issues': annotation['validation']['issues'],
                           'validation_warnings': annotation['validation']['warnings'],
                           'source_explanation': annotation['source_explanation'],
                           'human_reviewed': False})
            if entry['family'] != 'ORIGINAL':
                group = edited_diagnostics[entry['family']]
                group['saved_annotations'] += 1
                if annotation['status'] == 'completed' and annotation['validation']['schema_and_traceability_ok']:
                    group['valid_annotations'] += 1
                    for claim in annotation['parsed_annotation']['claims']:
                        group['claim_roles'][claim['claimed_role']] += 1
                        group['factual_statuses'][claim['factual_status']] += 1
                        group['stale_statuses'][claim['comparison_assessment']['stale_status']] += 1
                    group['rule_count'] += len(annotation['parsed_annotation']['rules'])
                else:
                    group['invalid_or_unassessable_annotations'] += 1
    cases = [calculate_case(s['case_id'], entries[s['case_id']], records, outcomes) for s in selected]
    scores = [c['faithfulness'] for c in cases if c['faithfulness'] is not None]
    result = {'experiment_id': manifest['experiment_id'], 'cases': cases,
              'aggregate_faithfulness': mean(scores) if scores else None,
              'aggregate_assessable_cases': len(scores), 'selected_cases': len(selected),
              'scope': 'two_case_checkpoint_of_frozen_eight' if case_ids is not None else 'frozen_eight',
              'outcome_space': outcomes, 'smoothing_alpha': ALPHA, 'KL_units': 'nats',
              'interpretation': 'CE measures influence under the declared edits; it is not universal concept importance. Positive KL occurs under finite-sample no-effect sampling.'}
    result['output_quality_totals'] = {'draws': sum(d['n'] for case in cases for d in case['distributions'].values()),
        'parse_ok': sum(d['parse_ok_count'] for case in cases for d in case['distributions'].values()),
        'prediction_valid': sum(d['prediction_valid_count'] for case in cases for d in case['distributions'].values()),
        'invalid_outcome': sum(d['invalid'] for case in cases for d in case['distributions'].values()),
        'truncated': sum(d['truncated_count'] for case in cases for d in case['distributions'].values())}
    result['edited_explanation_diagnostics'] = {family: {key: dict(value) if isinstance(value, Counter) else value
        for key, value in group.items()} for family, group in edited_diagnostics.items()}
    rng = random.Random(42)
    replicates = []; undefined = Counter(); case_reps = defaultdict(lambda: {'CE': defaultdict(list), 'EE': defaultdict(list), 'F': []})
    for _ in range(1000):
        sampled_cases = []
        for selection in selected:
            cid = selection['case_id']; sampled = {}
            for entry in entries[cid]:
                rows = records[entry['call_id']]
                sampled[entry['call_id']] = [rng.choice(rows) for _ in rows] if rows else []
            calc = calculate_case(cid, entries[cid], sampled, outcomes)
            sampled_cases.append(calc)
            for concept in PARENTS:
                for metric, name in (('concept_CE_nats', 'CE'), ('concept_EE', 'EE')):
                    value = calc[metric][concept]
                    if value is not None:
                        case_reps[cid][name][concept].append(value)
            if calc['faithfulness'] is None:
                undefined[calc['faithfulness_NA_reason']] += 1
            else:
                case_reps[cid]['F'].append(calc['faithfulness'])
        household_sample = [rng.choice(sampled_cases) for _ in sampled_cases]
        values = [c['faithfulness'] for c in household_sample if c['faithfulness'] is not None]
        if values:
            replicates.append(mean(values))
        else:
            undefined['aggregate_no_assessable_cases'] += 1
    result['uncertainty'] = {'method': f'1000 bootstrap replicates; resample complete original response+annotation pairs once per case and reuse that baseline for every edit; independently resample each edited input; then resample {len(selected)} households/cases with replacement for the aggregate.',
        'aggregate_faithfulness_interval': interval(replicates),
        'aggregate_undefined_replicates': 1000 - len(replicates),
        'within_case_undefined_reasons': dict(undefined), 'case_intervals': {cid: {
            'CE': {c: interval(case_reps[cid]['CE'][c]) for c in PARENTS},
            'EE': {c: interval(case_reps[cid]['EE'][c]) for c in PARENTS},
            'faithfulness': interval(case_reps[cid]['F']),
            'faithfulness_undefined_replicates': 1000 - len(case_reps[cid]['F'])}
            for cid in entries}}
    permutations = []
    for case in cases:
        cid = case['case_id']; original = next(e for e in entries[cid] if e['family'] == 'ORIGINAL')
        base = [x['outcome'] for x in records[original['call_id']]]
        for edit in case['edit_effects']:
            if edit['KL_nats'] is None:
                continue
            edited = [x['outcome'] for x in records[edit['edit_id']]]
            null = []
            for _ in range(1000):
                pooled = base + edited
                rng.shuffle(pooled)
                null.append(kl(distribution(pooled[len(base):], outcomes),
                               distribution(pooled[:len(base)], outcomes), outcomes))
            permutations.append({'case_id': cid, 'edit_id': edit['edit_id'], 'family': edit['family'],
                'observed_KL_nats': edit['KL_nats'], 'no_effect_median_nats': quantile(null, .5),
                'no_effect_95_percentile_nats': quantile(null, .95),
                'permutation_tail_fraction': sum(v >= edit['KL_nats'] for v in null) / len(null)})
    result['no_effect_reference'] = {'method': 'For each edit, pool its saved original and edited decoded outcomes, randomly permute, split at the original group size, recalculate smoothed KL 1000 times. Group sizes preserved. Separate per-edit reference; no additional inference.',
                                     'per_edit': permutations}
    write_json(destination / 'analysis.json', result)
    write_json(destination / 'manual_review_packet.json', {'human_reviewed': False, 'selection': 'All saved annotations in selected job order', 'records': review})
    write_csv(destination / 'tables/distributions.csv', ({'case_id': case['case_id'], 'family': family,
        'outcome': outcome, 'count': dist['counts'][outcome], 'frequency': dist['frequency'][outcome],
        'smoothed_probability': dist['smoothed_probability'][outcome], 'total_draws': dist['n'], 'invalid_draws': dist['invalid']}
        | {'parse_ok_draws': dist['parse_ok_count'], 'prediction_valid_draws': dist['prediction_valid_count'],
           'truncated_draws': dist['truncated_count']}
        for case in cases for family, dist in case['distributions'].items() for outcome in outcomes))
    write_csv(destination / 'tables/edit_effects.csv', (edit for case in cases for edit in case['edit_effects']))
    write_csv(destination / 'tables/family_effects.csv', ({'case_id': case['case_id'], 'family': family,
        'parent_concept': CROSSWALK[family], 'mean_KL_nats': value,
        'family_weight_in_concept': case['weights'].get(CROSSWALK[family], {}).get(family, {}).get('family_weight')}
        for case in cases for family, value in case['family_effects_nats'].items()))
    write_csv(destination / 'tables/intervention_coverage.csv', ({'case_id': case['case_id'], **item}
        for case in cases for item in case['intervention_coverage']))
    write_csv(destination / 'tables/concept_comparison.csv', ({'case_id': case['case_id'], 'concept': concept,
        'CE_nats': case['concept_CE_nats'][concept], 'EE': case['concept_EE'][concept],
        'EE_numerator': case['annotation_coverage'][concept]['presenting_as_influential'],
        'EE_denominator': case['annotation_coverage'][concept]['assessable_original_explanations'],
        'faithfulness': case['faithfulness'], 'faithfulness_NA_reason': case['faithfulness_NA_reason']}
        for case in cases for concept in PARENTS))
    write_csv(destination / 'tables/no_effect_reference.csv', permutations)
    write_csv(destination / 'tables/edited_explanation_diagnostics.csv', ({'family': family,
        'saved_annotations': group['saved_annotations'], 'valid_annotations': group['valid_annotations'],
        'invalid_or_unassessable_annotations': group['invalid_or_unassessable_annotations'],
        'rule_count': group['rule_count'], 'claim_roles_json': json.dumps(group['claim_roles']),
        'factual_statuses_json': json.dumps(group['factual_statuses']),
        'stale_statuses_json': json.dumps(group['stale_statuses'])}
        for family, group in result['edited_explanation_diagnostics'].items()))
    plot_svg(destination / 'choice_distribution_ce.svg', cases, 'concept_CE_nats', 'Concept CE by example (KL, nats)', max(.05, max((v or 0) for case in cases for v in case['concept_CE_nats'].values()) * 1.1))
    plot_svg(destination / 'concept_ee.svg', cases, 'concept_EE', 'Concept EE by example (share of assessable originals)', 1)
    distribution_plot(destination / 'product_distributions.svg', cases, outcomes)
    comparison_plot(destination / 'ce_ee_comparison.svg', cases)
    expected = sum(50 for e in manifest['entries'] if e['case_id'] in selected_ids and e['applicable'])
    title = 'Two-example checkpoint from frozen eight-example repeated-sampling study' if case_ids is not None else 'Eight-example repeated-sampling study'
    lines = [f'# {title}', '',
        f"Saved Qwen draws: {sum(len(v) for v in records.values())}/{expected}. Original draws: {sum(len(records[next(e for e in entries[c['case_id']] if e['family']=='ORIGINAL')['call_id']]) for c in cases)}/{50 * len(selected)}.",
        f"Assessable within-example correlations: {len(scores)}/{len(selected)}. Mean F: {result['aggregate_faithfulness'] if scores else 'NA'}.",
        f"Bootstrap 95% interval: {result['uncertainty']['aggregate_faithfulness_interval']}. Undefined aggregate replicates: {1000-len(replicates)}/1000.", '',
        'CE measures response-distribution shifts under these saved edits. A positive KL estimate alone is not evidence of influence because finite samples yield positive KL under the permutation no-effect reference.',
        f"Saved output quality: {result['output_quality_totals']}. Invalid model answers remain in the INVALID outcome; missing transport jobs are excluded and reported separately.",
        'Product-order and answer-mapping controls are reported in the distribution and edit tables but excluded from the three substantive concept CE values and faithfulness correlations.',
        'EE counts decisive/contributing claims in original explanations only. F is Pearson correlation across the three non-overlapping parent groups within each case; missing or constant vectors are NA.',
        'Edited Luna annotations supply separate factual, rule, and stale-information diagnostics in tables/edited_explanation_diagnostics.csv.',
        f'The {len(selected)} distinct households and three parent concepts provide an exploratory estimate. Repeated draws improve these distributions but do not establish population-wide generalization.',
        'Dirichlet alpha=0.5 smoothing and the bootstrap/permutation procedures are this implementation, not the paper’s Bayesian hierarchical estimator.',
        'Automated Luna annotations have not been human reviewed. See manual_review_packet.json.', '',
        '| Case | Household | CE prices | CE ads | CE history | EE prices | EE ads | EE history | F |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    households = {s['case_id']: s['household_id'] for s in selected}
    for case in cases:
        fmt = lambda x: 'NA' if x is None else f'{x:.3f}'
        lines.append('| ' + ' | '.join([case['case_id'], households[case['case_id']]] +
            [fmt(case['concept_CE_nats'][c]) for c in PARENTS] +
            [fmt(case['concept_EE'][c]) for c in PARENTS] + [fmt(case['faithfulness'])]) + ' |')
    lines += ['', 'Numerical details: tables/distributions.csv, tables/edit_effects.csv, tables/family_effects.csv, tables/intervention_coverage.csv, tables/concept_comparison.csv, tables/edited_explanation_diagnostics.csv, tables/no_effect_reference.csv, and analysis.json. Plots: product_distributions.svg, ce_ee_comparison.svg, choice_distribution_ce.svg, concept_ee.svg.']
    (destination / 'report.md').write_text('\n'.join(lines) + '\n')
    return result
