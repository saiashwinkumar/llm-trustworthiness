"""Build the standalone research presentation; never write experiment directories.

Refresh: .venv/bin/python -B scripts/build_presentation_report.py --refresh-aws
Local rebuild: .venv/bin/python -B scripts/build_presentation_report.py
"""
import argparse
import base64
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import html
import json
import math
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from presentation_snapshot import refresh, latest
from choice_trust.storage import load_run
from choice_trust.model import prompt
from choice_trust.schema import validate_cases, visible_evidence
from choice_trust.interventions import eligible_explanation, apply

CONDITIONS = ('no_history', 'with_history')
LABELS = dict(no_history='Without support', with_history='With history')
SPLITS = ('development', 'validation', 'test')
OUT = ROOT/'presentation'

# Optional local-only enhancement: show the edited lines immediately while retaining
# every character of both saved prompts in keyboard-scrollable panels.
PROMPT_SCROLL_SCRIPT = """document.querySelectorAll('.counterfactual .prompt-text').forEach(panel => {
  const edit = panel.querySelector('.prompt-change, .prompt-original-change');
  if (edit) panel.scrollTop = Math.max(0, edit.getBoundingClientRect().top - panel.getBoundingClientRect().top + panel.scrollTop - 48);
});"""


def esc(value):
    return html.escape(str(value), quote=True)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'


def write(path, text):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(text, encoding='utf-8'); temp.replace(path)


def percentage(hits, n):
    return f'{100*hits/n:.1f}%' if n else 'No evaluated purchases'


def name(case, cid):
    return next(c['name'].capitalize() for c in case['candidates'] if c['id'] == cid)


def price(value):
    return f'{value:.2f}'


def history(case):
    return [e for e in case['evidence'] if e['type'] == 'history']


def support_choice(case):
    counts = Counter(e['value']['choice'] for e in history(case))
    return max(sorted(c['id'] for c in case['candidates']), key=lambda c: counts[c])


def evidence_description(case, eid):
    e = next(e for e in case['evidence'] if e['id'] == eid)
    if e['type'] == 'price': return f"{name(case, e['candidate_id'])} price {price(e['value'])}"
    if e['type'] == 'ad': return f"{name(case, e['candidate_id'])} advertised: {'yes' if e['value'] else 'no'}"
    if e['type'] == 'history': return f"support purchase {eid[1:]}: {name(case, e['value']['choice'])}"
    return f"{eid}: {e['value']}"


def offer_table(case):
    facts = {e['id']: e for e in case['evidence']}
    rows = ''.join(f"<tr><th scope='row'>{esc(c['name'].capitalize())} <span class='muted'>({esc(c['id'])})</span></th>"
                   f"<td>{price(facts[c['attributes']['price']]['value'])}</td>"
                   f"<td>{'Yes' if facts[c['attributes']['advertised']]['value'] else 'No'}</td></tr>"
                   for c in case['candidates'])
    return '<table><thead><tr><th>Product</th><th>Price</th><th>Advertised</th></tr></thead><tbody>'+rows+'</tbody></table>'


def support_table(case):
    candidates = case['candidates']
    rows = ''
    for index, e in enumerate(history(case), 1):
        v = e['value']
        ads = ', '.join(name(case, cid) for cid, yes in v['ads'].items() if yes) or 'None'
        prices = ''.join(f"<td>{price(v['prices'][c['id']])}</td>" for c in candidates)
        rows += f"<tr><th scope='row'>{index}</th>{prices}<td>{esc(ads)}</td><td><strong>{esc(name(case,v['choice']))}</strong></td></tr>"
    headers = ''.join(f"<th>{esc(c['name'].capitalize())}</th>" for c in candidates)
    return f"<div class='table-scroll'><table class='support-table'><thead><tr><th>Purchase</th>{headers}<th>Advertised</th><th>Chosen</th></tr></thead><tbody>{rows}</tbody></table></div>"


def prompt_panel(text, label, *, rendered=None):
    return f"<div class='prompt-panel'><p class='prompt-label'>{esc(label)}</p><pre class='prompt-text' tabindex='0' aria-label='{esc(label)}'>{rendered if rendered is not None else esc(text)}</pre></div>"


def highlight_prompt_changes(before, after):
    original, changed = [], []
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    for kind, a0, a1, b0, b1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        left, right = esc(''.join(a[a0:a1])), esc(''.join(b[b0:b1]))
        original.append(left if kind=='equal' else f"<span class='prompt-original-change'>{left}</span>" if left else '')
        changed.append(right if kind=='equal' else f"<mark class='prompt-change'>{right}</mark>" if right else '')
    return ''.join(original), ''.join(changed)


def workflow_diagram():
    steps = [('Prepare inputs','Offers, with or without five support purchases'),
             ('Predict','Score the candidates and save the choice'),
             ('Explain','Ask for reasons and supporting evidence IDs'),
             ('Check & edit','Check response structure; edit cited/control evidence or order'),
             ('Predict again','Use the same model on the changed input'),
             ('Compare','Measure answer changes and score shifts')]
    boxes = ''.join(f"<li><strong>{esc(title)}</strong><span>{esc(detail)}</span></li>" for title,detail in steps)
    return f"<figure class='workflow' aria-label='Study workflow'><figcaption>From customer evidence to behavioral tests</figcaption><ol class='workflow-steps'>{boxes}</ol><div class='workflow-accuracy'><span>Observed purchase <small>Hidden from the model</small></span><span class='flow-arrow' aria-hidden='true'>→</span><span>Compare with the original prediction <small>Accuracy and simple baselines, across separate household splits</small></span></div><p class='workflow-note'>Answer scores reflect the model’s relative preference for its answers, not customer purchase probabilities.</p></figure>"


