"""Predefined sensitivity grids and separately identified explanation tests."""
import copy
import math
import random
from collections import Counter
from .schema import masked, visible_evidence
from experiment import digest


def edit(case,evidence_id,value):
    result=copy.deepcopy(case)
    evidence={e['id']:e for e in result['evidence']}
    e=evidence.get(evidence_id)
    if not e or not e['editable']: return None,'Evidence is not editable'
    if value==e['value']: return None,'No change in value'
    policy=e.get('policy',{})
    kind=policy.get('kind')
    if kind=='numeric':
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value): return None,'Expected finite numeric value'
        bounds=policy.get('development_bounds')
        if not bounds: return None,'Development support unavailable'
        lower=max(bounds[0],policy.get('min',bounds[0])); upper=min(bounds[1],policy.get('max',bounds[1]))
        if not lower<=value<=upper: return None,'Outside development/declared bounds'
    elif kind=='categorical':
        if value not in policy.get('values',[]): return None,'Value is not an admissible categorical alternative'
    else: return None,'No supported edit policy'
    e['value']=value
    # Adapter constraints: comparisons between named attributes of the same candidate.
    for constraint in result.get('constraints',[]):
        if constraint.get('op') not in ('le','lt','ge','eq','ne'):
            return None,'Unsupported cross-field constraint'
        for c in result['candidates']:
            attrs=c.get('attributes',{})
            if constraint['left'] not in attrs or constraint['right'] not in attrs:
                return None,'Constraint attribute missing'
            a=evidence[attrs[constraint['left']]]['value']; b=evidence[attrs[constraint['right']]]['value']
            try: valid={'le':lambda:a<=b,'lt':lambda:a<b,'ge':lambda:a>=b,'eq':lambda:a==b,'ne':lambda:a!=b}[constraint['op']]()
            except TypeError: valid=False
            if not valid: return None,'Cross-field constraint violated'
    result['outcome']=None
    return result,None


def systematic(case,condition,seed=42,permutations=2):
    facts=visible_evidence(case,condition)
    specs=[]
    for eid,e in facts.items():
        if not e['editable']: continue
        policy=e.get('policy',{})
        kind=policy.get('kind')
        values=policy.get('values',[]) if kind=='categorical' else policy.get('grid',[])
        if kind=='numeric' and not values: values=[e['value']*v for v in policy.get('multipliers',[.8,1.2])]
        if not values:
            specs.append(dict(kind='attribute_sweep',evidence_ids=[eid],value=None,skip_reason='No predefined edit grid'))
        for value in values:
            if value!=e['value']: specs.append(dict(kind='attribute_sweep' if kind=='numeric' else 'categorical_toggle',evidence_ids=[eid],value=value))
    histories=[eid for eid,e in facts.items() if e['type']=='history']
    specs.append(dict(kind='history_mask',evidence_ids=histories,skip_reason=None if histories else 'No history evidence in condition'))
    ids=[c['id'] for c in case['candidates']]
    seen=set()
    rng=random.Random(int(digest([seed,case['case_id'],'order'])[:8],16))
    for _ in range(permutations):
        order=ids[:]; rng.shuffle(order)
        if order==ids: order=order[1:]+order[:1]
        if tuple(order) in seen: continue
        seen.add(tuple(order))
        specs.append(dict(kind='presentation',evidence_ids=[],order=order))
    return specs


def eligible_explanation(explanation):
    """A completed, valid citation set is required only for explanation tests."""
    if not isinstance(explanation,dict): return False
    if (explanation.get('parse_ok') is not True or explanation.get('citation_valid') is not True
            or explanation.get('abstained') or explanation.get('truncated')):
        return False
    if 'citation_assessment' in explanation and not explanation['citation_assessment']['usable_for_evidence_interventions']:
        return False
    obj=explanation.get('parsed')
    ids=obj.get('evidence_ids') if isinstance(obj,dict) else None
    return (isinstance(ids,list) and len(ids)>=1
            and all(isinstance(eid,str) for eid in ids) and len(set(ids))==len(ids))


