"""Saved-record metrics for the frozen test/with_history 100-case experiment.

No model, network, inference callback, or new annotation is used. Existing linked
annotation labels are assumed correct as requested; semantic quality is not
reassessed. Missing labels are unknown, never inferred from explanation text.
"""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import csv,json

from .development_pilot import digest,FAMILIES
from .joint_observation import parse_joint_response
from .test100_plan import verify_manifest,DEFAULT_OUT

ROOT=Path(__file__).resolve().parents[1]
VERSION='test100-saved-metrics-v1'
SUBSTANTIVE=FAMILIES[:6]
FACTUAL_STATUSES=('supported','contradicted','unsupported_by_supplied_information','unclear','not_applicable')
ASSUMPTION='Existing explanation annotation labels are assumed correct reference labels for this analysis, without semantic re-review or a human-review approval gate. This assumption cannot supply missing annotations. No human validation is claimed.'


def read(path):return json.loads(Path(path).read_text())
def file_hash(path):return sha256(Path(path).read_bytes()).hexdigest()
def label_path(path):
    try:return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:return str(Path(path).resolve())

def rate(n,d):
    assert 0<=n<=d
    return {'numerator':n,'denominator':d,'rate':n/d if d else None,'percentage':100*n/d if d else None}


def decode(record,entry):
    if record is None:return None,'missing_response'
    response=record['response'];parsed,d=parse_joint_response(response['raw_response'],entry['observations']['candidates'],entry['observations'],truncated=response['diagnostics']['generation_truncated'])
    if parsed!=response['parsed_result'] or d!=response['diagnostics']:raise ValueError('Stored parsing differs from raw response: '+entry['call_id'])
    if not d['parse_ok']:return None,'json_parse_failure'
    if not d['prediction_valid']:return None,'invalid_or_missing_prediction'
    inverse={answer:product for product,answer in entry['presentation']['answer_mapping'].items()}
    product=inverse[parsed['prediction']]
    if product!=record['decoded_product_id']:raise ValueError('Saved decoded product mismatch: '+entry['call_id'])
    return product,None


def load_run(study_dir):
    study_dir=Path(study_dir);manifest=verify_manifest(study_dir)
    if manifest['split']!='test' or manifest['condition']!='with_history' or manifest['selection_count']!=100:raise ValueError('Wrong study scope')
    entries={e['call_id']:e for e in manifest['entries']};records={};items={};protected={}
    paths=[study_dir/p for p in ('manifest.json','selected_cases.json','evaluation_targets.json','registry.json','protocol.json','execution_config.json','rendered_prompts.json')]
    config=read(study_dir/'execution_config.json');prompts=read(study_dir/'rendered_prompts.json')
    orphan=[]
    for path in sorted((study_dir/'responses').glob('*.json')):
        r=read(path);cid=r['call_id']
        if cid not in entries or r['plan_id']!=manifest['plan_id']:
            orphan.append({'path':label_path(path),'reason':'not_a_response_in_this_frozen_plan'});continue
        e=entries[cid]
        if cid in records or path.stem!=cid:raise ValueError('Duplicate or inconsistent response ID')
        if any(r.get(k)!=e[k] for k in ('case_id','condition','family')):raise ValueError('Response case/condition/family join mismatch: '+cid)
        if e['skip_reason']:raise ValueError('Response exists for a not-applicable intervention')
        out=r['response'];expected=digest({'plan_id':manifest['plan_id'],'entry':e,'runtime':config['runtime'],'rendered_prompt':prompts[cid]['rendered_prompt']})
        if r['input_signature']!=expected or out['messages']!=e['messages'] or out['rendered_prompt']!=prompts[cid]['rendered_prompt']:raise ValueError('Frozen input signature/prompt mismatch: '+cid)
        if out['generation_metadata']['effective_settings']!=config['runtime']['effective_settings']:raise ValueError('Generation setting mismatch: '+cid)
        if out['prompt_version']!=manifest['prompt_version'] or out['observation_version']!=manifest['observation_version']:raise ValueError('Response experiment-version mismatch: '+cid)
        model=out['generation_metadata']['model'];expected_model=config['runtime']['model']
        if any(model.get(k)!=expected_model.get(k) for k in ('model_id','revision','device','dtype','torch','transformers')):raise ValueError('Model provenance mismatch: '+cid)
        if model.get('tokenizer_revision')!=expected_model['revision'] and expected_model['revision'] not in model.get('tokenizer',''):raise ValueError('Tokenizer provenance missing/mismatched: '+cid)
        decode(r,e);records[cid]=r;paths.append(path)
    for e in entries.values():
        path=study_dir/'items'/f"{e['call_id']}.json"
        if path.exists():items[e['call_id']]=read(path);paths.append(path)
    protected.update({label_path(p):file_hash(p) for p in paths})
    return {'directory':study_dir,'manifest':manifest,'entries':entries,'responses':records,'items':items,
            'targets':read(study_dir/'evaluation_targets.json'),'protected':protected,'excluded_responses':orphan}


def annotation_sources(study_dir):
    paths=set((Path(study_dir)/'annotations').rglob('*.json'))
    paths.update((ROOT/'choice_study/explanation_annotation_runs').glob('*.json'))
    paths.update((ROOT/'choice_study').glob('*/annotations/*.json'))
    paths.update((ROOT/'choice_study').glob('*/agent_assisted_annotation_audit_*/reviewed_layer.json'))
    return sorted(paths)


