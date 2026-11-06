"""Strict Luna claim/rule schema and offline structural/traceability validation."""
import json
from .explanation_annotation import GROUPS,RELATIONSHIPS,ROLES,STATUSES,validate_annotations

SCHEMA_VERSION='luna-claims-rules-v1'
RULE_TYPES=('choose_uniquely_cheapest_current_product','choose_most_frequent_support_product','advertising_priority','fixed_product_rule','other_explicit_rule','ambiguous_or_unspecified')
SCOPES=('all_current_candidates','supplied_household_history','specified_candidate_subset','mixed_information_groups','other_or_unclear')


def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def strings(values=None):return {'type':'array','items':{'type':'string',**({'enum':list(values)} if values else {})}}


def annotation_schema(candidates,provenance):
    ids=[c['id'] for c in candidates];fields=sorted({f for p in provenance.values() for f in p['source_fields']})
    claim=obj({'claim_id':{'type':'string'},'exact_quote':{'type':'string'},'concept_groups':strings(GROUPS),
        'relationship_type':{'type':'string','enum':sorted(RELATIONSHIPS)},'claimed_role':{'type':'string','enum':sorted(ROLES)},
        'direction':obj({'favors':strings(ids),'disfavors':strings(ids)}),
        'mapped_evidence_ids':strings(provenance),'source_fields':strings(fields),
        'factual_status':{'type':'string','enum':sorted(STATUSES)},'annotation_note':{'type':'string'}})
    rule=obj({'rule_id':{'type':'string'},'exact_quote':{'type':'string'},'claim_ids':strings(),
        'explicit':{'type':'boolean'},'sufficiently_specified':{'type':'boolean'},
        'concept_groups':strings(GROUPS),'scope':{'type':'string','enum':list(SCOPES)},'scope_note':{'type':'string'},
        'conditions':strings(),'rule_type':{'type':'string','enum':list(RULE_TYPES)},
        'premise_claim_ids':strings(),'factual_premises_status':{'type':'string','enum':['valid','invalid','unassessable','not_applicable']},
        'mapped_evidence_ids':strings(provenance),'source_fields':strings(fields),
        'expected_original_candidate':{'type':['string','null'],'enum':ids+[None]},
        'eligible_for_counterfactual_testing':{'type':'boolean'},'eligibility_reason':{'type':'string'}})
    return obj({'claims':{'type':'array','items':claim},'rules':{'type':'array','items':rule},
        'coverage':obj({'all_substantive_claims_addressed':{'type':'boolean'},'omitted_quotes':strings(),'notes':{'type':'string'}})})