def response_link(e):
    # The raw response remains downloadable even when index.html is copied alone.
    payload = dict(raw=e['raw'], prompt=e['prompt'], parsed=e.get('parsed'),
                   record_id=e['record_id'], record_hash=e['record_hash'],
                   prompt_version=e.get('prompt_version'), citation_policy_version=e.get('citation_policy_version'),
                   citation_assessment=e.get('citation_assessment'), reuse_origin=e.get('reuse_origin'),
                   original_record=e.get('original_record'))
    data = base64.b64encode(json_text(payload).encode()).decode()
    return f"<a download='{esc(e['case_id'])}-{e['condition']}-response.json' href='data:application/json;base64,{data}'>Full response &amp; prompt</a>"


def check_records(manifest, cases, data):
    validate_cases(cases)
    cm = {c['case_id']: c for c in cases}
    seen = set()
    for p in data['predictions']:
        key = p['case_id'], p['condition']
        assert key not in seen, 'Multiple effective predictions for one case/condition'
        seen.add(key)
        c = cm[p['case_id']]
        assert not p.get('synthetic')
        assert p['outcome'] == c['outcome'] and p['split'] == c['split']
        assert p['correct'] == (p['prediction'] == c['outcome'])
        # Reconstruct the allowlisted prompt, then change the hidden label. Neither
        # labels nor bookkeeping can influence the saved prediction input.
        assert p['prompt'] == prompt(c, p['condition'])
        assert prompt(dict(c, outcome=None), p['condition']) == p['prompt']
        assert p['score_method'] == 'candidate_sequence_conditional_likelihood_v2'
        assert math.isclose(sum(p['scores'].values()), 1, abs_tol=1e-9)
    ep = set()
    for e in data['explanations']:
        assert e['prediction_id'] not in ep, 'Multiple effective explanations'
        ep.add(e['prediction_id'])
        # Saved explanation prompts contain no query label field; quoted text is
        # read from the saved JSON response, never paraphrased into quotation marks.
        assert '"outcome"' not in e['prompt'] and '"correct"' not in e['prompt']
    pm = {p['record_id']: p for p in data['predictions']}
    for i in data['interventions']:
        if i['status'] != 'measured': continue
        before = pm[i['prediction_id']]
        assert i['before']['record_hash'] == before['record_hash']
        assert i['winner_changed'] == (before['prediction'] != i['after']['prediction'])
        assert i.get('edited_outcome') is None
        delta = i['after']['scores'][before['prediction']] - before['scores'][before['prediction']]
        assert math.isclose(delta, i['score_change'], abs_tol=1e-12)
        edited, error = apply(cm[i['case_id']], i['spec'])
        assert error is None
        assert i['after']['prompt'] == prompt(edited, i['condition'], i['spec'].get('order'))
    return {'record_hashes_and_parent_links': 'passed by load_run',
            'split_and_case_integrity': 'passed', 'prediction_prompts_reconstructed_without_query_outcomes': len(data['predictions']),
            'edited_prompts_and_measurements_reconstructed': sum(i['status']=='measured' for i in data['interventions']),
            'quote_checks': 'Each displayed quotation equals the decoded saved explanation field, or a marked exact prefix.'}


