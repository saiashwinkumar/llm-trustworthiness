"""Separate predictive quality, grounding, faithfulness and robustness estimates."""
import copy
import csv
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from .storage import load_run, atomic_json
from .scoring import normalize_log_scores
from .interventions import eligible_explanation
from .citations import response_issues


def estimate(pairs,bootstrap=500,seed=42):
    pairs=[(float(v),str(g)) for v,g in pairs if v is not None]
    groups=defaultdict(list)
    for v,g in pairs: groups[g].append(v)
    result=dict(mean=sum(v for v,g in pairs)/len(pairs) if pairs else None,n=len(pairs),groups=len(groups),ci95=None)
    if len(groups)>1:
        rng=random.Random(seed); keys=sorted(groups); values=[]
        sums={k:sum(groups[k]) for k in keys}
        for _ in range(bootstrap):
            selected=rng.choices(keys,k=len(keys))
            values.append(sum(sums[k] for k in selected)/sum(len(groups[k]) for k in selected))
        values.sort(); result['ci95']=[values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]]
    return result


def metric_rows(rows,bootstrap=500):
    eligible=[r for r in rows if r.get('outcome') is not None]
    scored=[r for r in eligible if r.get('scores') is not None]
    metrics=dict(n=len(eligible),unlabeled=len(rows)-len(eligible),scored_n=len(scored),
                 unavailable_scores=len(eligible)-len(scored))
    metrics['accuracy']=estimate([(r['prediction']==r['outcome'],r['group_id']) for r in eligible],bootstrap)
    losses,briers,mrr=[],[],[]
    for r in scored:
        p=r['scores']; y=r['outcome']; g=r['group_id']
        losses.append((-math.log(max(p[y],1e-12)),g))
        briers.append((sum((v-int(k==y))**2 for k,v in p.items()),g))
        rank=1+sum(v>p[y] for v in p.values())+(sum(v==p[y] for v in p.values())-1)/2
        mrr.append((1/rank,g))
    metrics.update(log_loss=estimate(losses,bootstrap),brier_sum=estimate(briers,bootstrap),mrr=estimate(mrr,bootstrap))
    bins=[]
    for i in range(5):
        selected=[r for r in scored if min(4,int(max(r['scores'].values())*5))==i]
        bins.append(dict(lower=i/5,upper=(i+1)/5,n=len(selected),
                         confidence=sum(max(r['scores'].values()) for r in selected)/len(selected) if selected else None,
                         accuracy=sum(r['prediction']==r['outcome'] for r in selected)/len(selected) if selected else None))
    metrics['calibration_bins']=bins
    metrics['ece_5']=sum(b['n']*abs(b['confidence']-b['accuracy']) for b in bins if b['n'])/len(scored) if scored else None
    thresholds=sorted({max(r['scores'].values()) for r in scored},reverse=True)
    # At most 20 measured cutoffs, including ties in full.
    thresholds=thresholds[::max(1,len(thresholds)//20)] + (thresholds[-1:] if thresholds else [])
    curve=[]
    for t in dict.fromkeys(thresholds):
        kept=[r for r in scored if max(r['scores'].values())>=t]
        curve.append(dict(threshold=t,n=len(kept),coverage=len(kept)/len(scored),
                          error=1-sum(r['prediction']==r['outcome'] for r in kept)/len(kept)))
    metrics['error_vs_coverage']=curve
    return metrics


def temperature_fit(rows):
    validation=[r for r in rows if r['split']=='validation' and r.get('scores') is not None and r.get('outcome') is not None]
    if not validation: return dict(temperature=None,n=0,status='Not measured: no scored validation outcomes')
    grid=[math.exp(-3+i*6/120) for i in range(121)]
    def loss(t):
        return sum(-math.log(max(temperature_scores(r['scores'],t)[r['outcome']],1e-12)) for r in validation)/len(validation)
    t=min(grid,key=loss)
    return dict(temperature=t,n=len(validation),status='Validation-only fixed log-temperature grid [-3,3], 121 points')


def temperature_scores(scores,t):
    return normalize_log_scores({k:math.log(max(v,1e-12))/t for k,v in scores.items()})


def baselines(rows,cases,bootstrap):
    development=[c for c in cases.values() if c['split']=='development' and c.get('outcome') is not None]
    popularity=Counter(c['outcome'] for c in development)
    predictions=[]; cheap=[]; history=[]; chance=[]
    for r in rows:
        c=cases[r['case_id']]; ids=[x['id'] for x in c['candidates']]
        if c.get('outcome') is None: continue
        chance.append((1/len(ids),r['group_id']))
        if development:
            scores={i:(popularity[i]+1)/sum(popularity[k]+1 for k in ids) for i in ids}
            predictions.append(dict(r,scores=scores,prediction=max(sorted(ids),key=scores.get)))
        prices={e['candidate_id']:e['value'] for e in c['evidence'] if e['type']=='price' and e.get('candidate_id')}
        if set(prices)==set(ids): cheap.append((min(sorted(ids),key=prices.get)==c['outcome'],r['group_id']))
        if r['condition']!='no_history':
            counts=Counter(e['value']['choice'] for e in c['evidence'] if e['type']=='history' and isinstance(e['value'],dict) and e['value'].get('choice') in ids)
            if counts:
                scores={i:(counts[i]+1)/(sum(counts.values())+len(ids)) for i in ids}
                history.append(dict(r,scores=scores,prediction=max(sorted(ids),key=scores.get)))
    return dict(uniform_chance=estimate(chance,bootstrap),development_popularity=metric_rows(predictions,bootstrap),
                cheapest_accuracy=estimate(cheap,bootstrap),support_frequency=metric_rows(history,bootstrap))


def explanation_metrics(predictions,explanations,interventions,bootstrap):
    by_prediction={p['record_id']:p for p in predictions}
    es=[e for e in explanations if e['prediction_id'] in by_prediction]
    ins=[r for r in interventions if r['prediction_id'] in by_prediction]
    result={}
    for name,criterion in [('all',lambda p:True),('correct',lambda p:p.get('correct') is True),('incorrect',lambda p:p.get('correct') is False)]:
        pids={k for k,p in by_prediction.items() if criterion(p)}
        ee=[e for e in es if e['prediction_id'] in pids]; ii=[i for i in ins if i['prediction_id'] in pids]
        group=dict(predictions=len(pids),explanations=len(ee),missing_explanations=len(pids)-len(ee),
                   invalid=sum(not e['parse_ok'] or not e['citation_valid'] for e in ee),abstentions=sum(e['abstained'] for e in ee),
                   truncations=sum(bool(e.get('truncated')) for e in ee),
                   coverage=estimate([(eligible_explanation(e),e['group_id']) for e in ee],bootstrap),metrics={})
        group['assessment_issues'] = dict(Counter(issue for e in ee for issue in response_issues(e)))
        group['prompt_versions'] = dict(Counter(e.get('prompt_version', 'historical: see run manifest') for e in ee))
        group['citation_policies'] = dict(Counter(e.get('citation_policy_version', 'historical: see original assessment') for e in ee))
        effects=defaultdict(list)
        valid_pids={e['prediction_id'] for e in ee if eligible_explanation(e)}
        dependent={'cited_remove','cited_retain','random_remove','random_retain','explicit_claim'}
        excluded=0
        for i in ii:
            if i['status']=='measured':
                kind=i['spec']['kind']
                if kind in dependent and i['prediction_id'] not in valid_pids:
                    excluded+=1
                    continue
                effects[kind].append(i)
        for kind,items in effects.items():
            group['metrics'][kind+'_score_change']=estimate([(i.get('score_change'),i['group_id']) for i in items],bootstrap)
            group['metrics'][kind+'_margin_change']=estimate([(i.get('margin_change'),i['group_id']) for i in items],bootstrap)
        group['metrics']['presentation_flip']=estimate([(i.get('winner_changed'),i['group_id']) for i in effects['presentation']],bootstrap)
        group['metrics']['explicit_claim_agreement']=estimate([(i.get('claim_agreement'),i['group_id']) for i in effects['explicit_claim']],bootstrap)
        # Paired case-level removal advantage avoids counting each random control as an independent case.
        advantage=[]; margin_adv=[]; retention=[]
        for pid in pids:
            cited=[i for i in effects['cited_remove'] if i['prediction_id']==pid and i.get('score_change') is not None]
            controls=[i for i in effects['random_remove'] if i['prediction_id']==pid and i.get('score_change') is not None]
            if cited and controls:
                advantage.append((-cited[0]['score_change']+sum(x['score_change'] for x in controls)/len(controls),by_prediction[pid]['group_id']))
                if cited[0].get('margin_change') is not None and all(x.get('margin_change') is not None for x in controls):
                    margin_adv.append((-cited[0]['margin_change']+sum(x['margin_change'] for x in controls)/len(controls),by_prediction[pid]['group_id']))
            retention += [(abs(i['score_change']),i['group_id']) for i in effects['cited_retain'] if i['prediction_id']==pid and i.get('score_change') is not None]
        group['metrics']['removal_advantage']=estimate(advantage,bootstrap)
        group['metrics']['margin_advantage']=estimate(margin_adv,bootstrap)
        group['metrics']['retention_absolute_change']=estimate(retention,bootstrap)
        group['skipped']=dict(Counter(i.get('skip_reason') or 'unspecified' for i in ii if i['status']=='skipped'))
        group['measured_interventions']=sum(i['status']=='measured' for i in ii)
        group['excluded_invalid_explanation_measurements']=excluded
        result[name]=group
    return result


def audit_metrics(out,explanations,predictions):
    path=out/'manual_audit.csv'; result=dict(reviewed=0,supported_claims=0,total_factual_claims=0,unsupported_rate=None)
    if not path.exists(): return result
    eligible={e['record_hash']:e for e in explanations if e['prediction_id'] in {p['record_id'] for p in predictions}}
    seen=set()
    with path.open(newline='',encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            if row.get('explanation_hash') not in eligible: continue
            if row['explanation_hash'] in seen: raise ValueError('Duplicate manual audit row')
            seen.add(row['explanation_hash'])
            a=row['supported_claims'].strip(); b=row['total_factual_claims'].strip()
            if not a and not b: continue
            if not a or not b: raise ValueError('Partial manual claim-count review')
            a,b=int(a),int(b)
            if not 0<=a<=b: raise ValueError('Invalid manual claim counts')
            result['reviewed']+=1; result['supported_claims']+=a; result['total_factual_claims']+=b
    if result['total_factual_claims']: result['unsupported_rate']=1-result['supported_claims']/result['total_factual_claims']
    return result


def monotonicity(interventions,bootstrap):
    """Price sensitivity of the affected candidate, NOT explanation claim agreement."""
    groups=defaultdict(list)
    for row in interventions:
        if row['spec']['kind']!='attribute_sweep' or row['status']!='measured' or not row.get('after'):
            continue
        ids=row['spec']['evidence_ids']
        if len(ids)!=1: continue
        old=next((e for e in row['original_evidence'] if e['id']==ids[0]),None)
        if not old or old['type']!='price' or not old.get('candidate_id'): continue
        cid=old['candidate_id']; before=row['before'].get('scores'); after=row['after'].get('scores')
        if before is None or after is None: continue
        change=row['spec']['value']-old['value']
        score_change=after[cid]-before[cid]
        if change==0: continue
        # Test probability direction, not a product with currency-dependent units.
        # A one-cent and a one-dollar price increase must use the same score tolerance.
        agrees=score_change<=1e-6 if change>0 else score_change>=-1e-6
        groups[(row['condition'],row['split'])].append((agrees,row['group_id']))
    result={}
    for (condition,split),pairs in groups.items():
        result.setdefault(condition,{})[split]=dict(estimate=estimate(pairs,bootstrap),
            interpretation='Weak own-price monotonicity: price increase does not raise the affected candidate score. Sensitivity diagnostic only; ties count as weak agreement. Not a claim about explanations or customers.')
    return result


def ci_text(ci):
    return "unavailable" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def analyze(out,bootstrap=500):
    manifest,case_rows,data=load_run(out); cases={c['case_id']:c for c in case_rows}
    result=dict(schema_version=2,synthetic=any(c.get('synthetic') for c in case_rows),bootstrap=bootstrap,
                warnings=manifest.get('warnings',[]),conditions={},findings=[],
                limitations=['Scores are normalized answer likelihoods, not validated customer probabilities.',
                'Edited scenarios have no observed outcome. Sensitivity does not establish customer motives.',
                'Valid citations do not validate explanation prose; manual grounding review is separate.',
                'Group-cluster intervals are exploratory with few groups. Subgroups are not confirmatory.',
                'Candidate identities remain visible in retention tests; priors can preserve predictions.'])
    for condition in sorted({r['condition'] for r in data['predictions']}):
        rows=[r for r in data['predictions'] if r['condition']==condition]
        fit=temperature_fit(rows); groups={}
        for split in ('development','validation','test'):
            selected=[r for r in rows if r['split']==split]
            if not selected: continue
            metrics=metric_rows(selected,bootstrap)
            calibrated=[]
            if fit['temperature'] is not None:
                for r in selected:
                    if r.get('scores') is not None: calibrated.append(dict(r,scores=temperature_scores(r['scores'],fit['temperature'])))
            group=dict(raw=metrics,calibrated=metric_rows(calibrated,bootstrap) if split=='test' and calibrated else None,
                       baselines=baselines(selected,cases,bootstrap),
                       candidate_counts={str(n):metric_rows([r for r in selected if len(cases[r['case_id']]['candidates'])==n],bootstrap)
                                         for n in sorted({len(cases[r['case_id']]['candidates']) for r in selected})},
                       explanations=explanation_metrics(selected,data['explanations'],data['interventions'],bootstrap),
                       grounding=audit_metrics(out,data['explanations'],selected))
            groups[split]=group
        result['conditions'][condition]=dict(temperature_fit=fit,splits=groups)
        if 'test' in groups:
            g=groups['test']; a=g['raw']['accuracy']; chance=g['baselines']['uniform_chance']['mean']
            if a['n']:
                result['findings'].append(f"{condition}: measured test accuracy {a['mean']:.1%} on {a['n']} cases / {a['groups']} groups; variable-candidate chance {chance:.1%}. 95% cluster interval: {ci_text(a['ci95'])}.")
            advantage=g['explanations']['all']['metrics']['removal_advantage']
            if advantage['n']:
                ci=advantage['ci95']; interpretation='uncertain difference (interval includes zero or unavailable)'
                if ci and ci[0]>0: interpretation='measured positive difference on this sample'
                if ci and ci[1]<0: interpretation='measured negative difference on this sample'
                result['findings'].append(f"{condition}: cited-versus-random removal advantage {advantage['mean']:.4f}, n={advantage['n']}, 95% CI={ci_text(ci)}; {interpretation}.")
        if not fit['n']: result['findings'].append(f'{condition}: calibration unavailable; no validation scores were supplied.')
        if 'test' in groups:
            eg=groups['test']['explanations']['all']; audit=groups['test']['grounding']
            result['findings'].append(f"{condition}: assessment issues {eg['assessment_issues']}; {eg['abstentions']} with no supporting citations and {eg['truncations']} truncated explanations among {eg['explanations']} attempts; {eg['missing_explanations']} test predictions have no explanation attempt.")
            if not audit['reviewed']: result['findings'].append(f'{condition}: factual grounding is not measured; no completed manual reviews.')
    result['monotonicity_diagnostic']=monotonicity(data['interventions'],bootstrap)
    # Paired condition effect only on the same original cases.
    pairs=defaultdict(dict)
    for r in data['predictions']:
        if r['split']=='test' and r.get('correct') is not None: pairs[r['case_id']][r['condition']]=r
    paired=[(int(p['with_history']['correct'])-int(p['no_history']['correct']),p['with_history']['group_id']) for p in pairs.values() if 'with_history' in p and 'no_history' in p]
    result['paired_history_accuracy_difference']=estimate(paired,bootstrap)
    if result['synthetic']: result['findings'].insert(0,'SYNTHETIC DEMONSTRATION — these measurements test software only and are not LLM findings.')
    if not data['predictions']: result['findings'].append('No saved predictions. No findings inferred.')
    atomic_json(out/'metrics.json',result)
    lines=['# '+('SYNTHETIC DEMO — NOT LLM FINDINGS' if result['synthetic'] else 'Recorded research findings'),'']+result['findings']+['','## Limits','']+result['warnings']+result['limitations']
    (out/'report.md').write_text('\n\n'.join(lines)+'\n')
    print(f'Wrote {out}/metrics.json and report.md')
    return result