def validate_result(raw_text,job,api):
    """Never rewrite returned quotes, IDs or labels. Semantic truth remains unchecked."""
    from jsonschema import Draft202012Validator
    duplicates=[]
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:duplicates.append(k)
            out[k]=v
        return out
    parsed=None;issues=[];warnings=[]
    try:parsed=json.loads(raw_text,object_pairs_hook=pairs)
    except (ValueError,TypeError) as error:issues.append('JSON parse error: '+str(error))
    if parsed is not None:
        issues += ['Schema '+('/'.join(map(str,e.absolute_path)) or '<root>')+': '+e.message for e in Draft202012Validator(job['schema']).iter_errors(parsed)]
    if duplicates:issues.append('Duplicate JSON keys: '+', '.join(duplicates))
    inp=job['annotation_input'];explanation=inp['explanation'];prov=inp['provenance']
    claims=parsed.get('claims') if isinstance(parsed,dict) else None
    claim_checks=[]
    if isinstance(claims,list):
        _,old=validate_annotations(json.dumps({'claims':claims}),explanation=explanation,candidates=inp['candidates'],provenance=prov)
        issues+=old['schema_issues'];claim_checks=old['claim_checks']
        for check in claim_checks:issues += [f"Claim {check.get('claim_id',check['index'])}: {v}" for v in check['issues']]
        if [c.get('claim_id') for c in claims if isinstance(c,dict)]!=['C'+str(i+1) for i in range(len(claims))]:issues.append('Claim IDs must be stable C1..Cn in explanation order')
        field_groups={f:g for p in prov.values() for f in p['source_fields'] for g in p['concept_groups']}
        for c in claims:
            if not isinstance(c,dict):continue
            refs=c.get('source_fields',[]);groups=c.get('concept_groups',[])
            if isinstance(refs,list) and isinstance(groups,list) and all(isinstance(x,str) for x in refs+groups):
                if not {field_groups[f] for f in refs if f in field_groups}<=set(groups):issues.append('Claim '+str(c.get('claim_id'))+': source fields require additional concept group(s)')
    claims=claims if isinstance(claims,list) else []
    by_id={c.get('claim_id'):c for c in claims if isinstance(c,dict) and isinstance(c.get('claim_id'),str)}
    rules=parsed.get('rules') if isinstance(parsed,dict) else None
    rule_checks=[]
    if isinstance(rules,list):
        if [r.get('rule_id') for r in rules if isinstance(r,dict)]!=['R'+str(i+1) for i in range(len(rules))]:issues.append('Rule IDs must be stable R1..Rn')
        for r in rules:
            problems=[]
            if not isinstance(r,dict):continue
            if not isinstance(r.get('exact_quote'),str) or not r['exact_quote'] or r['exact_quote'] not in explanation:problems.append('Rule quote is not an exact nonempty substring')
            for key in ('claim_ids','premise_claim_ids'):
                value=r.get(key)
                if not isinstance(value,list) or any(not isinstance(cid,str) or cid not in by_id for cid in value):problems.append('Unknown or invalid '+key)
            mapped=r.get('mapped_evidence_ids');refs=r.get('source_fields')
            if isinstance(mapped,list) and isinstance(refs,list) and all(isinstance(v,str) for v in mapped+refs):
                covered={f for eid in mapped if eid in prov for f in prov[eid]['source_fields']}
                if not set(refs)<=covered:problems.append('Rule source fields not covered by mapped evidence')
            if r.get('eligible_for_counterfactual_testing') is True:
                if not r.get('explicit') or not r.get('sufficiently_specified'):problems.append('Eligible rule must be explicit and sufficiently specified')
                if r.get('factual_premises_status')!='valid':problems.append('Eligible rule requires valid factual premises')
                if r.get('rule_type')=='ambiguous_or_unspecified':problems.append('Ambiguous rule cannot be marked eligible')
                premise_ids=r.get('premise_claim_ids',[])
                if isinstance(premise_ids,list) and all(isinstance(cid,str) for cid in premise_ids):
                    if any(by_id.get(cid,{}).get('factual_status')!='supported' for cid in premise_ids):problems.append('Eligible rule has premise claims not labelled supported')
            if not isinstance(r.get('eligibility_reason'),str) or not r['eligibility_reason'].strip():problems.append('Missing eligibility reason')
            rule_checks.append({'rule_id':r.get('rule_id'),'issues':problems});issues += [str(r.get('rule_id'))+': '+s for s in problems]
    coverage=parsed.get('coverage') if isinstance(parsed,dict) else None
    if isinstance(coverage,dict):
        omitted=coverage.get('omitted_quotes',[])
        if isinstance(omitted,list) and any(not isinstance(q,str) or not q or q not in explanation for q in omitted):issues.append('Coverage omitted quote is not an exact substring')
        if coverage.get('all_substantive_claims_addressed') is True and omitted:issues.append('Coverage self-report conflicts with omitted quotes')
    rules=rules if isinstance(rules,list) else []
    output=api.get('output') or []
    complete=api.get('status')=='completed' and api.get('incomplete_details') is None and api.get('error') is None
    refusals=[v.get('refusal') for item in output if isinstance(item,dict) for v in item.get('content',[]) or [] if isinstance(v,dict) and v.get('type')=='refusal']
    if not complete:issues.append('API response is incomplete, failed or nonterminal')
    if refusals:issues.append('API refusal returned')
    returned=api.get('model') or '';model_matches=returned==job['request']['model'] or returned.startswith(job['request']['model']+'-')
    if not model_matches:issues.append('Returned model does not match requested Luna identity')
    if any(not isinstance(item,dict) or item.get('status') not in (None,'completed') for item in output):issues.append('An API output item is incomplete')
    reasoning=api.get('reasoning') or {}
    if reasoning.get('effort') not in (None,job['request']['reasoning']['effort']):issues.append('API reported a different reasoning effort')
    if api.get('max_output_tokens') not in (None,job['request']['max_output_tokens']):issues.append('API reported a different output allowance')
    self_complete=isinstance(coverage,dict) and coverage.get('all_substantive_claims_addressed') is True and not coverage.get('omitted_quotes')
    if not self_complete:issues.append('Model does not report complete substantive claim coverage')
    rule_links={cid for r in rules or [] if isinstance(r,dict) for cid in r.get('claim_ids',[]) if isinstance(cid,str)}
    if any(c.get('claimed_role')=='decisive' and c.get('claim_id') not in rule_links for c in claims or [] if isinstance(c,dict)):warnings.append('Inspect decisive claims without a corresponding rule entry')
    return parsed,{'parse_ok':parsed is not None,'schema_and_traceability_ok':not issues,'issues':issues,'warnings':warnings,
        'claim_checks':claim_checks,'rule_checks':rule_checks,'api_completed':complete,'generation_truncated':api.get('status')=='incomplete',
        'model_identity_matches':model_matches,'model_reports_claim_coverage_complete':self_complete,
        'semantic_correctness_checked':False,'coverage_verified':False,'faithfulness_assessed':False,'human_reviewed':False}