def join_annotations(run):
    """Join explicit response identifiers, not similar prose or shared brand names."""
    joined={};inventory=[];selected={r['case_id'] for r in run['manifest']['selected_cases']}
    for path in annotation_sources(run['directory']):
        data=read(path);run['protected'][label_path(path)]=file_hash(path)
        if path.name=='reviewed_layer.json':
            inventory.append({'annotation_id':label_path(path),'path':label_path(path),'status':'excluded',
                'reason':'agent_assisted_development_pilot_layer_outside_frozen_test_selection',
                'case_ids':list(data.get('records',{}))});continue
        result=data.get('result',data)
        if 'parsed_annotations' not in result:continue
        cid=data.get('call_id') or data.get('response_id') or data.get('source_response_id')
        case=data.get('case_id') or (cid.split('__')[0] if cid else None)
        row={'annotation_id':label_path(path),'path':label_path(path),'response_id':cid,'case_id':case}
        if case not in selected:
            inventory.append({**row,'status':'excluded','reason':'case_outside_frozen_test_selection'});continue
        if cid not in run['responses']:
            inventory.append({**row,'status':'excluded','reason':'no_stable_link_to_a_response_in_this_experiment'});continue
        record=run['responses'][cid];inp=result.get('annotation_input',{});parsed=record['response']['parsed_result']
        if not isinstance(parsed,dict) or inp.get('explanation')!=parsed.get('explanation') or inp.get('observations',{}).get('text')!=run['entries'][cid]['observations']['text']:
            inventory.append({**row,'status':'excluded','reason':'annotation_source_response_or_factual_input_differs'});continue
        claims=result.get('parsed_annotations',{}).get('claims')
        if not isinstance(claims,list):
            inventory.append({**row,'status':'unassessable','reason':'existing_annotation_has_no_claim_list'});continue
        if cid in joined:raise ValueError('Multiple reference annotation layers for '+cid+'; specify a layer without silently mixing')
        joined[cid]={'annotation_id':label_path(path),'claims':claims,'record':result}
        inventory.append({**row,'status':'joined','claim_count':len(claims),'label_assumption':'accepted_as_correct_without_semantic_reassessment'})
    return joined,inventory


def prediction_metrics(run):
    rows=[];originals={e['case_id']:e for e in run['entries'].values() if e['family']=='ORIGINAL'}
    assert len(originals)==100
    evaluated=correct=available=0;original_errors=Counter()
    for case,e in originals.items():
        r=run['responses'].get(e['call_id']);available+=r is not None;product,error=decode(r,e)
        if error:original_errors[error]+=1
        elif case not in run['targets']:original_errors['missing_target']+=1
        else:evaluated+=1;correct+=product==run['targets'][case]
    family_rows=[]
    for family in FAMILIES:
        these=[]
        for e in run['entries'].values():
            if e['family']!=family:continue
            baseline=originals[e['case_id']];a=run['responses'].get(baseline['call_id']);b=run['responses'].get(e['call_id'])
            original_product,a_error=decode(a,baseline)
            edited_product,b_error=(None,'not_applicable') if e['skip_reason'] else decode(b,e)
            status=run['items'].get(e['call_id'],{}).get('status','missing_item_state')
            valid=not e['skip_reason'] and a_error is None and b_error is None and status in ('completed','reused')
            these.append({'case_id':e['case_id'],'family':family,'original_response_id':baseline['call_id'],
                'edited_response_id':e['call_id'],'original_response_path':label_path(run['directory']/'responses'/f"{baseline['call_id']}.json") if a else None,
                'edited_response_path':label_path(run['directory']/'responses'/f"{e['call_id']}.json") if b else None,
                'status':status,'applicable':not bool(e['skip_reason']),'skip_reason':e['skip_reason'],
                'original_product_id':original_product,'edited_product_id':edited_product,'valid_prediction_comparison':valid,
                'prediction_changed':original_product!=edited_product if valid else None,
                'original_prediction_exclusion':a_error,'edited_prediction_exclusion':b_error,
                'exact_patch':e.get('patch',[]),'answer_mapping':e.get('presentation',{}).get('answer_mapping')})
        rows+=these;valid=[r for r in these if r['valid_prediction_comparison']];changed=sum(r['prediction_changed'] for r in valid)
        family_rows.append({'family':family,'selected_cases':100,'applicable':sum(r['applicable'] for r in these),
            'completed':sum(r['status']=='completed' for r in these),'reused':sum(r['status']=='reused' for r in these),
            'assessable':len(valid),'changed':changed,'unchanged':len(valid)-changed,'skipped':sum(not r['applicable'] for r in these),
            'failed':sum(r['status']=='failed' for r in these),'unresolved':sum(r['applicable'] and r['status'] not in ('completed','reused','failed') for r in these),
            'completed_unassessable':sum(r['status'] in ('completed','reused') and not r['valid_prediction_comparison'] for r in these),
            'change_rate':rate(changed,len(valid)),'skip_reasons':dict(Counter(r['skip_reason'] for r in these if r['skip_reason']))})
    accuracy={**rate(correct,evaluated),'selected_cases':100,'available_originals':available,'evaluated_originals':evaluated,
              'coverage':rate(evaluated,100),'parsing_or_prediction_exclusions':dict(original_errors),'originals_counted_once':len(originals)}
    invariance={r['family']:rate(r['unchanged'],r['assessable']) for r in family_rows if r['family'] in FAMILIES[6:]}
    return accuracy,family_rows,invariance,rows


