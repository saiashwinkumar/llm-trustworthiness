"""Strict common cases. Only allowlisted evidence enters prompts."""
from __future__ import annotations
import copy
import math

TASKS = {'purchase', 'click', 'rating_choice', 'sampled_candidate_ranking', 'classification'}
SPLITS = {'development', 'validation', 'test'}


def validate_case(case):
    if case.get('schema_version') != 2:
        raise ValueError('Expected case schema_version=2; use an adapter.')
    for key in ('case_id', 'dataset_id', 'task'):
        if not isinstance(case.get(key), str) or not case[key]:
            raise ValueError(f'Missing case field {key}')
    if case['task'] not in TASKS or case.get('split') not in SPLITS:
        raise ValueError('Unsupported task or split')
    candidates = case.get('candidates', [])
    ids = [c.get('id') for c in candidates]
    if len(ids) < 2 or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('Candidates need at least two distinct stable string IDs')
    for c in candidates:
        if set(c) - {'id', 'name', 'attributes'} or not isinstance(c.get('name'), str):
            raise ValueError('Candidate schema: id, name, attributes (evidence-ID mapping)')
    if case.get('outcome') is not None and case['outcome'] not in ids:
        raise ValueError('Outcome is not an available candidate')
    facts = case.get('evidence', [])
    evidence_ids = [e.get('id') for e in facts]
    if len(set(evidence_ids)) != len(facts):
        raise ValueError('Duplicate evidence IDs')
    for e in facts:
        if not isinstance(e.get('id'), str) or not e['id']:
            raise ValueError('Evidence needs a stable ID')
        if e.get('pre_decision') is not True:
            raise ValueError('Evidence must be explicitly marked pre_decision=true')
        if e.get('type') in {'outcome', 'target', 'post_decision'}:
            raise ValueError('Query outcome/post-decision evidence is prohibited')
        if not all(k in e for k in ('source', 'type', 'value', 'editable', 'units')):
            raise ValueError('Incomplete evidence metadata')
        if e.get('candidate_id') is not None and e['candidate_id'] not in ids:
            raise ValueError('Evidence references unavailable candidate')
        if e['type'] == 'history' and (not e.get('observation_id') or e['observation_id'] == case['case_id']):
            raise ValueError('History must identify a separate observation')
        if isinstance(e['value'], float) and not math.isfinite(e['value']):
            raise ValueError('Nonfinite evidence')
    by_id = {e['id']: e for e in facts}
    for c in candidates:
        for name, eid in c.get('attributes', {}).items():
            if eid not in by_id or by_id[eid].get('candidate_id') != c['id']:
                raise ValueError(f'Attribute {name} must reference that candidate’s evidence')
    return case


def validate_cases(cases):
    seen, groups = set(), {}
    for case in cases:
        validate_case(case)
        if case['case_id'] in seen:
            raise ValueError('Duplicate case ID')
        seen.add(case['case_id'])
        group = case.get('group_id') or case['case_id']
        key = (case['dataset_id'], group)
        if key in groups and groups[key] != case['split']:
            raise ValueError('Group overlap across splits')
        groups[key] = case['split']
    for case in cases:
        if any(e['type']=='history' and e['observation_id'] in seen for e in case['evidence']):
            raise ValueError('Query observations cannot be reused as history evidence')
    if len({c['dataset_id'] for c in cases}) > 1 or len({c['task'] for c in cases}) > 1:
        raise ValueError('Use separate prepared datasets for different dataset IDs or tasks')
    if len({bool(c.get('synthetic')) for c in cases}) > 1:
        raise ValueError('Do not mix synthetic and real cases')
    return cases


def visible_evidence(case, condition='full'):
    return {e['id']: e for e in case['evidence'] if condition != 'no_history' or e['type'] != 'history'}


def masked(case, ids, keep=False):
    result = copy.deepcopy(case)
    for e in result['evidence']:
        if (e['id'] not in ids) if keep else (e['id'] in ids):
            e['masked'] = True
    result['outcome'] = None
    return result