def explanation_tests(case,condition,explanation,random_controls,seed):
    facts=visible_evidence(case,condition)
    if (not eligible_explanation(explanation)
            or not set(explanation['parsed']['evidence_ids'])<=set(facts)):
        issues = (explanation or {}).get('citation_assessment', {}).get('issues', [])
        reason = '; '.join(issues) or 'Supporting citations unavailable, duplicated, missing, or response incomplete (see saved assessment)'
        return [dict(kind='cited_remove',evidence_ids=[],skip_reason=reason),
                dict(kind='cited_retain',evidence_ids=[],skip_reason=reason),
                dict(kind='explicit_claim',evidence_ids=[],skip_reason='No eligible original directional claim')]
    obj=explanation['parsed']; ids=obj['evidence_ids']
    specs=[dict(kind='cited_remove',evidence_ids=ids),dict(kind='cited_retain',evidence_ids=ids)]
    types=Counter(facts[i]['type'] for i in ids)
    rng=random.Random(int(digest([seed,case['case_id'],condition,'controls'])[:8],16))
    for i in range(random_controls):
        control=[]
        for role,n in sorted(types.items()):
            control+=rng.sample(sorted(k for k,e in facts.items() if e['type']==role),n)
        specs += [dict(kind='random_remove',evidence_ids=control,control=i),dict(kind='random_retain',evidence_ids=control,control=i)]
    claim=obj.get('counterfactual')
    if (isinstance(claim,dict) and not explanation.get('claim_error')
            and claim.get('evidence_id') in ids and 'value' in claim
            and claim.get('expected_direction') in ('increase','decrease')):
        specs.append(dict(kind='explicit_claim',evidence_ids=[claim['evidence_id']],value=claim['value'],expected_direction=claim['expected_direction']))
    else: specs.append(dict(kind='explicit_claim',evidence_ids=[],skip_reason=explanation.get('claim_error') or 'No original directional claim'))
    return specs


def apply(case,spec):
    if spec.get('skip_reason'): return None,spec['skip_reason']
    kind=spec['kind']
    if kind in ('attribute_sweep','categorical_toggle','explicit_claim'):
        return edit(case,spec['evidence_ids'][0],spec['value'])
    if kind in ('cited_remove','random_remove','history_mask'): return masked(case,set(spec['evidence_ids'])),None
    if kind in ('cited_retain','random_retain'): return masked(case,set(spec['evidence_ids']),keep=True),None
    if kind=='presentation':
        ids=[candidate['id'] for candidate in case['candidates']]
        order=spec.get('order')
        if not isinstance(order,list) or len(order)!=len(ids) or set(order)!=set(ids):
            return None,'Presentation order must retain every candidate exactly once'
        changed=copy.deepcopy(case); changed['outcome']=None
        return changed,None
    return None,'Unknown intervention'


def measurements(original,after):
    chosen=original['prediction']
    scores=original.get('scores'); edited=after.get('scores') if after else None
    rival=sorted((k for k in scores if k!=chosen),key=lambda k:(-scores[k],k))[0] if scores else None
    delta=edited[chosen]-scores[chosen] if scores is not None and edited is not None else None
    margin_delta=None
    if delta is not None and rival:
        log=lambda x:math.log(max(x,1e-12))
        margin_delta=(log(edited[chosen])-log(edited[rival]))-(log(scores[chosen])-log(scores[rival]))
    return dict(reference_candidate=chosen,fixed_rival=rival,score_change=delta,margin_change=margin_delta,
                winner_changed=after['prediction']!=chosen if after else None,
                scores_unavailable_reason=None if delta is not None else 'No numerical scores or intervention skipped')


def planned_specs(case, condition, explanation, random_controls, seed, permutations, suite='all'):
    """Select execution scope without changing intervention definitions or IDs."""
    grid = systematic(case, condition, seed, permutations)
    if suite == 'systematic':
        return grid
    checks = explanation_tests(case, condition, explanation, random_controls, seed)
    if suite == 'explanation':
        return checks + [spec for spec in grid if spec['kind'] == 'presentation']
    if suite != 'all':
        raise ValueError('Unknown intervention suite')
    return grid + checks