def compute(manifest, cases, data):
    cm = {c['case_id']: c for c in cases}
    pm = {p['record_id']: p for p in data['predictions']}
    development = [c for c in cases if c['split']=='development']
    pop = Counter(c['outcome'] for c in development)
    fixed = max(sorted(pop), key=pop.get)
    findings = {'prediction': {}, 'fixed_brand': fixed, 'examples': [], 'interventions': {},
                'method': {'accuracy_unit': 'purchase occasion within condition',
                           'baseline': 'Fixed brand chosen only from development outcomes; support majority uses the five supplied observations. Ties use sorted candidate IDs, matching project baselines.',
                           'uncited_controls': 'Only type/count-matched random removals with no cited IDs; require all five matched removals before including a case. Average controls within each case, then average cases.',
                           'illustrations': 'Explanation illustrations retain the development workflow case and first incorrect paired test example. Counterfactual illustrations show cited removal, comparable uncited removal, a price edit, and presentation order. Choose the first measured cited/uncited pair with equal removal counts by evidence type and identical source prediction/explanation; a keep-cited measurement qualifies when its actual masked complement is wholly uncited and type/count matched. Choose the first measured with-history price edit and ordering test, falling back to either condition. Selection does not require an answer change.'}}
    for split in SPLITS:
        result = {}
        for cond in CONDITIONS:
            rows = [p for p in data['predictions'] if p['split']==split and p['condition']==cond]
            result[cond] = dict(n=len(rows), correct=sum(p['prediction']==p['outcome'] for p in rows),
                fixed_correct=sum(p['outcome']==fixed for p in rows),
                support_correct=sum(support_choice(cm[p['case_id']])==p['outcome'] for p in rows),
                record_ids=[p['record_id'] for p in rows])
        intersection = set(p['case_id'] for p in data['predictions'] if p['split']==split and p['condition']=='no_history') & set(p['case_id'] for p in data['predictions'] if p['split']==split and p['condition']=='with_history')
        result['paired'] = {cond: sum(p['correct'] for p in data['predictions'] if p['condition']==cond and p['case_id'] in intersection) for cond in CONDITIONS}
        result['paired']['n'] = len(intersection)
        result['households'] = len({c['group_id'] for c in cases if c['split']==split})
        findings['prediction'][split] = result
    ex = defaultdict(dict)
    for e in data['explanations']:
        if e.get('parsed',{}).get('explanation'): ex[e['case_id']][e['condition']] = e
    paired = [cid for cid, rows in ex.items() if len(rows)==2]
    preferred = [cid for cid in paired if cid=='row-2342']
    if not preferred: preferred = [cid for cid in paired if all(pm[e['prediction_id']]['correct'] for e in ex[cid].values())][:1]
    wrong = [cid for cid in paired if cm[cid]['split']=='test' and any(not pm[e['prediction_id']]['correct'] for e in ex[cid].values())]
    if not wrong: wrong = [cid for cid in paired if any(not pm[e['prediction_id']]['correct'] for e in ex[cid].values())]
    chosen = list(dict.fromkeys(preferred + wrong[:1]))[:2] or paired[:2]
    for cid in chosen:
        findings['examples'].append(dict(case_id=cid, explanation_ids={cond:ex[cid][cond]['record_id'] for cond in CONDITIONS}))
    measured = [i for i in data['interventions'] if i['status']=='measured']
    for split in SPLITS:
        for cond in CONDITIONS:
            subset = [i for i in measured if i['split']==split and i['condition']==cond]
            group = {}
            for kind in ('cited_remove','presentation','attribute_sweep','categorical_toggle','history_mask'):
                rows = [i for i in subset if i['spec']['kind']==kind]
                if rows: group[kind] = dict(n=len(rows), cases=len({i['case_id'] for i in rows}),
                    changed=sum(i['winner_changed'] for i in rows), record_ids=[i['record_id'] for i in rows])
            disjoint = []; all_controls = []
            for cited in [i for i in subset if i['spec']['kind']=='cited_remove']:
                controls = [i for i in subset if i['prediction_id']==cited['prediction_id'] and i['spec']['kind']=='random_remove']
                if len(controls) != 5: continue
                uncited = [i for i in controls if set(i['spec']['evidence_ids']).isdisjoint(cited['spec']['evidence_ids'])]
                all_controls.append(dict(case_id=cited['case_id'], cited_id=cited['record_id'],
                    control_ids=[i['record_id'] for i in controls], disjoint_control_ids=[i['record_id'] for i in uncited]))
                if uncited:
                    disjoint.append(dict(case_id=cited['case_id'], cited_flip=int(cited['winner_changed']),
                        control_flip=sum(i['winner_changed'] for i in uncited)/len(uncited),
                        cited_id=cited['record_id'], control_ids=[i['record_id'] for i in uncited]))
            group['control_pairs'] = all_controls; group['uncited_pairs'] = disjoint
            findings['interventions'][split+'/'+cond] = group
    em = {e['record_id']:e for e in data['explanations']}
    removals = {i['prediction_id']:i for i in measured if i['spec']['kind']=='cited_remove'}
    matched = []
    for i in measured:
        if i['spec']['kind'] not in ('random_remove','cited_retain'): continue
        source = removals.get(i['prediction_id'])
        if not source or source['explanation_id']!=i['explanation_id']: continue
        facts = visible_evidence(cm[i['case_id']],i['condition'])
        cited = set(em[i['explanation_id']]['parsed']['evidence_ids'])
        removed = {e['id'] for e in i['edited_evidence'] if e.get('masked') and e['id'] in facts}
        source_removed = {e['id'] for e in source['edited_evidence'] if e.get('masked') and e['id'] in facts}
        if not removed or removed & cited or source_removed!=cited: continue
        types = Counter(facts[eid]['type'] for eid in removed)
        if types!=Counter(facts[eid]['type'] for eid in cited): continue
        matched.append((source,i,sorted(removed),dict(types)))
    selections = []
    if matched:
        cited,uncited,removed,types = matched[0]
        selections.extend([
            dict(category='cited',title='Remove or mask cited evidence',record_id=cited['record_id'],
                 removed_evidence_ids=sorted(cited['spec']['evidence_ids'])),
            dict(category='uncited',title='Remove comparable uncited evidence',record_id=uncited['record_id'],
                 removed_evidence_ids=removed,comparator_id=cited['record_id'],
                 matched_evidence_types=types,measured_as=uncited['spec']['kind'])])
    else:
        candidates=[i for i in measured if i['spec']['kind']=='cited_remove']
        if candidates: selections.append(dict(category='cited',title='Remove or mask cited evidence',record_id=candidates[0]['record_id']))
    for kind,category,title in [('attribute_sweep','price','Change a price'),('presentation','order','Change presentation order')]:
        candidates=[i for i in measured if i['spec']['kind']==kind]
        preferred=[i for i in candidates if i['condition']=='with_history']
        if candidates: selections.append(dict(category=category,title=title,record_id=(preferred or candidates)[0]['record_id']))
    findings['counterfactual_examples'] = selections
    findings['verified_uncited_comparisons'] = [dict(cited_id=a['record_id'],uncited_id=b['record_id'],
        removed_uncited_ids=ids,matched_types=types,measured_as=b['spec']['kind']) for a,b,ids,types in matched]
    findings['illustrative_intervention_ids'] = [s['record_id'] for s in selections]
    findings['source_counts'] = {k:len(v) for k,v in data.items()}
    findings['explanation_scopes'] = {s:{cond:len({e['case_id'] for e in data['explanations'] if e['split']==s and e['condition']==cond}) for cond in CONDITIONS} for s in SPLITS}
    findings['usable_explanations'] = sum(eligible_explanation(e) for e in data['explanations'])
    findings['explanation_prompt_versions'] = dict(Counter(e.get('prompt_version','historical') for e in data['explanations']))
    findings['citation_policies'] = dict(Counter(e.get('citation_policy_version','historical') for e in data['explanations']))
    findings['intervention_status_counts'] = dict(Counter(i['status'] for i in data['interventions']))
    return findings, ex


