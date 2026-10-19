"""Adapters are explicit data contracts, not automatic leakage detectors."""
from __future__ import annotations
import csv
import json
import random
from collections import defaultdict
from pathlib import Path
from .schema import validate_cases
from experiment import digest, read_jsonl


def fact(eid, value, role, source, *, candidate=None, units=None, editable=False, **extra):
    return dict(id=eid, value=value, type=role, source=source, candidate_id=candidate,
                units=units, editable=editable, pre_decision=True, **extra)


def yogurt(rows, source_manifest=None):
    cases = []
    allocations = (source_manifest or {}).get('household_allocation', {})
    for r in rows:
        facts, candidates = [], []
        for cid, name in r['brand_map'].items():
            candidates.append(dict(id=cid, name=name, attributes={'price': 'P_'+cid, 'advertised': 'F_'+cid}))
            facts += [fact('P_'+cid, r['query']['prices'][cid], 'price', 'current offer', candidate=cid,
                           units='original dataset units', editable=True, policy={'kind': 'numeric', 'multipliers': [.8, 1.2]}),
                      fact('F_'+cid, r['query']['ads'][cid], 'ad', 'current offer', candidate=cid,
                           editable=True, policy={'kind': 'categorical', 'values': [False, True]})]
        support_rows = allocations.get(str(r['household_id']), {}).get('support_source_rows', [])
        for i, h in enumerate(r['support']):
            facts.append(fact(h['evidence_id'], {k: h[k] for k in ('prices', 'ads', 'choice')}, 'history',
                              'separate support observation; chronology unknown',
                              observation_id='row-'+str(support_rows[i]) if i < len(support_rows) else
                              f"support-{r['household_id']}-{h['evidence_id']}", editable=False))
        cases.append(dict(schema_version=2, case_id=r['case_id'], dataset_id='yogurt', task='purchase',
                          candidates=candidates, evidence=facts, outcome=r.get('target'),
                          group_id=str(r['household_id']), split=r['split'], time=None,
                          synthetic=bool(r.get('synthetic')), constraints=[],
                          task_note='Purchase conditional on these four brands. No dates; support is unordered.'))
    return validate_cases(cases)


def parse_value(value, kind):
    if kind == 'number':
        return float(value)
    if kind == 'boolean':
        if value in (True, 'true', 'True', '1', 1): return True
        if value in (False, 'false', 'False', '0', 0): return False
        raise ValueError(f'Invalid boolean {value!r}')
    if kind == 'json' and isinstance(value, str): return json.loads(value)
    return value


def assign_splits(cases, config):
    if all(c.get('split') for c in cases): return
    if any(c.get('split') for c in cases): raise ValueError('Partial split assignments are prohibited')
    groups = defaultdict(list)
    for c in cases: groups[c.get('group_id') or c['case_id']].append(c)
    keys = sorted(groups)
    strategy = config.get('split_strategy', 'group')
    if strategy == 'temporal':
        # ISO-8601 dates supplied by adapter; never infer time from row order.
        from datetime import datetime
        def stamp(c):
            if not c.get('time'): raise ValueError('Temporal split requires explicit ISO-8601 times')
            return datetime.fromisoformat(c['time'].replace('Z', '+00:00'))
        keys.sort(key=lambda g: min(stamp(c) for c in groups[g]))
    elif strategy == 'group':
        random.Random(config.get('seed', 42)).shuffle(keys)
    else: raise ValueError('split_strategy must be group or temporal')
    if len(keys) < 3: raise ValueError('Need >=3 groups for automatic splits; supply explicit splits otherwise')
    ndev = min(len(keys)-2, max(1, int(.6*len(keys))))
    nval = min(len(keys)-ndev-1, max(1, int(.2*len(keys))))
    for i, key in enumerate(keys):
        split = 'development' if i < ndev else 'validation' if i < ndev+nval else 'test'
        for c in groups[key]: c['split'] = split
    if strategy == 'temporal':
        intervals = {s: [stamp(c) for c in cases if c['split']==s] for s in ('development','validation','test')}
        if max(intervals['development']) >= min(intervals['validation']) or max(intervals['validation']) >= min(intervals['test']):
            raise ValueError('Groups span temporal boundaries; supply defensible disjoint time/group partitions')