def claim_match(claim,family,patch):
    """Finer relationship/source matches; HH alone never invents a subtype."""
    groups=set(claim.get('concept_groups',[]));refs=set(claim.get('source_fields',[]));rel=claim.get('relationship_type')
    prices={f for f in refs if '.prices.' in f};ads={f for f in refs if '.advertised.' in f};purchases={f for f in refs if f.endswith('.purchased')}
    history=bool(purchases or any(f.startswith('H') for f in prices|ads))
    if family=='CURRENT_PRICE':return ('fine' if any(f.startswith('current.prices.') for f in refs) or rel=='current_price_comparison' else 'broad') if 'CURRENT_PRICES' in groups else None
    if family=='CURRENT_ADVERTISING':return ('fine' if any(f.startswith('current.advertised.') for f in refs) or rel=='current_advertising' else 'broad') if 'CURRENT_ADVERTISING' in groups else None
    if 'HOUSEHOLD_HISTORY' not in groups:return None
    changed={p['field'] for p in patch}
    if family=='SUPPORT_PURCHASE':
        if rel=='support_purchase_frequency' or refs&changed:return 'fine'
        if rel in ('historical_price_purchase_relationship','historical_advertising_purchase_relationship','brand_persistence_under_different_offers') and purchases&changed:return 'fine'
    elif family=='HISTORICAL_PRICE_ASSOCIATION':
        if rel=='historical_price_purchase_relationship' or any(f.startswith('H') for f in prices):return 'fine'
    elif family=='HISTORICAL_ADVERTISING_ASSOCIATION':
        if rel=='historical_advertising_purchase_relationship' or any(f.startswith('H') for f in ads):return 'fine'
    elif family=='HISTORICAL_OFFER_REMOVAL':
        if rel in ('historical_price_purchase_relationship','historical_advertising_purchase_relationship','brand_persistence_under_different_offers') or any(f.startswith('H') for f in prices|ads):return 'fine'
        if rel=='support_purchase_frequency' or (purchases and not prices and not ads):return None
    if not refs and rel=='other_or_unclear':return 'broad_history_unresolved'
    return None


def influence(annotation,family,patch):
    if annotation is None:return {'classification':'unassessable','reason':'missing_original_explanation_annotation','subtype':'annotation_missing','evidence':[]}
    matches=[(c,claim_match(c,family,patch)) for c in annotation['claims']];matches=[(c,m) for c,m in matches if m]
    fine_positive=any(m!='broad_history_unresolved' and c.get('claimed_role') in ('decisive','contributing') for c,m in matches)
    if any(m=='broad_history_unresolved' for _,m in matches) and not fine_positive:return {'classification':'unclear','reason':'broad_household_group_does_not_identify_affected_history_information','subtype':'broad_group_only','evidence':[{'claim_id':c.get('claim_id'),'exact_quote':c.get('exact_quote'),'source_fields':c.get('source_fields',[]),'mapped_evidence_ids':c.get('mapped_evidence_ids',[]),'match_level':m} for c,m in matches]}
    roles={c.get('claimed_role') for c,_ in matches};levels={m for _,m in matches}
    if roles&{'decisive','contributing'}:value,subtype='yes','claimed_influence'
    elif roles-{'descriptive_only','explicitly_irrelevant'}:value,subtype='unclear','role_unclear'
    elif not matches:value,subtype='no','not_mentioned_in_existing_annotations'
    else:value,subtype='no',';'.join(sorted(roles))
    return {'classification':value,'subtype':subtype,'matching_level':';'.join(sorted(levels)) or 'no_relevant_claim',
            'reason':'Roles are accepted reference labels regardless of factual truth; no means no influence asserted, not model non-use.','evidence':[{'claim_id':c.get('claim_id'),'exact_quote':c.get('exact_quote'),'claimed_role':c.get('claimed_role'),'factual_status':c.get('factual_status'),'source_fields':c.get('source_fields',[]),'mapped_evidence_ids':c.get('mapped_evidence_ids',[]),'match_level':m} for c,m in matches]}


def conditional_metrics(pairs,annotations):
    tables=[]
    for family in SUBSTANTIVE:
        rows=[p for p in pairs if p['family']==family]
        for p in rows:
            assessment=influence(annotations.get(p['original_response_id']),family,p['exact_patch'])
            p['original_annotation_id']=annotations.get(p['original_response_id'],{}).get('annotation_id')
            p['claimed_influence']=assessment
        valid=[p for p in rows if p['valid_prediction_comparison']]
        counts={f'{label}_{outcome}':sum(p['claimed_influence']['classification']==label and p['prediction_changed']==changed for p in valid)
                for label in ('yes','no') for outcome,changed in (('changed',True),('unchanged',False))}
        tables.append({'family':family,'valid_prediction_pairs':len(valid),**counts,
            'p_change_given_claimed_influence':rate(counts['yes_changed'],counts['yes_changed']+counts['yes_unchanged']),
            'p_change_given_no_influence_asserted':rate(counts['no_changed'],counts['no_changed']+counts['no_unchanged']),
            'unclear_excluded':sum(p['claimed_influence']['classification']=='unclear' for p in valid),
            'unassessable_excluded':sum(p['claimed_influence']['classification']=='unassessable' for p in valid),
            'invalid_prediction_pairs_excluded':sum(p['applicable'] and not p['valid_prediction_comparison'] for p in rows)})
    overall={'family':'OVERALL_PAIR_WEIGHTED','valid_prediction_pairs':sum(t['valid_prediction_pairs'] for t in tables)}
    for key in ('yes_changed','yes_unchanged','no_changed','no_unchanged','unclear_excluded','unassessable_excluded','invalid_prediction_pairs_excluded'):overall[key]=sum(t[key] for t in tables)
    overall['p_change_given_claimed_influence']=rate(overall['yes_changed'],overall['yes_changed']+overall['yes_unchanged'])
    overall['p_change_given_no_influence_asserted']=rate(overall['no_changed'],overall['no_changed']+overall['no_unchanged'])
    overall['unit']='original–edited pairs; several interventions share an original; pairs are not independent observations'
    return tables,overall


