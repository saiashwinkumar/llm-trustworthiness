"""Inspection displays only. These helpers never create an API client or call it."""
import json
from collections import Counter
from html import escape
from .observations import canonical_price
from .luna_annotations import SETTINGS,SDK_SETTINGS,MODEL,read


def table(rows):
    import pandas as pd
    from IPython.display import display
    with pd.option_context('display.max_colwidth',None,'display.max_columns',None,'display.max_rows',None):display(pd.DataFrame(rows))


def details(title,value,open=False):
    from IPython.display import HTML,display
    text=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2)
    display(HTML('<details'+(' open' if open else '')+'><summary>'+escape(title)+'</summary><pre>'+escape(text)+'</pre></details>'))


def show_configuration(inspection):
    print('Requested annotation model:',MODEL)
    print('API settings:',json.dumps(SETTINGS))
    print('SDK/transport settings:',json.dumps(SDK_SETTINGS))
    print('Frozen original-only jobs:',len(inspection.jobs),'| seed:',inspection.manifest['seed'])
    print('No credentials are needed for preparation, selection, prompt preview or summaries.')
    print('OPENAI_API_KEY is read only when an annotation cell is executed. Its value is never displayed.')
    print('Existing records are model-generated and not human-reviewed. No semantic correctness is inferred from schema validation.')


def show_selected(inspection):
    table([{'case_id':j['case_id'],'source_response_id':j['source_response_id'],'source_hash':j['source_response_sha256'],
            'exact original explanation':j['annotation_input']['explanation']} for j in inspection.jobs])


def show_source(inspection,job_id=None):
    job=inspection.by_id[job_id or inspection.jobs[0]['job_id']];inp=job['annotation_input']
    print('Case:',job['case_id'],'| source response:',job['source_response_id'])
    table(inp['candidates'])
    print('EXACT FACTUAL INPUT\n'+inp['observations']['text'])
    print('ORIGINAL PREDICTION:',inp['predicted_candidate'])
    print('EXACT GENERATED EXPLANATION\n'+inp['explanation'])
    print('PREDICTOR ORIGINAL GLOBAL CITATIONS:',inp['model_citations'])
    details('Evidence IDs and field provenance',inp['provenance'])


def show_prompt(inspection,job_id=None):
    details('COMPLETE LUNA REQUEST — full guide, exact input and strict schema; no credential',inspection.preview(job_id),open=True)


def visible_values(job,fields):
    out={}
    if not isinstance(fields,list):return {'diagnostic':'Invalid source-field list; inspect raw output and validation errors'}
    for field in fields:
        if not isinstance(field,str):out['INVALID_SOURCE_FIELD_REFERENCE']=repr(field);continue
        if field not in job['source_values']:out[field]='UNKNOWN_SOURCE_FIELD';continue
        value=job['source_values'][field]
        if value is None:out[field]='NOT_PROVIDED'
        elif '.prices.' in field:out[field]='$'+canonical_price(value)
        elif '.advertised.' in field:out[field]='ADVERTISED' if value else 'NOT_ADVERTISED'
        else:out[field]=value
    return out


def show_annotation(inspection,result):
    if not isinstance(result,dict) or 'raw_annotation_response' not in result:
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    job=inspection.by_id[result['job_id']]
    print('MODEL-GENERATED ANNOTATION — NOT HUMAN-REVIEWED')
    print('Requested/returned model:',result['requested_model'],result['returned_model'])
    print('API response:',result['api_response_id'],'| status:',result['api_status'],'| usage:',result['usage'])
    print('EXACT RAW ANNOTATION RESPONSE\n'+result['raw_annotation_response'])
    parsed=result.get('parsed_annotation')
    if isinstance(parsed,dict):
        claims=parsed.get('claims') if isinstance(parsed.get('claims'),list) else []
        rules=parsed.get('rules') if isinstance(parsed.get('rules'),list) else []
        table([{**c,'referenced model-visible values':visible_values(job,c.get('source_fields',[]))} for c in claims if isinstance(c,dict)])
        print('RULE ANNOTATIONS (potential eligibility, not counterfactual outcomes)')
        if rules:table([{**r,'referenced model-visible values':visible_values(job,r.get('source_fields',[]))} for r in rules if isinstance(r,dict)])
        else:print('The model returned no rule objects. Inspect the original explanation for missed rules.')
        print('MODEL-REPORTED COVERAGE:',parsed.get('coverage'))
    details('Structural/traceability diagnostics; semantic correctness and coverage are not automatically verified',result['validation'],open=True)
    details('Exact raw API response',result['raw_api_response'])
    details('Requested and API-reported effective settings',{'requested':result['requested_settings'],'effective':result['effective_settings']})


def show_summary(inspection):
    rows=[];saved=valid=0
    for job,state in zip(inspection.jobs,inspection.status()):
        path=inspection.result_path(job);record=read(path) if path.exists() else None
        parsed=record.get('parsed_annotation') if record else None
        diag=record.get('validation') if record else None
        claims=parsed.get('claims') if isinstance(parsed,dict) and isinstance(parsed.get('claims'),list) else None
        rules=parsed.get('rules') if isinstance(parsed,dict) and isinstance(parsed.get('rules'),list) else None
        if record:saved+=1
        if diag and diag['schema_and_traceability_ok']:valid+=1
        rows.append({'case_id':job['case_id'],'source_response_id':job['source_response_id'],'status':state['status'],
            'api_response_id':record.get('api_response_id') if record else None,
            'claim_count':len(claims) if claims is not None else None,
            'model_factual_labels':dict(Counter(str(c.get('factual_status')) for c in claims if isinstance(c,dict))) if claims is not None else None,
            'rule_count':len(rules) if rules is not None else None,
            'rules_potentially_eligible':sum(r.get('eligible_for_counterfactual_testing') is True for r in rules if isinstance(r,dict)) if rules is not None else None,
            'model_reports_complete_coverage':diag.get('model_reports_claim_coverage_complete') if diag else None,
            'structure_traceability_ok':diag.get('schema_and_traceability_ok') if diag else None,
            'diagnostic_issues':diag.get('issues') if diag else 'No annotation yet',
            'diagnostic_warnings':list(dict.fromkeys(diag.get('warnings',[])+[f"{c['claim_id']}: {w}" for c in diag.get('claim_checks',[]) for w in c.get('warnings',[])])) if diag else None,
            'human_reviewed':False})
    table(rows)
    print(f'This stage: {saved}/10 saved API annotations; {valid}/10 structurally traceable. Source-original scope:10/100; actual valid original annotation coverage from this stage:{valid}/100. Edited responses:0/642.')
    print('All jobs are original-only. Claim coverage and semantic correctness require inspection; neither is established by valid JSON or a model self-report.')
    print('No counterfactual rule-consistency or stale-fact labels/metrics are created by this stage.')
