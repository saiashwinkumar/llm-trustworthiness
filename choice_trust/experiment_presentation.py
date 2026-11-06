"""Saved-record presentation analysis. No inference or experimental mutations.

The frozen metrics remain untouched. This view documents the Luna rule adapter,
claim-level stale denominator and conservative changed-field matching explicitly.
"""
from collections import Counter
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
import json

from .development_pilot import digest, FAMILIES, verify_edit
from .joint_observation import parse_joint_response
from .observations import canonical_price, inputs_from_prepared_yogurt
from .explanation_annotation import validate_annotations, GROUPS, RELATIONSHIPS, ROLES, STATUSES
from .luna_batch_schema import validate_batch_result
from .test100_metrics import load_run, prediction_metrics, influence, rule_assessment, rate

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'choice_study/test_with_history_100_v1'
LABELS = {
    'CURRENT_PRICE': 'Current price', 'CURRENT_ADVERTISING': 'Current advertising',
    'SUPPORT_PURCHASE': 'Support purchase', 'HISTORICAL_PRICE_ASSOCIATION': 'Historical price association',
    'HISTORICAL_ADVERTISING_ASSOCIATION': 'Historical advertising association',
    'HISTORICAL_OFFER_REMOVAL': 'Historical offer removal',
    'PRODUCT_ORDER_CONTROL': 'Product order', 'ANSWER_MAPPING_CONTROL': 'Answer mapping'}
PURPOSES = {
    'CURRENT_PRICE': 'Does changing one current price change the predicted product?',
    'CURRENT_ADVERTISING': 'Does toggling one current advertising flag change the predicted product?',
    'SUPPORT_PURCHASE': 'Does changing one supplied household purchase change the predicted product?',
    'HISTORICAL_PRICE_ASSOCIATION': 'Does rearranging historical price offers across purchases change the prediction?',
    'HISTORICAL_ADVERTISING_ASSOCIATION': 'Does rearranging historical advertising across purchases change the prediction?',
    'HISTORICAL_OFFER_REMOVAL': 'Does removing historical offers while retaining purchases change the prediction?',
    'PRODUCT_ORDER_CONTROL': 'Does reordering the same products change the predicted product?',
    'ANSWER_MAPPING_CONTROL': 'Does relabelling answer identifiers change the canonical predicted product?'}
CONDITIONS = ('no_history', 'with_history')
SPLITS = ('development', 'validation', 'test')
METHOD_NOTES = [
    'Development raw Qwen annotations and test Luna annotations are different automated layers; they are never pooled. Structurally invalid annotations are excluded from aggregate annotation metrics but preserved in source files.',
    'The stricter presentation match requires a changed source field or a defined frequency dependency. Broad unresolved concept mentions are excluded; any difference from the archived matcher is listed per pair. The archived metrics and protocol files are unchanged.',
    'Luna rule objects are projected into the existing uniquely-cheapest template only when the saved rule is explicit, sufficiently specified, eligible, has supported premises, links a decisive claim, and has no extra unevaluable conditions. Other rules remain unavailable for this automated template.',
    'The frozen stale-fact metric is response-level. The requested claim-level stale rate is shown separately: only complete-source edited claims with temporal_scope=current_edited and stale_status in {stale,not_stale} enter its denominator. Explicit original references, general/influence, unclear and unassessable claims are excluded.',
    'Automatic annotations are descriptive reference labels for this report, not human-confirmed facts. Structure/traceability checks do not validate semantics or full claim coverage.']


def read(path):
    return json.loads(Path(path).read_text())