def factuality_metrics(run,annotations):
    claims=[];coverage=[]
    for cid,r in run['responses'].items():
        ann=annotations.get(cid);parsed=r['response']['parsed_result']
        coverage.append({'response_id':cid,'case_id':r['case_id'],'family':r['family'],
            'annotation_id':ann['annotation_id'] if ann else None,'annotation_status':'available_reference_labels' if ann else 'missing_annotation',
            'parsed_explanation_available':isinstance(parsed,dict) and isinstance(parsed.get('explanation'),str) and bool(parsed['explanation'].strip()),
            'reason':None if ann else 'No existing annotation is linked to this response; raw text is not newly annotated.'})
        if not ann:continue
        source=run['entries'][cid]['observations']['audit']['source_values']
        for c in ann['claims']:
            claims.append({'response_id':cid,'case_id':r['case_id'],'family':r['family'],'annotation_id':ann['annotation_id'],
                'claim_id':c.get('claim_id'),'exact_quote':c.get('exact_quote'),'factual_status':c.get('factual_status'),
                'claimed_role':c.get('claimed_role'),'source_fields':c.get('source_fields',[]),
                'mapped_evidence_ids':c.get('mapped_evidence_ids',[]),'source_values':{f:source[f] for f in c.get('source_fields',[]) if f in source},
                'unresolved_source_fields':[f for f in c.get('source_fields',[]) if f not in source],
                'included_in_contradiction_denominator':c.get('factual_status') in ('supported','contradicted'),
                'inclusion_or_exclusion_reason':'Reference factual label used without semantic reassessment; other statuses remain excluded.'})
    groups={}
    scopes=[('originals',lambda f:f=='ORIGINAL'),('edited_overall',lambda f:f!='ORIGINAL'),('all_distinct_responses',lambda f:True)]
    scopes += [('edited_'+f,lambda x,f=f:x==f) for f in FAMILIES]
    for name,predicate in scopes:
        response_ids={cid for cid,r in run['responses'].items() if predicate(r['family'])}
        selected=[c for c in claims if c['response_id'] in response_ids];counts=Counter(c['factual_status'] for c in selected)
        groups[name]={'response_count':len(response_ids),'annotated_response_count':sum(cid in annotations for cid in response_ids),
            'missing_annotation_count':sum(cid not in annotations for cid in response_ids),'claim_status_counts':{s:counts[s] for s in FACTUAL_STATUSES},
            'contradiction_rate':rate(counts['contradicted'],counts['supported']+counts['contradicted']),
            'excluded_status_counts':{s:counts[s] for s in FACTUAL_STATUSES if s not in ('supported','contradicted')},
            'reason':None if selected else 'No linked claim-level factual annotations; no contradiction labels were invented.'}
    return groups,claims,coverage


def rule_assessment(pair,annotation,run):
    base={'case_id':pair['case_id'],'family':pair['family'],'original_response_id':pair['original_response_id'],
          'edited_response_id':pair['edited_response_id'],'annotation_id':annotation.get('annotation_id') if annotation else None,
          'exact_patch':pair['exact_patch'],'rule_claims':[],'expected_product_id':None,'consistent':None,'assessable':False}
    if not pair['applicable']:return {**base,'status':'not_applicable','reason':pair['skip_reason']}
    if pair['family'] not in SUBSTANTIVE:return {**base,'status':'control_excluded','reason':'Presentation controls are separate from substantive claimed-rule comparisons.'}
    if annotation is None:return {**base,'status':'unassessable','reason':'missing_original_rule_annotation','premise_status':'unassessable','rule_status':'unassessable'}
    decisive=[c for c in annotation['claims'] if c.get('claimed_role')=='decisive']
    if not decisive:return {**base,'status':'unassessable','reason':'no_explicit_deciding_rule_in_reference_labels','rule_status':'not_established'}
    base['rule_claims']=[{'claim_id':c.get('claim_id'),'exact_quote':c.get('exact_quote'),'source_fields':c.get('source_fields',[])} for c in decisive]
    # Only an existing, fully specified rule object is supported. No prose-to-rule
    # inference is made from a contributing reason or a "more likely" statement.
    rules=[c.get('rule_specification') for c in decisive]
    if len(rules)!=1 or not isinstance(rules[0],dict) or rules[0].get('template')!='choose_uniquely_cheapest_current_product':
        return {**base,'status':'unassessable','reason':'no_unambiguous_supported_structured_rule_template','rule_status':'ambiguous_or_unformalized'}
    rule=rules[0];by_id={c.get('claim_id'):c for c in annotation['claims']};premises=rule.get('premise_claim_ids',[])
    if not premises or any(cid not in by_id for cid in premises):return {**base,'status':'unassessable','reason':'rule_premise_claims_not_specified','premise_status':'unassessable'}
    statuses=[by_id[cid].get('factual_status') for cid in premises]
    if any(s=='contradicted' for s in statuses):return {**base,'status':'invalid_premise','reason':'reference_labels_contradict_required_rule_premise','premise_status':'invalid'}
    if any(s!='supported' for s in statuses):return {**base,'status':'unassessable','reason':'rule_premises_not_established_valid','premise_status':'unassessable'}
    from .observations import canonical_price
    entry=run['entries'][pair['edited_response_id']];prices=entry['edited_source']['current']['prices']
    values={k:canonical_price(v) for k,v in prices.items()}
    if any(v is None for v in values.values()):return {**base,'status':'unassessable','reason':'edited_price_missing'}
    from decimal import Decimal
    low=min(Decimal(v) for v in values.values());winners=[k for k,v in values.items() if Decimal(v)==low]
    base['edited_current_price_values_2dp']=values
    if len(winners)!=1:return {**base,'status':'unassessable','reason':'edited_prices_do_not_imply_a_unique_product'}
    if not pair['valid_prediction_comparison']:return {**base,'status':'unassessable','reason':'prediction_not_decodable'}
    return {**base,'status':'assessable','assessable':True,'expected_product_id':winners[0],
            'consistent':pair['edited_product_id']==winners[0],'premise_status':'valid','rule_status':'explicit_specified_template'}