def generic(source: Path, config):
    adapter = config.get('adapter', 'product')
    if config.get('pre_decision_reviewed') is not True:
        raise ValueError('Config must attest pre_decision_reviewed=true for allowlisted input fields')
    rows = list(csv.DictReader(source.open(newline='', encoding='utf-8'))) if source.suffix == '.csv' else read_jsonl(source)
    fields = config.get('fields', {})
    field = lambda role: fields.get(role, role)
    target_field = field('outcome')
    input_columns = [a['column'] for a in config.get('attributes', [])+config.get('context', [])]
    input_columns += [field('text')] if adapter == 'text' else []
    if target_field in input_columns:
        raise ValueError('Outcome column cannot be an input evidence field')
    grouped = defaultdict(list)
    for row in rows: grouped[str(row[field('case_id')])].append(row)
    cases = []
    for cid, group in grouped.items():
        r = group[0]
        for role in ('outcome', 'group_id', 'split', 'time'):
            if len({json.dumps(x.get(field(role)), sort_keys=True) for x in group}) != 1:
                raise ValueError(f'Inconsistent {role} within complete case {cid}')
        facts, candidates = [], []
        if adapter == 'text':
            if len(group) != 1: raise ValueError('One row per text classification case required')
            candidates = [dict(id=str(x['id']), name=x['name'], attributes={}) for x in config['labels']]
            facts.append(fact('text', r[field('text')], 'text', field('text')))
        elif adapter == 'product':
            # CSV: long format; JSONL: one complete case with candidates array.
            products = r['candidates'] if len(group)==1 and 'candidates' in r else group
            for p in products:
                pid = str(p[field('candidate_id')])
                candidate = dict(id=pid, name=str(p[field('candidate_name')]), attributes={})
                for a in config.get('attributes', []):
                    if a['column'] not in p or p[a['column']] in ('', None): continue
                    eid = 'attr:'+pid+':'+a['name']
                    facts.append(fact(eid, parse_value(p[a['column']], a.get('dtype','text')), a.get('type',a['name']),
                                      a['column'], candidate=pid, units=a.get('units'), editable=a.get('editable',False),
                                      policy=a.get('policy', {}), attribute=a['name']))
                    candidate['attributes'][a['name']] = eid
                candidates.append(candidate)
        else: raise ValueError('Supported generic adapters: product, text')
        for a in config.get('context', []):
            if any(x.get(a['column']) != r.get(a['column']) for x in group):
                raise ValueError('Context must be constant within a choice occasion')
            if r.get(a['column']) not in ('',None):
                facts.append(fact('context:'+a['name'], parse_value(r[a['column']],a.get('dtype','text')),
                                  a.get('type','context'), a['column'], units=a.get('units'),
                                  editable=a.get('editable',False), policy=a.get('policy',{})))
        # History is explicit structured JSON, never inferred from query labels.
        history = r.get(field('history'), []) or []
        if isinstance(history,str): history=json.loads(history)
        for h in history:
            facts.append(fact('history:'+str(h['observation_id']), h['value'], 'history', 'separate observation',
                              observation_id=str(h['observation_id'])))
        outcome = r.get(target_field)
        cases.append(dict(schema_version=2, case_id=cid, dataset_id=config['dataset_id'],
                          task=config.get('task','classification' if adapter=='text' else 'purchase'),
                          candidates=candidates, evidence=facts, outcome=None if outcome in ('',None) else str(outcome),
                          group_id=str(r.get(field('group_id')) or cid), split=r.get(field('split')),
                          time=r.get(field('time')), synthetic=bool(config.get('synthetic',False)),
                          constraints=config.get('constraints',[]), task_note=config.get('task_note','')))
    assign_splits(cases,config)
    return validate_cases(cases)


def fit_policies(cases):
    """Numeric edit support learned only from development evidence of matching type/attribute."""
    values = defaultdict(list)
    for c in cases:
        if c['split'] != 'development': continue
        for e in c['evidence']:
            if e.get('policy',{}).get('kind')=='numeric':
                values[(e['type'],e.get('attribute'))].append(float(e['value']))
    for c in cases:
        for e in c['evidence']:
            policy=e.get('policy',{})
            if policy.get('kind')=='numeric':
                support=values.get((e['type'],e.get('attribute')),[])
                policy['development_bounds']=[min(support),max(support)] if support else None
    return cases


def prepare(source, out, config=None, adapter='generic'):
    from .storage import atomic_json, write_jsonl
    if out.exists(): raise ValueError('Prepared output already exists; choose a new directory')
    if adapter=='yogurt':
        mp=source.with_name('manifest.json')
        source_manifest=json.loads(mp.read_text()) if mp.exists() else None
        cases=yogurt(read_jsonl(source), source_manifest)
        configuration={'adapter':'yogurt','source_manifest':source_manifest}
    else:
        configuration=config
        cases=generic(source,config)
    if not cases: raise ValueError('Empty dataset')
    fit_policies(cases)
    out.mkdir(parents=True)
    write_jsonl(out/'cases.jsonl',cases)
    import hashlib
    atomic_json(out/'manifest.json',dict(schema_version=2, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        cases_hash=digest(cases), configuration=configuration,
        split_assignments={c['case_id']:c['split'] for c in cases},
        bounds_fitted_on='development', seed=(config or {}).get('seed',42)))
    return cases