def hash_file(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def decode(record, entry):
    if record is None:
        return None
    result = record['response']
    parsed, diagnostics = parse_joint_response(result['raw_response'], entry['observations']['candidates'],
        entry['observations'], truncated=result['diagnostics'].get('generation_truncated'))
    if parsed != result['parsed_result'] or diagnostics != result['diagnostics']:
        raise ValueError('Source parsing diagnostics changed: ' + entry['call_id'])
    if not diagnostics['parse_ok'] or not diagnostics['prediction_valid']:
        return None
    inverse = {v: k for k, v in entry['presentation']['answer_mapping'].items()}
    product = inverse[parsed['prediction']]
    if product != record['decoded_product_id']:
        raise ValueError('Incorrect saved canonical product: ' + entry['call_id'])
    return product


def load_development():
    directory = ROOT / 'choice_study/development_counterfactual_v1'
    manifest = read(directory / 'manifest.json')
    if digest({k: v for k, v in manifest.items() if k != 'plan_id'}) != manifest['plan_id']:
        raise ValueError('Development manifest seal mismatch')
    entries = {e['call_id']: e for e in manifest['entries'] if e['family'] in ('ORIGINAL',) + FAMILIES}
    cases = {}
    with (ROOT / 'data/processed/cases.jsonl').open() as stream:
        for line in stream:
            case = json.loads(line)
            if case['case_id'] in {e['case_id'] for e in entries.values()}:
                cases[case['case_id']] = case
    records = {}
    annotations = {}
    raw_annotations = {}
    for cid, entry in entries.items():
        if inputs_from_prepared_yogurt(cases[entry['case_id']], with_history=entry['condition'] == 'with_history') != entry['original_source']:
            raise ValueError('Development source/target join differs')
        if not entry['skip_reason']:
            verify_edit(entry, manifest['development_price_bounds_cents'])
        path = directory / 'responses' / f'{cid}.json'
        if path.exists():
            record = read(path)
            if record['plan_id'] != manifest['plan_id'] or record['response']['messages'] != entry['messages']:
                raise ValueError('Development response linkage differs')
            decode(record, entry)
            records[cid] = record
        path = directory / 'annotations' / f'{cid}.json'
        if path.exists():
            annotation = read(path)
            result = annotation['result']
            inp = result['annotation_input']
            if cid not in records or inp['explanation'] != records[cid]['response']['parsed_result']['explanation'] or inp['observations']['text'] != entry['observations']['text']:
                raise ValueError('Development annotation does not match exact response')
            parsed, diagnostics = validate_annotations(result['raw_annotation_response'], explanation=inp['explanation'],
                candidates=inp['candidates'], provenance=inp['provenance'], truncated=result['generation_metadata'].get('truncated'))
            if parsed != result['parsed_annotations']:
                raise ValueError('Development annotation parsed content changed')
            normalized = {'claims': parsed.get('claims', []) if isinstance(parsed, dict) else [], 'rules': [],
                'annotation_id': str(path.relative_to(ROOT)), 'record': result, 'raw_record': annotation,
                'method': 'Qwen3-1.7B provisional LLM annotation', 'valid': diagnostics['structure_and_traceability_ok'],
                'coverage_complete': False, 'diagnostics': diagnostics}
            raw_annotations[cid] = normalized
            if normalized['valid']:
                annotations[cid] = normalized
    return {'directory': directory, 'manifest': manifest, 'entries': entries, 'responses': records,
            'targets': {cid: c['target'] for cid, c in cases.items()}, 'annotations': annotations,
            'raw_annotations': raw_annotations, 'method': 'Qwen3-1.7B provisional LLM annotations'}


def development_annotation_example(run):
    """A fixed, previously audited pilot failure; no new model/reviewer labels."""
    cid = 'row-1289__no_history__ORIGINAL'
    audit = run['directory'] / 'agent_assisted_annotation_audit_v1'
    review = read(audit / 'reviewed_layer.json')
    snapshot = next(s for s in read(audit / 'source_snapshots.json') if s['call_id'] == cid)
    verification = read(audit / 'verification.json')
    annotation = run['raw_annotations'][cid]
    record = annotation['record']
    response = run['responses'][cid]
    entry = run['entries'][cid]
    reviewed = review['records'][cid]
    if not review['review_label'] == 'agent-assisted' or verification['human_review_occurred']:
        raise ValueError('Pilot review provenance differs')
    if (snapshot['annotation_input'] != record['annotation_input']
            or snapshot['raw_annotation_response'] != record['raw_annotation_response']
            or snapshot['predictor_raw_response'] != response['response']['raw_response']):
        raise ValueError('Pilot source differs from the saved agent-assisted audit')
    for proposed in reviewed['proposed_claims']:
        if proposed['exact_quote'] not in record['annotation_input']['explanation']:
            raise ValueError('Pilot review quotation no longer matches the explanation')
    paths = [run['directory'] / 'annotations' / (cid + '.json'),
             run['directory'] / 'responses' / (cid + '.json'),
             audit / 'reviewed_layer.json', audit / 'source_snapshots.json', audit / 'verification.json']
    hashes = {str(p.relative_to(ROOT)): hash_file(p) for p in paths}
    for name in (reviewed['annotation_file'], reviewed['source_response_file']):
        if hashes[name] != verification['protected_sha256'][name]:
            raise ValueError('Pilot raw source changed since the audit: ' + name)
    return {'call_id': cid, 'entry': entry, 'response': response, 'annotation': annotation,
            'review': reviewed, 'review_label': 'agent-assisted', 'human_reviewed': False,
            'selection_reason': 'Illustrative failure already identified in the saved six-record development audit; not a representative sample or a matched comparison with the Test example.',
            'source_sha256': hashes}


def load_luna(run, snapshot):
    snapshot = Path(snapshot)
    provenance = read(snapshot / 'snapshot_provenance.json')
    manifest = read(snapshot / 'annotation_manifest.json')
    if manifest['study_plan_id'] != run['manifest']['plan_id']:
        raise ValueError('Annotation snapshot belongs to a different run')
    if digest({k: v for k, v in manifest.items() if k != 'annotation_manifest_id'}) != manifest['annotation_manifest_id']:
        raise ValueError('Annotation manifest seal mismatch')
    annotations = {}
    all_records = {}
    exclusions = []
    for path in sorted((snapshot / 'records').glob('*.json')):
        record = read(path)
        cid = record['source_response_id']
        if cid not in run['responses'] or cid in all_records:
            raise ValueError('Duplicate or unrelated annotation: ' + cid)
        if hash_file(path) != provenance['records'][cid]['sha256']:
            raise ValueError('Annotation snapshot content changed')
        job = read(STUDY / 'luna_all_742_v1/jobs' / f'{cid}.json')
        source_hash = hash_file(STUDY / 'responses' / f'{cid}.json')
        if record['source_response_sha256'] != source_hash or job['source_response_sha256'] != source_hash or record['exact_request'] != job['request']:
            raise ValueError('Annotation response hash/request linkage differs')
        if record['requested_settings'] != manifest['settings'] or record['requested_model'] != 'gpt-6-luna':
            raise ValueError('Annotation model/settings differ')
        api = json.loads(record['raw_api_response'])
        # The reused original canonical job ID differs, but request/schema/source
        # definitions are identical. Validate against this batch job's exact input.
        parsed, diagnostics = validate_batch_result(record['raw_annotation_response'], job, api)
        if parsed != record['parsed_annotation'] or diagnostics != record['validation']:
            raise ValueError('Saved Luna annotations/diagnostics changed')
        normalized = {'claims': parsed.get('claims', []) if isinstance(parsed, dict) else [],
            'rules': parsed.get('rules', []) if isinstance(parsed, dict) else [],
            'annotation_id': record['annotation_id'], 'record': record, 'raw_record': record,
            'method': 'GPT-6 Luna automated annotation', 'valid': diagnostics['schema_and_traceability_ok'],
            'coverage_complete': diagnostics['model_reports_claim_coverage_complete'], 'diagnostics': diagnostics,
            'source_explanation': job['source_explanation'], 'job': job}
        all_records[cid] = normalized
        if normalized['valid'] and job['source_explanation']['status'] == 'complete':
            annotations[cid] = normalized
        else:
            exclusions.append({'response_id': cid, 'status': record['status'], 'issues': diagnostics['issues'],
                'source_status': job['source_explanation']['status']})
    return annotations, all_records, exclusions


def matched_influence(annotation, family, patch):
    if annotation is None:
        return {'classification': 'unassessable', 'reason': 'No traceable matching original annotation.', 'evidence': []}
    changed = {p['field'] for p in patch}
    matching = []
    broad = False
    group = 'CURRENT_PRICES' if family == 'CURRENT_PRICE' else 'CURRENT_ADVERTISING' if family == 'CURRENT_ADVERTISING' else 'HOUSEHOLD_HISTORY'
    for claim in annotation['claims']:
        refs = set(claim.get('source_fields', []))
        rel = claim.get('relationship_type')
        if refs & changed:
            matching.append(claim)
        elif family == 'SUPPORT_PURCHASE' and rel == 'support_purchase_frequency':
            matching.append(claim)  # Frequency depends on the purchase labels as a set.
        elif group in claim.get('concept_groups', []) and not refs:
            broad = True
    roles = {c['claimed_role'] for c in matching}
    if roles & {'decisive', 'contributing'}:
        label = 'yes'
    elif broad or 'unclear' in roles:
        label = 'unclear'
    elif matching:
        label = 'no'
    elif annotation['coverage_complete']:
        label = 'no'
    else:
        label = 'unassessable'
    return {'classification': label, 'evidence': matching,
        'reason': 'Changed-field or support-frequency dependency match; influence labels are separate from factual labels.'}


def assess_rule(pair, annotation, run):
    if annotation is None:
        return {'assessable': False, 'reason': 'No matching, traceable original rule annotation.'}
    rules = annotation['rules']
    if len(rules) != 1:
        return {'assessable': False, 'reason': 'No unique saved explicit rule with an evaluable template.'}
    rule = rules[0]
    claims = {c['claim_id']: c for c in annotation['claims']}
    if not (rule.get('explicit') and rule.get('sufficiently_specified') and rule.get('eligible_for_counterfactual_testing')):
        return {'assessable': False, 'reason': rule.get('eligibility_reason', 'Rule eligibility not established.')}
    if rule['rule_type'] != 'choose_uniquely_cheapest_current_product' or rule['scope'] != 'all_current_candidates':
        return {'assessable': False, 'reason': 'The existing evaluator does not implement this rule type/conditions.'}
    linked = [claims[c] for c in rule['claim_ids'] if c in claims and claims[c]['claimed_role'] == 'decisive']
    if len(linked) != 1:
        return {'assessable': False, 'reason': 'A contributing or ambiguous reason is not an absolute deciding rule.'}
    conditions = rule['conditions']
    if len(conditions) != 2 or not any('availab' in c.lower() for c in conditions) or not any('unique' in c.lower() for c in conditions):
        return {'assessable': False, 'reason': 'Additional rule conditions require review; no implication was invented.'}
    if rule['factual_premises_status'] != 'valid':
        return {'assessable': False, 'reason': 'Required rule premises are not established valid.'}
    projected = deepcopy(linked[0])
    projected['rule_specification'] = {'template': rule['rule_type'], 'premise_claim_ids': rule['premise_claim_ids']}
    # The legacy template requires the premise claims and one decisive claim.
    others = [deepcopy(c) for c in annotation['claims'] if c['claimed_role'] != 'decisive']
    result = rule_assessment(pair, {'annotation_id': annotation['annotation_id'], 'claims': others + [projected]}, run)
    result['saved_rule'] = rule
    return result


def annotation_facts(annotations, ids):
    selected = [annotations[cid] for cid in ids if cid in annotations]
    statuses = Counter(c['factual_status'] for a in selected for c in a['claims'])
    return {**rate(statuses['contradicted'], statuses['supported'] + statuses['contradicted']),
        'response_coverage': rate(len(selected), len(ids)), 'claim_status_counts': dict(statuses),
        'annotations': len(selected), 'source_responses': len(ids)}


def annotation_label_inventory(run, condition='with_history'):
    """Count saved claim labels once per response; quarantine excluded records.

    Multi-label concepts/directions count a claim once per assigned label. Direction
    identifiers are decoded with the response's own mapping to retain products.
    """
    entries = {cid: e for cid, e in run['entries'].items()
               if e['condition'] == condition and cid in run['responses']}
    names = {c['id']: c['name'].capitalize() for e in entries.values()
             for c in e['original_source']['candidates']}
    domains = {'factual_status': sorted(STATUSES), 'claimed_role': sorted(ROLES),
        'concept_groups': list(GROUPS) + ['no_concept_group'],
        'relationship_type': sorted(RELATIONSHIPS),
        'direction': [f'{kind}:{cid}' for kind in ('favors', 'disfavors') for cid in sorted(names)] + ['no_stated_direction'],
        'temporal_scope': ['current_edited', 'explicit_original_reference', 'general_or_influence', 'unclear', 'not_annotated'],
        'stale_status': ['stale', 'not_stale', 'unassessable', 'not_applicable', 'not_annotated']}
    raw = run['raw_annotations']
    layers = {'eligible': {cid: run['annotations'][cid] for cid in entries if cid in run['annotations']},
              'excluded': {cid: raw[cid] for cid in entries if cid in raw and cid not in run['annotations']}}

    def count_row(family, ids, annotations):
        counts = {key: Counter() for key in domains}
        claims_total = 0
        for cid in ids:
            inverse = {v: k for k, v in entries[cid]['presentation']['answer_mapping'].items()}
            for claim in annotations[cid]['claims']:
                claims_total += 1
                for key in ('factual_status', 'claimed_role', 'relationship_type'):
                    counts[key][claim.get(key, 'not_recorded')] += 1
                counts['concept_groups'].update(set(claim.get('concept_groups', [])) or {'no_concept_group'})
                direction = claim.get('direction') or {}
                directions = {f'{kind}:{inverse.get(answer, answer)}' for kind in ('favors', 'disfavors')
                              for answer in direction.get(kind, [])}
                counts['direction'].update(directions or {'no_stated_direction'})
                comparison = claim.get('comparison_assessment') or {}
                for key in ('temporal_scope', 'stale_status'):
                    counts[key][comparison.get(key, 'not_annotated')] += 1
        return {'family': family, 'responses': len(ids), 'claims': claims_total,
                'counts': {key: dict(value) for key, value in counts.items()}}

    output = {}
    for layer, annotations in layers.items():
        rows = [count_row(family, [cid for cid in annotations if entries[cid]['family'] == family], annotations)
                for family in ('ORIGINAL',) + FAMILIES]
        rows += [count_row('ALL_EDITED', [cid for cid in annotations if entries[cid]['family'] != 'ORIGINAL'], annotations),
                 count_row('ALL_DISTINCT', list(annotations), annotations)]
        output[layer] = rows
        for row in rows:
            for key, counts in row['counts'].items():
                domains[key] += sorted(set(counts) - set(domains[key]))
    return {'domains': domains, 'candidate_names': names, 'layers': output,
            'unit': 'Saved claims within distinct responses; original claims are counted once, not repeated for each edit.',
            'multi_label_note': 'A claim can have several concepts or directions; those columns can sum above the claim count.',
            'excluded_note': 'Excluded-record counts are an audit inventory of raw labels, not eligible metric evidence.'}


def stale_metrics(annotations, edited_ids):
    eligible = []
    response_assessed = response_stale = 0
    claims_total = 0
    exclusions = Counter()
    for cid in edited_ids:
        annotation = annotations.get(cid)
        if not annotation:
            continue
        claims = annotation['claims']
        claims_total += len(claims)
        comparisons = [c.get('comparison_assessment') for c in claims]
        any_stale = any(isinstance(c, dict) and c['stale_status'] == 'stale' for c in comparisons)
        complete = bool(comparisons) and all(isinstance(c, dict) and c['stale_status'] != 'unassessable' for c in comparisons)
        if any_stale or complete:
            response_assessed += 1
            response_stale += any_stale
        for claim in claims:
            comparison = claim.get('comparison_assessment')
            if not isinstance(comparison, dict):
                exclusions['No edited comparison labels'] += 1
            elif comparison['temporal_scope'] != 'current_edited':
                exclusions['Not asserted as current edited information'] += 1
            elif comparison['stale_status'] not in ('stale', 'not_stale'):
                exclusions['Staleness not assessable/applicable'] += 1
            else:
                eligible.append(claim)
    return {'claims': {**rate(sum(c['comparison_assessment']['stale_status'] == 'stale' for c in eligible), len(eligible)),
                'annotation_coverage': rate(sum(cid in annotations for cid in edited_ids), len(edited_ids)),
                'eligible_coverage': rate(len(eligible), claims_total), 'exclusion_reasons': dict(exclusions)},
            'responses': {**rate(response_stale, response_assessed), 'assessment_coverage': rate(response_assessed, len(edited_ids))}}


def conditional_change_counts(pairs):
    """Expose the existing report classifications without reclassifying claims."""
    rows = []
    count_keys = ('yes_changed', 'yes_unchanged', 'no_changed', 'no_unchanged',
                  'unclear_excluded', 'unassessable_excluded', 'invalid_prediction_pairs_excluded')
    for family in FAMILIES[:6]:
        applicable = [p for p in pairs if p['family'] == family and p['applicable']]
        valid = [p for p in applicable if p['valid_prediction_comparison']]
        counts = {f'{label}_{outcome}': sum(p['influence']['classification'] == label
                    and p['prediction_changed'] == changed for p in valid)
                  for label in ('yes', 'no') for outcome, changed in (('changed', True), ('unchanged', False))}
        rows.append({'family': family, 'valid_prediction_pairs': len(valid), **counts,
            'unclear_excluded': sum(p['influence']['classification'] == 'unclear' for p in valid),
            'unassessable_excluded': sum(p['influence']['classification'] == 'unassessable' for p in valid),
            'invalid_prediction_pairs_excluded': len(applicable) - len(valid)})
    overall = {'family': 'OVERALL_PAIR_WEIGHTED',
               'valid_prediction_pairs': sum(r['valid_prediction_pairs'] for r in rows),
               **{key: sum(r[key] for r in rows) for key in count_keys}}
    for row in rows + [overall]:
        row['p_change_given_claimed_influence'] = rate(row['yes_changed'], row['yes_changed'] + row['yes_unchanged'])
        row['p_change_given_no_influence_asserted'] = rate(row['no_changed'], row['no_changed'] + row['no_unchanged'])
    return rows, overall


def cohort(run, condition):
    entries = {cid: e for cid, e in run['entries'].items() if e['condition'] == condition}
    originals = {e['case_id']: e for e in entries.values() if e['family'] == 'ORIGINAL'}
    if not originals:
        return None
    annotations = run['annotations']
    correct = evaluated = 0
    for case, entry in originals.items():
        product = decode(run['responses'].get(entry['call_id']), entry)
        if product is not None and case in run['targets']:
            evaluated += 1
            correct += product == run['targets'][case]
    result = {'accuracy': {**rate(correct, evaluated), 'coverage': rate(evaluated, len(originals))},
              'method': run['method'], 'families': {}, 'pairs': [], 'influence_match_differences': []}
    for family in FAMILIES:
        these = [e for e in entries.values() if e['family'] == family]
        pairs = []
        for edited in these:
            original = originals[edited['case_id']]
            a = decode(run['responses'].get(original['call_id']), original)
            b = decode(run['responses'].get(edited['call_id']), edited) if not edited['skip_reason'] else None
            valid = not edited['skip_reason'] and a is not None and b is not None
            pair = {'case_id': edited['case_id'], 'family': family, 'original_response_id': original['call_id'],
                'edited_response_id': edited['call_id'], 'original_product_id': a, 'edited_product_id': b,
                'applicable': not bool(edited['skip_reason']), 'skip_reason': edited['skip_reason'],
                'valid_prediction_comparison': valid, 'prediction_changed': a != b if valid else None,
                'exact_patch': edited.get('patch', [])}
            annotation = annotations.get(original['call_id'])
            pair['influence'] = matched_influence(annotation, family, edited.get('patch', [])) if family in FAMILIES[:6] else {'classification': 'unassessable', 'reason': 'Presentation control; separate invariance metric.', 'evidence': []}
            if family in FAMILIES[:6]:
                archived = influence(annotation, family, edited.get('patch', []))
                if archived['classification'] != pair['influence']['classification']:
                    result['influence_match_differences'].append({'response_id': edited['call_id'], 'archived_match': archived['classification'], 'report_match': pair['influence']['classification']})
            pair['rule'] = assess_rule(pair, annotation, run) if family in FAMILIES[:6] and valid else {'assessable': False, 'reason': 'Not an assessable substantive pair.'}
            pairs.append(pair)
        valid = [p for p in pairs if p['valid_prediction_comparison']]
        claimed = [p for p in valid if p['influence']['classification'] == 'yes']
        not_claimed = [p for p in valid if p['influence']['classification'] == 'no']
        result['families'][family] = {'change': rate(sum(p['prediction_changed'] for p in valid), len(valid)),
            'invariance': rate(sum(not p['prediction_changed'] for p in valid), len(valid)),
            'p_claimed': rate(sum(p['prediction_changed'] for p in claimed), len(claimed)),
            'p_not_claimed': rate(sum(p['prediction_changed'] for p in not_claimed), len(not_claimed)),
            'annotation_coverage': rate(sum(p['original_response_id'] in annotations for p in valid), len(valid)),
            'classification_coverage': rate(len(claimed) + len(not_claimed), len(valid)),
            'valid_pairs': len(valid), 'applicable': sum(p['applicable'] for p in pairs),
            'skips': Counter(p['skip_reason'] for p in pairs if p['skip_reason'])}
        result['pairs'].extend(pairs)
    substantive = [p for p in result['pairs'] if p['family'] in FAMILIES[:6] and p['valid_prediction_comparison']]
    for key, label in (('p_claimed', 'yes'), ('p_not_claimed', 'no')):
        selected = [p for p in substantive if p['influence']['classification'] == label]
        result[key] = {**rate(sum(p['prediction_changed'] for p in selected), len(selected)),
            'annotation_coverage': rate(sum(p['original_response_id'] in annotations for p in substantive), len(substantive)),
            'classification_coverage': rate(sum(p['influence']['classification'] in ('yes', 'no') for p in substantive), len(substantive))}
    assessed = [p for p in substantive if p['rule'].get('assessable')]
    result['rule'] = {**rate(sum(p['rule']['consistent'] for p in assessed), len(assessed)), 'assessment_coverage': rate(len(assessed), len(substantive))}
    original_ids = [e['call_id'] for e in originals.values()]
    edited_ids = [e['call_id'] for e in entries.values() if e['family'] in FAMILIES and not e['skip_reason'] and e['call_id'] in run['responses']]
    result['facts_original'] = annotation_facts(annotations, original_ids)
    result['facts_edited'] = annotation_facts(annotations, edited_ids)
    result['conditional_change_by_family'], result['conditional_change_overall_pair_weighted'] = conditional_change_counts(result['pairs'])
    available_originals = [cid for cid in original_ids if cid in run['responses']]
    available_ids = available_originals + edited_ids
    raw_annotations = run.get('raw_annotations', annotations)
    result['annotation_coverage'] = {
        'linked_originals': sum(cid in annotations for cid in available_originals),
        'original_responses': len(available_originals),
        'linked_edited': sum(cid in annotations for cid in edited_ids), 'edited_responses': len(edited_ids),
        'linked_total': sum(cid in annotations for cid in available_ids), 'distinct_responses': len(available_ids),
        'excluded_annotation_sources': sum(cid in raw_annotations and cid not in annotations for cid in available_ids),
        'missing_annotations': sum(cid not in raw_annotations for cid in available_ids)}
    stale = stale_metrics(annotations, edited_ids)
    result['stale_claims'], result['stale_responses'] = stale['claims'], stale['responses']
    return result


def select_example(run, config_path):
    config_path = Path(config_path)
    if config_path.exists():
        config = read(config_path)
        if config['study_plan_id'] != run['manifest']['plan_id']:
            raise ValueError('Presentation configuration belongs to another run')
        return config
    choices = []
    for entry in run['entries'].values():
        if entry['family'] != 'ORIGINAL':
            continue
        edits = [e for e in run['entries'].values() if e['case_id'] == entry['case_id'] and e['family'] in FAMILIES and not e['skip_reason']]
        complete = sum(decode(run['responses'].get(e['call_id']), e) is not None for e in [entry] + edits)
        choices.append((-complete, -len(edits), int(entry['case_id'].removeprefix('row-')), entry['case_id']))
    chosen = sorted(choices)[0][-1]
    config = {'version': 'actual-experiment-presentation-v1', 'study_plan_id': run['manifest']['plan_id'],
              'example_case_id': chosen, 'selection_rule': 'Maximum complete decodable saved original+edited records, then maximum applicable intervention families, then smallest numeric query ID. No correctness, explanation quality, annotation labels or prediction-change outcome is consulted.'}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2) + '\n')
    return config