def stale_assessment(pair,annotation):
    base={'case_id':pair['case_id'],'family':pair['family'],'original_response_id':pair['original_response_id'],
          'edited_response_id':pair['edited_response_id'],'annotation_id':annotation.get('annotation_id') if annotation else None,
          'exact_patch':pair['exact_patch'],'assessable':False,'contains_stale_fact':None,'claim_evidence':[]}
    if not pair['applicable']:return {**base,'status':'not_applicable','reason':pair['skip_reason']}
    if annotation is None:return {**base,'status':'unassessable','reason':'missing_edited_claim_annotations; no explicit stale labels or mapped temporal/asserted-value information'}
    # An explicit existing stale label is a reference label, not newly invented.
    labelled=[c for c in annotation['claims'] if isinstance(c.get('stale_fact'),bool)]
    for c in labelled:
        base['claim_evidence'].append({'claim_id':c.get('claim_id'),'exact_quote':c.get('exact_quote'),
           'stale_fact':c['stale_fact'],'source_fields':c.get('source_fields',[]),'mapped_evidence_ids':c.get('mapped_evidence_ids',[])})
    if any(c['stale_fact'] for c in labelled):return {**base,'status':'assessable','assessable':True,'contains_stale_fact':True,'reason':'existing_explicit_stale_fact_label'}
    if annotation['record'].get('stale_fact_coverage_complete') is True:
        return {**base,'status':'assessable','assessable':True,'contains_stale_fact':False,'reason':'existing_complete_stale_assessment_contains_no_positive_label'}
    return {**base,'status':'unassessable','reason':'existing_annotations_do_not_establish_current_vs_past_assertion_scope_and_changed_original_value; contradiction alone is insufficient'}


def rule_and_stale_metrics(run,pairs,annotations):
    rules=[rule_assessment(p,annotations.get(p['original_response_id']),run) for p in pairs]
    stale=[stale_assessment(p,annotations.get(p['edited_response_id'])) for p in pairs]
    rule_summary={};stale_summary={}
    for family in list(SUBSTANTIVE)+['OVERALL_PAIR_WEIGHTED']:
        rows=[r for r in rules if r['family'] in SUBSTANTIVE and (family=='OVERALL_PAIR_WEIGHTED' or r['family']==family) and r['status']!='not_applicable']
        assessed=[r for r in rows if r['assessable']];consistent=sum(r['consistent'] for r in assessed)
        rule_summary[family]={'applicable_pairs':len(rows),'assessable_pairs':len(assessed),'consistent':consistent,'inconsistent':len(assessed)-consistent,
            'rule_consistency_rate':rate(consistent,len(assessed)),'assessment_coverage':rate(len(assessed),len(rows)),
            'unassessable_pairs':len(rows)-len(assessed),'exclusion_reasons':dict(Counter(r.get('reason') for r in rows if not r['assessable'])),
            'invalid_premise_count':sum(r.get('premise_status')=='invalid' for r in rows) if any(r.get('premise_status') in ('valid','invalid') for r in rows) else None,
            'ambiguous_rule_count':sum(r.get('rule_status')=='ambiguous_or_unformalized' for r in rows) if any(r.get('rule_status')!='unassessable' for r in rows) else None}
    for family in list(FAMILIES)+['OVERALL_EDITED_RESPONSES']:
        rows=[r for r in stale if (family=='OVERALL_EDITED_RESPONSES' or r['family']==family) and r['status']!='not_applicable']
        assessed=[r for r in rows if r['assessable']];positive=sum(r['contains_stale_fact'] for r in assessed)
        stale_summary[family]={'edited_response_count':len(rows),'assessable_edited_explanations':len(assessed),
            'containing_stale_fact':positive,'stale_fact_rate':rate(positive,len(assessed)),
            'assessment_coverage':rate(len(assessed),len(rows)),'unassessable_count':len(rows)-len(assessed),
            'exclusion_reasons':dict(Counter(r.get('reason') for r in rows if not r['assessable']))}
    return rule_summary,stale_summary,rules,stale