def prediction_sections(f, cases):
    fixed_name = name(cases[0], f['fixed_brand'])
    purposes = {'development':'Used to check the workflow, define plausible edits, and establish simple baselines. No model fine-tuning was performed.',
        'validation':'Used to examine prediction and explanation behavior before fixing the test protocol.',
        'test':'Evaluates choices in separate households. Earlier pilot test results informed the study, so this is exploratory evidence, not an untouched confirmatory test.'}
    blocks = []
    for split in SPLITS:
        r = f['prediction'][split]; pair = r['paired']; delta = pair['with_history']-pair['no_history']
        takeaway = 'History helps on the same purchases' if delta>0 else ('History lowers accuracy on the same purchases' if delta<0 else 'History leaves accuracy unchanged on the same purchases')
        h = r['with_history']
        if h['support_correct']>h['correct']: takeaway += ', but a simple household rule does better.'
        else: takeaway += '.'
        cards = ''
        for cond in CONDITIONS:
            q = r[cond]
            cards += f"<div class='metric'><h4>{LABELS[cond]}</h4><div class='big'>{percentage(q['correct'],q['n'])}</div><p>{q['correct']:,} correct out of {q['n']:,} evaluated purchases.</p><p class='baseline'>Always choosing {esc(fixed_name)}: <strong>{percentage(q['fixed_correct'],q['n'])}</strong></p></div>"
        blocks.append(f"<article class='split'><div class='split-head'><h3>{split.capitalize()}</h3><p class='takeaway'>{takeaway}</p></div><p class='purpose'>{purposes[split]}</p><div class='two metrics'>{cards}</div><p class='rule'>Choosing the most frequent product in the five support purchases: <strong>{percentage(h['support_correct'],h['n'])}</strong> ({h['support_correct']:,} of {h['n']:,}).</p></article>")
    return ''.join(blocks)


def example_input(case, preds):
    predictions = ' · '.join(f"{LABELS[cond]}: <strong>{esc(name(case,preds[(case['case_id'],cond)]['prediction']))}</strong>" for cond in CONDITIONS)
    panels = ''.join('<div><h4>'+LABELS[cond]+'</h4>'+prompt_panel(preds[(case['case_id'],cond)]['prompt'],'Exact prediction input')+'</div>' for cond in CONDITIONS)
    return f"<p class='eyebrow'>A real purchase example</p><div class='input-grid'><div><h3>Current product offers</h3>{offer_table(case)}</div><div><h3>Five support purchases</h3><p class='small'>Only the “With history” condition receives these observations.</p>{support_table(case)}</div></div><p class='small'>Prices use the dataset’s original units, shown to two decimals. Each support observation is a separate, <strong>unordered purchase</strong>; these are not a chronological sequence.</p><div class='answer-strip'><p>{predictions}</p><p>Observed purchase: <strong>{esc(name(case,case['outcome']))}</strong> <span class='hidden-label'>Hidden from the model</span></p></div><div class='saved-inputs'><h3>The exact inputs sent to the model</h3><p class='small'>These are the saved prompts, with their original precision and wording. Scroll within each input to read it in full.</p><div class='two'>{panels}</div></div>"