def legacy_accuracy(snapshot):
    from .storage import load_run as load_legacy
    manifest, cases, data = load_legacy(snapshot)
    results = {}
    for split in SPLITS:
        results[split] = {}
        for condition in CONDITIONS:
            rows = [p for p in data['predictions'] if p['split'] == split and p['condition'] == condition]
            total = sum(c['split'] == split for c in cases)
            good = [r for r in rows if r.get('prediction') is not None and r.get('outcome') is not None]
            if any(r['correct'] != (r['prediction'] == r['outcome']) for r in good):
                raise ValueError('Earlier workflow correctness label mismatch')
            results[split][condition] = {**rate(sum(r['prediction'] == r['outcome'] for r in good), len(good)),
                                       'coverage': rate(len(good), total)}
    return results, {'manifest': manifest, 'cases': len(cases), 'record_counts': {k: len(v) for k, v in data.items()}}


def assemble(luna_snapshot, legacy_snapshot, config_path):
    test = load_run(STUDY)
    annotations, all_annotations, exclusions = load_luna(test, luna_snapshot)
    test.update(annotations=annotations, raw_annotations=all_annotations, method='GPT-6 Luna automated annotations')
    development = load_development()
    pilot_example = development_annotation_example(development)
    metrics = {'development': {c: cohort(development, c) for c in CONDITIONS},
               'validation': {c: None for c in CONDITIONS},
               'test': {'no_history': None, 'with_history': cohort(test, 'with_history')}}
    accuracy, families, invariance, _ = prediction_metrics(test)
    assert metrics['test']['with_history']['accuracy']['numerator'] == accuracy['numerator']
    for family in families:
        assert metrics['test']['with_history']['families'][family['family']]['change'] == family['change_rate']
    old, old_info = legacy_accuracy(legacy_snapshot)
    config = select_example(test, config_path)
    cid = config['example_case_id']
    example_entries = {e['family']: e for e in test['entries'].values() if e['case_id'] == cid}
    example_records = {f: test['responses'].get(e['call_id']) for f, e in example_entries.items()}
    example_annotations = {f: all_annotations.get(e['call_id']) for f, e in example_entries.items()}
    example_pairs = {p['family']: p for p in metrics['test']['with_history']['pairs'] if p['case_id'] == cid}
    return {'metrics': metrics, 'legacy_accuracy': old, 'legacy_info': old_info, 'config': config,
        'annotation_label_inventory': annotation_label_inventory(test),
        'development_annotation_example': pilot_example,
        'example': {'entries': example_entries, 'records': example_records, 'annotations': example_annotations,
                    'pairs': example_pairs, 'target': test['targets'][cid], 'model': read(STUDY / 'execution_config.json')['runtime']['model']},
        'annotation_snapshot': str(Path(luna_snapshot).relative_to(ROOT)), 'legacy_snapshot': str(Path(legacy_snapshot).relative_to(ROOT)),
        'annotation_exclusions': exclusions, 'all_annotation_records': len(all_annotations),
        'valid_annotation_records': len(annotations), 'method_notes': METHOD_NOTES,
        'protected_source_hashes': {**test['protected'], **pilot_example['source_sha256']}, 'model_calls': 0}