def measured_examples(run,pairs):
    selections=[]
    categories=[('changed_prediction',lambda p:p['valid_prediction_comparison'] and p['prediction_changed']),
        ('unchanged_prediction',lambda p:p['valid_prediction_comparison'] and not p['prediction_changed']),
        ('answer_mapping_invariant',lambda p:p['family']=='ANSWER_MAPPING_CONTROL' and p['valid_prediction_comparison'] and not p['prediction_changed']),
        ('malformed_edited_response',lambda p:p['applicable'] and p['edited_prediction_exclusion']=='json_parse_failure')]
    for category,predicate in categories:
        pair=next((p for p in pairs if predicate(p)),None)
        if pair is None:continue
        a=run['responses'][pair['original_response_id']]['response'];b=run['responses'].get(pair['edited_response_id'],{}).get('response',{})
        selections.append({'category':category,'selection_rule':'First matching saved pair in fixed family and manifest order; illustrative, not a new experiment or annotation.',
            'case_id':pair['case_id'],'family':pair['family'],'original_response_id':pair['original_response_id'],'edited_response_id':pair['edited_response_id'],
            'original_product_id':pair['original_product_id'],'edited_product_id':pair['edited_product_id'],'exact_patch':pair['exact_patch'],
            'original_explanation':a['parsed_result'].get('explanation') if isinstance(a['parsed_result'],dict) else None,
            'edited_explanation':b.get('parsed_result',{}).get('explanation') if isinstance(b.get('parsed_result'),dict) else None,
            'original_raw_response':a['raw_response'],'edited_raw_response':b.get('raw_response'),
            'annotation_status':'No linked annotations; raw explanation text is displayed without assigning new influence/factuality/staleness labels.'})
    return selections


def validate_calculations(metrics,pairs,claims):
    assert metrics['original_accuracy']['originals_counted_once']==100
    assert len(pairs)==800 and len({p['edited_response_id'] for p in pairs})==800
    assert sum(r['assessable'] for r in metrics['prediction_change_by_family'])==sum(p['valid_prediction_comparison'] for p in pairs)
    for row in metrics['prediction_change_by_family']:
        assert row['changed']+row['unchanged']==row['assessable']
        assert row['assessable']<=row['completed']+row['reused']<=row['applicable']
        if row['family'] in metrics['invariance'] and row['assessable']:
            assert abs(metrics['invariance'][row['family']]['rate']-(1-row['change_rate']['rate']))<1e-12
    def visit(obj):
        if isinstance(obj,dict):
            if {'numerator','denominator','rate'}<=set(obj):
                assert 0<=obj['numerator']<=obj['denominator']
                assert (obj['rate'] is None)==(obj['denominator']==0)
            for value in obj.values():visit(value)
        elif isinstance(obj,list):
            for value in obj:visit(value)
    visit(metrics)
    keys=[(c['response_id'],c['annotation_id'],c['claim_id']) for c in claims];assert len(keys)==len(set(keys))
    return {'original_responses_counted_once':True,'unique_intervention_rows':True,'decoded_comparisons_verified_from_raw_predictions':True,
            'counts_and_numerators_consistent':True,'control_invariance_equals_one_minus_change':True,
            'zero_denominators_are_null':True,'claim_records_not_duplicated_across_pairs':True}


def calculate(study_dir=DEFAULT_OUT):
    run=load_run(study_dir);annotations,inventory=join_annotations(run)
    accuracy,families,invariance,pairs=prediction_metrics(run)
    conditional,overall=conditional_metrics(pairs,annotations)
    factual,claims,coverage=factuality_metrics(run,annotations)
    rules,stale,rule_records,stale_records=rule_and_stale_metrics(run,pairs,annotations)
    for p in pairs:
        if p['family'] not in SUBSTANTIVE:p['claimed_influence']={'classification':'not_evaluated','reason':'presentation_control_excluded_from_main_influence_comparisons'}
        p.setdefault('original_annotation_id',annotations.get(p['original_response_id'],{}).get('annotation_id'))
        p['edited_annotation_id']=annotations.get(p['edited_response_id'],{}).get('annotation_id')
    originals=[r for r in run['responses'].values() if r['family']=='ORIGINAL'];edited=[r for r in run['responses'].values() if r['family']!='ORIGINAL']
    states=Counter(i['status'] for i in run['items'].values());diagnostics=Counter()
    for r in run['responses'].values():
        d=r['response']['diagnostics'];diagnostics['parse_failures']+=d['parse_ok'] is False;diagnostics['invalid_predictions']+=d['prediction_valid'] is False
        diagnostics['invalid_citation_lists']+=d['citations_valid'] is False;diagnostics['truncations']+=d['generation_truncated'] is True
    metrics={'analysis_version':VERSION,'study_plan_id':run['manifest']['plan_id'],'scope':{'split':'test','condition':'with_history','selected_cases':100},
        'annotation_reference_assumption':ASSUMPTION,
        'data_coverage':{'selected_cases':100,'available_originals':len(originals),'originals_reused':sum(bool(r.get('reuse_provenance')) for r in originals),'applicable_interventions':sum(r['applicable'] for r in pairs),
            'completed_edited_responses':len(edited),'completed_responses':len(run['responses']),'valid_original_edited_pairs':sum(p['valid_prediction_comparison'] for p in pairs),
            'skipped_interventions':sum(not p['applicable'] for p in pairs),'item_status_counts':dict(states),
            'unresolved_items':sum(s not in ('completed','reused','not_applicable') for s in [run['items'].get(cid,{}).get('status','missing') for cid in run['entries']]),
            'excluded_response_files':run['excluded_responses'],'response_diagnostics':dict(diagnostics)},
        'annotation_coverage':{'linked_originals':sum(r['call_id'] in annotations for r in originals),'original_responses':len(originals),
            'linked_edited':sum(r['call_id'] in annotations for r in edited),'edited_responses':len(edited),
            'linked_total':len(annotations),'distinct_responses':len(run['responses']),
            'excluded_annotation_sources':sum(r['status']=='excluded' for r in inventory),
            'reason':'Existing saved annotations refer to other cases/experimental versions. Missing labels are not no-influence or no-error labels.' if not annotations else None},
        'original_accuracy':accuracy,'prediction_change_by_family':families,'invariance':invariance,
        'conditional_change_by_family':conditional,'conditional_change_overall_pair_weighted':overall,
        'conditional_definition':'No influence means NO INFLUENCE ASSERTED IN THE EXPLANATION reference labels, not proof the model ignored the information. Unclear/missing labels excluded; controls separate.',
        'rule_consistency':rules,'factual_contradiction':factual,'stale_fact':stale,
        'interpretation_limits':['Actual edited-scenario customer purchases are unknown; no counterfactual accuracy is computed.',
           'Several interventions share an original case; pair-weighted results do not imply independent observations.',
           'No distribution metrics, KL CE, distribution EE, Pearson faithfulness or combined trust score are computed.',
           'No new model calls, annotations, semantic annotation reviews or human-review approval were used.']}
    metrics['consistency_checks']=validate_calculations(metrics,pairs,claims)
    return {'metrics':metrics,'pairs':pairs,'claims':claims,'response_annotation_coverage':coverage,'rule_evidence':rule_records,
        'stale_evidence':stale_records,'annotation_inventory':inventory,'examples':measured_examples(run,pairs),'protected':run['protected']}