def explanation_sections(f, ex, cm, pm):
    result = ''
    for selected in f['examples']:
        cid = selected['case_id']; c = cm[cid]
        cards = ''; correctness = []
        for cond in CONDITIONS:
            e = ex[cid][cond]; p = pm[e['prediction_id']]
            raw = e['raw']['text']; text = e['parsed']['explanation']
            try: decoded = json.loads(raw)
            except ValueError: decoded = json.loads(raw[raw.index('{'):raw.rindex('}')+1])
            assert decoded['explanation'] == text
            excerpt = len(text)>420
            quote = text[:420].rsplit(' ',1)[0] if excerpt else text
            assert text.startswith(quote)
            correctness.append(p['correct'])
            cited = e['parsed']['evidence_ids']
            description = '; '.join(evidence_description(c, eid).split(':')[0] if eid.startswith('H') else evidence_description(c,eid).rsplit(' ',1)[0] if eid.startswith('P') else name(c,eid[-1])+' advertising' for eid in cited)
            if len(cited)>7:
                description = 'All current product prices and advertising indicators' + ('; all five support purchases' if all('H'+str(j) in cited for j in range(1,6)) else '')
                # Only use the summary when it exactly describes the IDs.
                expected = {e['id'] for e in c['evidence'] if e['type']!='history'} | ({'H'+str(j) for j in range(1,6)} if 'H1' in cited else set())
                if set(cited)!=expected: description = '; '.join(evidence_description(c,eid) for eid in cited)
            cards += f"<div class='explanation'><h4>{LABELS[cond]}</h4>{prompt_panel(p['prompt'],'Exact prediction input')}<p class='prediction-line'>Predicted <strong>{esc(name(c,p['prediction']))}</strong> · {'Correct' if p['correct'] else 'Incorrect'}</p><p class='small'>Observed: {esc(name(c,c['outcome']))} (hidden from model)</p>{prompt_panel(e['prompt'],'Exact explanation input')}<p class='quote-label'>Exact model {'excerpt' if excerpt else 'explanation'}</p><blockquote>{esc(quote)}{' […]' if excerpt else ''}</blockquote><p class='small evidence-note'><strong>Cited evidence:</strong> {esc(description)}.</p><p class='small'>{response_link(e)}</p></div>"
        prices = ' · '.join(f"{name(c,e['candidate_id'])} {price(e['value'])}" for e in c['evidence'] if e['type']=='price')
        ads = ', '.join(name(c,e['candidate_id']) for e in c['evidence'] if e['type']=='ad' and e['value']) or 'none'
        support = ', '.join(name(c,e['value']['choice']) for e in history(c))
        note = ''
        if cid=='row-2342':
            assert next(e['value'] for e in c['evidence'] if e['id']=='P_B') < next(e['value'] for e in c['evidence'] if e['id']=='P_A')
            note = 'The observed choice was predicted correctly, but the prose contains errors: Hiland is cheaper than Dannon, and Dannon and Weight have equal prices. A correct prediction does not guarantee a factually consistent explanation.'
        elif cid=='row-2026':
            assert next(e['value'] for e in c['evidence'] if e['id']=='P_C') > next(e['value'] for e in c['evidence'] if e['id']=='P_B')
            note = 'Weight costs more than Hiland, contrary to the first explanation. The second combines Hiland’s price with Weight’s advertising, although the saved prediction is Dannon.'
        title = 'A correct choice can come with a flawed explanation.' if all(correctness) else 'An explanation can fail to justify the saved choice.'
        result += f"<article class='example'><h3>{title}</h3><p class='small'>A = Dannon, B = Hiland, C = Weight, D = Yoplait.</p><p class='evidence-context'><strong>Offers:</strong> {esc(prices)}. Advertised: {esc(ads)}.<br><strong>Support choices:</strong> {esc(support)}.</p><div class='two'>{cards}</div>{'<p class="reading">'+esc(note)+'</p>' if note else ''}</article>"
    scopes = f['explanation_scopes']
    scope_parts = []
    for s in SPLITS:
        a,b = (scopes[s][cond] for cond in CONDITIONS)
        denom = len([c for c in cm.values() if c['split']==s])
        scope_parts.append(f'{s}: {a} of {denom} purchases per condition' if a==b else f'{s}: {a} without support and {b} with history, out of {denom} purchases')
    return result + '<p class="small scope">Explanation evidence covers subsets—'+esc('; '.join(scope_parts))+'. These illustrations are selected to show correct and incorrect predictions, not to estimate how often explanation errors occur.</p>'