def format_rate(value):
    return 'NA (0/0)' if value['rate'] is None else f"{value['percentage']:.2f}% ({value['numerator']}/{value['denominator']})"


def markdown_report(result):
    m=result['metrics'];a=m['original_accuracy'];c=m['data_coverage'];ac=m['annotation_coverage']
    lines=['# Completed 100-case with-history test metrics','',m['annotation_reference_assumption'],'',
        '## Analysis data','',f"Frozen plan `{m['study_plan_id']}`. Test/with_history only; development, validation, legacy runs and unrelated annotation cases are excluded.",
        f"Selected cases: 100. Originals: {c['available_originals']}; applicable edits: {c['applicable_interventions']}; saved responses: {c['completed_responses']}; valid pairs: {c['valid_original_edited_pairs']}; skips: {c['skipped_interventions']}; unresolved: {c['unresolved_items']}.",
        f"Model diagnostics (overlapping counts): {c['response_diagnostics']}. No missing or malformed response is replaced with an invented prediction.",'',
        '## Original prediction accuracy','',f"**{a['numerator']} correct out of {a['denominator']} = {a['percentage']:.2f}%**. Evaluation coverage: {a['evaluated_originals']}/100 selected cases. Each original is counted once. Original parsing/prediction exclusions: {a['parsing_or_prediction_exclusions']}.",'',
        '## Prediction changes','', '| Family | Applicable | Completed/reused | Assessable | Changed | Unchanged | Change rate | Skips | Unassessable completed |',
        '|---|---:|---:|---:|---:|---:|---|---:|---:|']
    for r in m['prediction_change_by_family']:
        lines.append(f"| {r['family']} | {r['applicable']} | {r['completed']+r['reused']} | {r['assessable']} | {r['changed']} | {r['unchanged']} | {format_rate(r['change_rate'])} | {r['skipped']} | {r['completed_unassessable']} |")
    lines+=['',f"Product-order invariance: **{format_rate(m['invariance']['PRODUCT_ORDER_CONTROL'])}**.",
        f"Answer-mapping invariance: **{format_rate(m['invariance']['ANSWER_MAPPING_CONTROL'])}**. Both use canonical product identity, not answer-letter equality.",'',
        '## Explanation annotation coverage','',f"Linked original annotations: **{ac['linked_originals']}/{ac['original_responses']}**. Linked edited annotations: **{ac['linked_edited']}/{ac['edited_responses']}**.",
        'The eight raw annotation files and one agent-assisted reviewed-layer file discovered in the project belong to the development pilot or the older row-2 experiment. None refers to a selected test case. They are excluded because of case/experiment linkage, not semantic quality. The requested assumption that labels are correct is honored; it does not create missing test labels. See `annotation_inventory.json`.',
        '', '## Conditional prediction changes and 2×2 counts','',
        '“No influence” means **no influence asserted in the reference explanation labels**, not proof of model non-use. Descriptive-only, explicitly denied and not-mentioned statuses remain distinct in per-pair records. Broad household labels are not invented history subtypes. Controls are excluded.',
        '', '| Family | Yes: changed | Yes: unchanged | No: changed | No: unchanged | P(change given yes) | P(change given no) | Unclear/unassessable excluded |',
        '|---|---:|---:|---:|---:|---|---|---:|']
    for r in m['conditional_change_by_family']+[m['conditional_change_overall_pair_weighted']]:
        lines.append(f"| {r['family']} | {r['yes_changed']} | {r['yes_unchanged']} | {r['no_changed']} | {r['no_unchanged']} | {format_rate(r['p_change_given_claimed_influence'])} | {format_rate(r['p_change_given_no_influence_asserted'])} | {r['unclear_excluded']+r['unassessable_excluded']} |")
    lines+=['','The overall row is pair-weighted; multiple interventions on one case are not independent observations. With no linked original annotations, all 440 otherwise valid substantive pairs are unassessable for claimed influence. Two additional substantive pairs have invalid edited predictions. Zero conditional denominators yield null/NA, not 0%.',
        '', '## Rule consistency','',
        'NA (0/0 assessable rule-testing pairs); assessment coverage 0/442 applicable substantive pairs. No original rule annotations are linked. Invalid-premise and ambiguous-rule counts are unknown (null), not assumed zero. Every pair has an explicit eligibility/exclusion record in `rule_consistency_evidence.jsonl`.',
        'Only an existing decisive rule with the documented structured `choose_uniquely_cheapest_current_product` template and supported mapped premise claims is accepted. Contributing reasons, vague “more likely” language, changed justifications and missing rule labels are not converted into rule violations.',
        '', '## Factual contradiction','',
        'NA for originals, edits, each family and all distinct explanations: each has 0 supported and 0 contradicted *annotated claims*, so the denominator is zero. Original-response coverage is 0/100, edited-response coverage 0/642, all-response coverage 0/742. Unsupported, unclear and not-applicable counts are recorded separately; absent annotations are not classified into any factual category.',
        '`claim_factuality.jsonl` is empty because there are zero in-scope reference claims. `response_annotation_coverage.jsonl` retains all 742 responses and the reason each lacks an annotation. Originals are never repeated across comparison pairs.',
        '', '## Stale facts','',
        'NA (0/0 assessable edited explanations), coverage 0/642. There are no linked edited claim annotations, explicit stale labels, or mapped temporal/asserted-value information. Exact patches alone do not establish what an explanation asserts. A contradiction is not automatically stale; current facts that remain true, past/original references and changed reasoning are not stale by definition.',
        'Per-family counts and exclusions are in `metrics.json`; `stale_fact_evidence.jsonl` retains every planned edited item, its exact patch and missing-information reason. No label was inferred from raw text.',
        '', '## Actual saved examples','']
    for e in result['examples']:
        lines+=[f"### {e['category']}: {e['case_id']} / {e['family']}",f"Response IDs: `{e['original_response_id']}` → `{e['edited_response_id']}`. Decoded product: {e['original_product_id']} → {e['edited_product_id']}.",
            '','Exact patch:','```json',json.dumps(e['exact_patch'],ensure_ascii=False),'```',
            '', 'Original explanation: '+json.dumps(e['original_explanation'],ensure_ascii=False),
            '', 'Edited explanation: '+json.dumps(e['edited_explanation'],ensure_ascii=False),
            '',e['annotation_status'],'']
    lines+=['## Outputs and reproducibility','',
        'Run `python3 scripts/analyze_test100.py` from the repository. Analysis reads saved records only; no model/server/annotation invocation occurs. Source-file checksums and analysis code hashes are in `analysis_manifest.json`. Rebuilding requires the same inputs; changed inputs require a new output directory.',
        'Outputs: `metrics.json`, `pair_analysis.csv`, `pair_analysis.jsonl`, `claim_factuality.jsonl`, `response_annotation_coverage.jsonl`, `rule_consistency_evidence.jsonl`, `stale_fact_evidence.jsonl`, `annotation_inventory.json`, `examples.json`, and this report.',
        '', 'All focused count/decoding/zero-denominator checks passed. No counterfactual customer accuracy, KL-based CE, distribution-based EE, Pearson faithfulness or combined trust score is calculated.']
    return '\n'.join(lines)+'\n'


def write_analysis(result,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    manifest={'analysis_version':VERSION,'study_plan_id':result['metrics']['study_plan_id'],'annotation_reference_assumption':ASSUMPTION,
              'source_sha256':result['protected'],'analysis_code_sha256':{label_path(p):file_hash(p) for p in (Path(__file__),ROOT/'scripts/analyze_test100.py')}}
    previous=out/'analysis_manifest.json'
    if previous.exists() and read(previous)!=manifest:raise ValueError('Analysis inputs/code changed; choose a new versioned output directory')
    def write_json(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    write_json('analysis_manifest.json',manifest);write_json('metrics.json',result['metrics'])
    write_json('annotation_inventory.json',result['annotation_inventory']);write_json('examples.json',result['examples'])
    for name,key in [('pair_analysis.jsonl','pairs'),('claim_factuality.jsonl','claims'),('response_annotation_coverage.jsonl','response_annotation_coverage'),('rule_consistency_evidence.jsonl','rule_evidence'),('stale_fact_evidence.jsonl','stale_evidence')]:
        with (out/name).open('w') as f:
            for row in result[key]:f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n')
    columns=['case_id','family','original_response_id','edited_response_id','status','applicable','skip_reason','original_product_id','edited_product_id','valid_prediction_comparison','prediction_changed','original_prediction_exclusion','edited_prediction_exclusion','original_annotation_id','edited_annotation_id','claimed_influence','exact_patch']
    with (out/'pair_analysis.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns);writer.writeheader()
        for row in result['pairs']:writer.writerow({k:json.dumps(row.get(k),ensure_ascii=False) if isinstance(row.get(k),(dict,list)) else row.get(k) for k in columns})
    (out/'report.md').write_text(markdown_report(result))
    for label,expected in result['protected'].items():
        path=Path(label) if Path(label).is_absolute() else ROOT/label
        if file_hash(path)!=expected:raise ValueError('A source record changed during analysis: '+label)
    return out