def counterfactual_sections(f, data, cm, snapshot):
    im = {i['record_id']:i for i in data['interventions']}
    examples = ''
    for selection in f['counterfactual_examples']:
        rid=selection['record_id']
        i = im[rid]; c = cm[i['case_id']]; spec = i['spec']; kind=spec['kind']
        comparison_note = ''
        if selection['category']=='uncited':
            removed='; '.join(evidence_description(c,eid) for eid in selection['removed_evidence_ids'])
            change=f"Hide the uncited evidence: {removed}. Replace these values with NOT_PROVIDED (unknown); keep the cited facts."
            comparator=im[selection['comparator_id']]
            counts=', '.join(f"{n} {'prices' if role=='price' else 'advertising indicators' if role=='ad' else role+' observations'}" for role,n in sorted(selection['matched_evidence_types'].items()))
            mechanism='This was saved as a keep-cited test: retaining the cited facts masks the uncited ones. ' if kind=='cited_retain' else ''
            behavior='changed' if comparator['winner_changed'] else 'did not change'
            control_behavior='changed' if i['winner_changed'] else 'did not change'
            comparison_note=f"{mechanism}The two removals use the same purchase and match in number and type ({counts}). Cited removal {behavior} the predicted product; uncited removal {control_behavior} it. This is one measured paired case."
        elif kind=='attribute_sweep':
            old = next(e['value'] for e in c['evidence'] if e['id']==spec['evidence_ids'][0])
            product = name(c,next(e['candidate_id'] for e in c['evidence'] if e['id']==spec['evidence_ids'][0]))
            if math.isclose(spec['value'],old*.8,abs_tol=1e-12):
                change = f"Reduce {product}’s price by 20% ({price(old)} → {price(spec['value'])}, rounded here). The exact stored values appear in the prompts."
            else:
                change = f"Change {product}’s price from {old!r} to {spec['value']!r}."
        elif kind in ('cited_remove','random_remove'):
            removed = '; '.join(evidence_description(c,eid) for eid in spec['evidence_ids'])
            category = 'cited evidence' if kind=='cited_remove' else 'count/type-matched control evidence'
            change = f"Hide the {category}: {removed}. Replace these values with NOT_PROVIDED (unknown); keep the other supplied facts."
        elif kind in ('cited_retain','random_retain'):
            retained = '; '.join(evidence_description(c,eid) for eid in spec['evidence_ids'])
            category = 'cited evidence' if kind=='cited_retain' else 'count/type-matched control evidence'
            change = f"Keep only the {category}: {retained}. Replace other supplied evidence values with NOT_PROVIDED (unknown)."
        elif kind=='presentation':
            change = 'Reorder candidates and their evidence: '+ ' → '.join(name(c,cid) for cid in spec.get('order',[]))+'. Values and candidate labels stay the same.'
        else:
            change = 'Apply the saved evidence edit; highlighted lines show exactly what changed.'
        destination = snapshot/f"intervention-{rid[:12]}.json"
        write(destination, json_text(i))
        href = destination.relative_to(OUT).as_posix()
        before,after=i['before']['prompt'],i['after']['prompt']
        left,right=highlight_prompt_changes(before,after)
        original_result = 'Matches the observed purchase' if i['before']['prediction']==c['outcome'] else 'Does not match the observed purchase'
        edited_result = 'Prediction changed' if i['winner_changed'] else 'Prediction unchanged'
        panels = ("<div>"+prompt_panel(before,'Original LLM input',rendered=left)+f"<p class='cf-prediction'>Original prediction <strong>{esc(name(c,i['before']['prediction']))}</strong><span class='small'>{original_result}</span></p></div>"
                  +"<div>"+prompt_panel(after,'Changed LLM input',rendered=right)+f"<p class='cf-prediction'>Changed prediction <strong>{esc(name(c,i['after']['prediction']))}</strong><span class='small'>{edited_result}</span></p></div>")
        observed = f"Observed purchase in the original data: <strong>{esc(name(c,c['outcome']))}</strong> (hidden from the model). The edited scenario has no observed customer purchase."
        diff_note = '<mark>Gold highlights changed or moved lines.</mark> Inputs open near the edit; scroll within each panel for the complete saved prompt.' if before!=after else 'This test retained all supplied evidence, so the two saved input prompts are identical.'
        examples += f"<article class='counterfactual'><h3>{esc(selection['title'])}</h3><p class='eyebrow'>{LABELS[i['condition']]}</p><p class='edit-description'>{esc(change)}</p><p class='small observed-purchase'>{observed}</p><p class='small diff-key'>{diff_note}</p><div class='two'>{panels}</div>{'<p class="reading">'+esc(comparison_note)+'</p>' if comparison_note else ''}<p class='small'><a href='{href}'>Full inputs and measured outputs</a></p></article>"
    rows = ''; order_notes = []; comparisons = []; systematic = []
    for split in ('validation','test'):
        for cond in CONDITIONS:
            g = f['interventions'][split+'/'+cond]
            cr = g.get('cited_remove'); order = g.get('presentation')
            if cr:
                rows += f"<tr><th scope='row'>{split.capitalize()} · {LABELS[cond]}</th><td><strong>{cr['changed']} of {cr['cases']} purchases</strong></td></tr>"
            if order:
                order_notes.append(f"{split.capitalize()}, {LABELS[cond].lower()}: <strong>{order['changed']} of {order['n']} reorderings</strong> changed the predicted product, across {order['cases']} purchases.")
            unc = g['uncited_pairs']
            if unc:
                cited_rate = sum(p['cited_flip'] for p in unc)/len(unc)
                control_rate = sum(p['control_flip'] for p in unc)/len(unc)
                direction = 'more often' if cited_rate>control_rate else 'less often' if cited_rate<control_rate else 'equally often'
                comparisons.append(f"{split.capitalize()}, {LABELS[cond].lower()}: cited removal changed the answer {direction} than comparable uncited removal ({100*cited_rate:.1f}% versus {100*control_rate:.1f}%), on {len(unc)} paired purchases. Controls are averaged within each purchase.")
            if split=='test':
                for kind,label in [('attribute_sweep','price edits'),('categorical_toggle','advertising edits'),('history_mask','removing support purchases')]:
                    a=g.get(kind)
                    if a: systematic.append(f"{LABELS[cond]}: {label} changed {a['changed']} of {a['n']} predictions across {a['cases']} purchases.")
    aggregate = ''
    if rows:
        aggregate += f"<div class='counter-summary'><h3>Removing cited evidence sometimes changes the answer.</h3><p>Each purchase below has one measured removal of its explanation’s complete cited evidence set.</p><table><thead><tr><th>Evidence sample</th><th>Predicted product changed</th></tr></thead><tbody>{rows}</tbody></table></div>"
    if order_notes:
        aggregate += '<div class="counter-summary"><h3>The answer is sensitive to presentation order.</h3><p>The products, values, and labels stay fixed; only the order of candidates and their evidence changes. Multiple reorderings of one purchase are related measurements.</p><div class="two order-results">'+''.join('<p>'+n+'</p>' for n in order_notes)+'</div></div>'
    control_limit = 'The random control sets can reuse cited facts. The uncited example above instead uses an independently verified, type/count-matched complement measured in a keep-cited test. That single-case comparison does not establish a general advantage for cited evidence.' if any(s['category']=='uncited' and s.get('measured_as')=='cited_retain' for s in f['counterfactual_examples']) else 'The measured random controls can reuse cited facts. Removal effects alone do not establish that citations identify uniquely influential evidence.'
    aggregate += '<p class="reading">'+(' '.join(comparisons) if comparisons else control_limit)+'</p>'
    if systematic: aggregate += '<div class="counter-summary"><h3>Other measured input changes</h3><p>'+' '.join(systematic)+'</p></div>'
    return examples+aggregate


def render(f, manifest, cases, data, ex, snapshot):
    cm={c['case_id']:c for c in cases}; pm={p['record_id']:p for p in data['predictions']}
    predpairs={(p['case_id'],p['condition']):p for p in data['predictions']}
    input_case=cm[f['examples'][0]['case_id']]
    test=f['prediction']['test']; a=test['no_history']; b=test['with_history']
    conclusion = f"On test purchases, accuracy is {percentage(a['correct'],a['n'])} without support and {percentage(b['correct'],b['n'])} with history. The simple support-majority rule reaches {percentage(b['support_correct'],b['n'])}."
    css=(ROOT/'presentation_src/style.css').read_text()
    body=f"""<header><p class='eyebrow'>Customer choice · Research findings</p><h1>Predicting a choice.<br>Explaining the evidence.</h1>{workflow_diagram()}</header>
<main>
<section class='intro'><h2>What was studied</h2><p class='lead'>Can an LLM predict customer product choices, and do its explanations identify evidence that actually influences those predictions?</p></section>
<section><h2>What the model saw</h2><p>Qwen3-1.7B chose among four yogurt products using prices and advertising indicators. The two conditions differ only in whether five purchases from the same household are supplied. The current purchase label is hidden from both prediction and explanation inputs.</p>{example_input(input_case,predpairs)}</section>
<section><h2>Prediction findings</h2><p>Households are kept separate across splits. Accuracy means choosing the product that was actually purchased. The fixed-brand baseline always chooses the most common product in development; the household rule uses only the five supplied purchases.</p>{prediction_sections(f,cases)}</section>
<section><h2>What the explanations said</h2><p>Explanations were requested after the prediction was saved. Evidence IDs are short labels: <strong>P_A</strong> means the price of product A; <strong>H1</strong> means one household support purchase; <strong>F_C</strong> is product C’s advertising indicator.</p><p>Readable JSON and existing, nonduplicated citations make a response usable for evidence edits. Any number of available IDs is allowed. This checks structure—not factual accuracy or whether the cited evidence influenced the answer.</p>{explanation_sections(f,ex,cm,pm)}</section>
<section><h2>What changed during counterfactual tests</h2><p>We changed the model’s input and scored a fresh prediction. Each example pairs the exact original input and prediction with the changed input and prediction. Measurements concern model behavior, not a new observation of what the customer bought.</p>{counterfactual_sections(f,data,cm,snapshot)}</section>
<section class='lessons'><h2>What we learned and what remains uncertain</h2><p><strong>Household evidence helps, but simple behavior is a demanding baseline.</strong> {conclusion}</p><p><strong>Prediction accuracy and explanation quality are different questions.</strong> The displayed examples contain factual inconsistencies. Citation compliance does not establish faithfulness, and these examples are not a systematic human-review estimate.</p><p><strong>Behavioral tests provide evidence about explanation faithfulness.</strong> Sensitivity to edited facts and to their presentation must be considered together. Edited scenarios cannot reveal the real customer’s next choice.</p><p><strong>The scope is specific.</strong> These findings apply to this model, yogurt dataset, and evaluated cases. Explanation and intervention samples cover subsets of purchases; repeated purchases within a household are not independent evidence of generalization.</p></section>
</main><footer><p><a href='support/{snapshot.name}/sources.html'>Supporting records and methods</a> · Full responses, source counts, provenance, and reproducible calculations.</p></footer>"""
    return f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Customer choice — research findings</title><style>{css}</style></head><body>{body}<script>{PROMPT_SCROLL_SCRIPT}</script></body></html>"


def supporting_files(snapshot, f, manifest, checks):
    write(snapshot/'presentation_findings.json', json_text(f))
    write(snapshot/'verification.json', json_text(checks))
    links = [('presentation_findings.json','Computed findings, source IDs, prompt cohorts, and sample sizes'),
             ('verification.json','Verification results'),('snapshot_provenance.json','Read boundaries and source hashes'),
             ('independent_verification.json','Independent numeric, link, and partial-record checks'),
             ('run_manifest.json','Model revision, inference settings, dataset and run provenance'),
             ('study_plan.json','Saved execution plan and subset assignments'),('cases.jsonl','Cases and household split assignments'),
             ('predictions.jsonl','Full prediction inputs and outputs'),('explanations.jsonl','Full explanation prompts, responses, and preserved assessments'),
             ('interventions.jsonl','All intervention records, including measured and skipped records'),
             ('manual_audit.csv','Audit worksheet (blank fields are not evidence of human review)')]
    entries=''.join(f"<li><a href='{snapshot.name}/{file}'>{esc(label)}</a></li>" for file,label in links if (snapshot/file).exists() or file=='independent_verification.json')
    cohorts=''.join(f'<li>{esc(k)}: {v} responses</li>' for k,v in f['explanation_prompt_versions'].items())
    text=f"""<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Supporting records</title><style>body{{max-width:850px;margin:60px auto;padding:0 24px;font:18px/1.65 system-ui;color:#213b34}}a{{color:#245e50}}li{{margin:12px 0}}code{{overflow-wrap:anywhere}}</style><a href='../index.html'>Back to presentation</a><h1>Sources and methods</h1><p>The presentation uses a read-only, immutable local snapshot of the authoritative AWS continuation. Its files are separate from the experiment and the queue’s own reports. Complete newline-terminated records were copied in child-before-parent order. Record hashes, dataset identity, parent references, saved prompts, and measurements were checked before rendering.</p><h2>Files</h2><ul>{entries}</ul><h2>Interpretation</h2><p>All counts refer to effective records in this continuation. Historical source records nested under original_record are provenance, not extra observations. Predictions use normalized conditional answer-sequence likelihoods, not calibrated probabilities of customer purchases. The main presentation uses choice accuracy and observed answer changes, not answer-score metrics.</p><p>Fixed-brand baseline: fit the most frequent product on development only. Support baseline: choose the modal product across the five unordered support purchases. Ties use sorted candidate IDs, as in the project evaluation. Baselines are evaluated on the same purchases as the corresponding model column. Test interpretation is exploratory because an earlier pilot inspected test outcomes. No fine-tuning is recorded.</p><p>Counterfactual summaries exclude skipped records. Removal denominators count purchases; order denominators count actual reorderings and explicitly identify distinct purchases. Random controls are count/type matched but can overlap cited evidence. The builder only calls a control uncited if its IDs are disjoint from the citations, and compares those controls within purchase before averaging purchases. It requires five measured random removal controls before a paired case contributes. A missing uncited comparison is not filled in.</p><p>Example selection: retain the development workflow example when available; choose the first paired incorrect test example in saved response order. Edited-input illustrations show the four requested categories: cited removal, comparable uncited removal, a price edit, and presentation order. The cited/uncited pair shares its original prediction and explanation and removes equal counts of each evidence type. A saved keep-cited measurement qualifies as uncited removal when its actual masked complement is wholly uncited and matches those counts; this is verified from the edited evidence. Price and ordering examples are the first measured with-history records, falling back to either condition. Selection does not require the answer to change. Exact saved prediction and explanation prompts are displayed, with original whitespace and precision. Counterfactual highlights mark changed lines; the complete original and edited prompt text is retained. These are illustrative measurements, not a representative error-rate sample. The derived uncited pair is reported separately from the five-random-control aggregate.</p><h2>Explanation cohorts and policy</h2><ul>{cohorts}</ul><p>The current citation policy is available-evidence-unlimited-v1. The original JSON schema is retained; JSON readability, required fields, existing IDs, and duplicate citations are separate checks. Original raw text, prompts, and earlier assessments remain in the records. Older explanation prompts were not regenerated. Eligibility for evidence interventions does not establish correctness or faithfulness.</p><h2>Refresh</h2><p>From the project root:</p><pre><code>.venv/bin/python -B scripts/build_presentation_report.py --refresh-aws</code></pre><p>This reads EC2 using the existing SSH identity. It makes no model calls and performs no remote writes. Omit --refresh-aws to rebuild from the last saved snapshot. If SSH or validation fails, the published page stays unchanged. Open presentation/index.html locally, or unzip presentation/choice-study-presentation.zip for the page and all linked sources.</p></html>"""
    write(OUT/'support/sources.html', text)
    # The main page links the immutable matching source index, so an in-flight
    # refresh cannot mix the old presentation with a new snapshot's provenance.
    write(snapshot/'sources.html', text.replace("href='../index.html'", "href='../../index.html'").replace("href='"+snapshot.name+'/', "href='"))


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--refresh-aws',action='store_true'); args=parser.parse_args()
    snapshot=refresh() if args.refresh_aws else latest()
    manifest,cases,data=load_run(snapshot)
    checks=check_records(manifest,cases,data)
    checks['presentation_version']='research-presentation-v3-four-counterfactual-tests'
    checks['builder_sources']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__),ROOT/'scripts/presentation_snapshot.py',ROOT/'scripts/verify_presentation_report.py',ROOT/'presentation_src/style.css')}
    f,ex=compute(manifest,cases,data)
    page=render(f,manifest,cases,data,ex,snapshot)
    assert all(x not in page for x in ('<script src','<select','<progress','role="tab"','https://','http://'))
    assert page.count('<script>')==1 and PROMPT_SCROLL_SCRIPT in page
    assert page.count('<h2>')==6
    supporting_files(snapshot,f,manifest,checks)
    candidate=OUT/'.candidate-index.html'
    write(candidate,page)
    from verify_presentation_report import test_snapshot_reader, verify_display
    test_snapshot_reader()
    independent=verify_display(snapshot,candidate)
    write(snapshot/'independent_verification.json',json_text(independent))
    candidate.replace(OUT/'index.html')
    archive=OUT/'choice-study-presentation.zip'; temp=archive.with_suffix('.tmp')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in [OUT/'index.html',OUT/'README.md',OUT/'support/sources.html',*sorted(snapshot.iterdir())]:
            if path.is_file(): z.write(path,path.relative_to(OUT))
    temp.replace(archive)
    print(json_text(dict(page=str(OUT/'index.html'),bundle=str(archive),source_counts=f['source_counts'],verification=checks)))


if __name__=='__main__': main()
