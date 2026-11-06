#!/usr/bin/env python3
"""Render four-case original claims and exact per-edit KL arithmetic as HTML."""
from __future__ import annotations

from html import escape
from hashlib import sha256
from math import log
from pathlib import Path
from statistics import mean
import json

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'choice_study/choice_faithfulness_8x50_v1'
DEST = STUDY / 'four_concept_sensitivity_v1'
PARENTS = ('CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY')
CONCEPTS = (*PARENTS, 'PRESENTATION_CONTROL')
NAMES = {'CURRENT_PRICES': 'Current prices', 'CURRENT_ADVERTISING': 'Current advertising',
         'HOUSEHOLD_HISTORY': 'Household history', 'PRESENTATION_CONTROL': 'Presentation controls'}
FAMILY = (
    ('CURRENT_PRICE', 'CURRENT_PRICES', 'Q_price', 'Current-price edit'),
    ('CURRENT_ADVERTISING', 'CURRENT_ADVERTISING', 'Q_ads', 'Current-advertising edit'),
    ('SUPPORT_PURCHASE', 'HOUSEHOLD_HISTORY', 'Q_history,support', 'Support-purchase edit'),
    ('HISTORICAL_OFFER_REMOVAL', 'HOUSEHOLD_HISTORY', 'Q_history,offers', 'Historical-offer removal'),
    ('PRODUCT_ORDER_CONTROL', 'PRESENTATION_CONTROL', 'Q_control,order', 'Product-order control'),
    ('ANSWER_MAPPING_CONTROL', 'PRESENTATION_CONTROL', 'Q_control,mapping', 'Answer-mapping control'),
)
COLORS = {'A': '#4f9dab', 'B': '#dfa25a', 'C': '#88a76a', 'D': '#b78cb1', 'INVALID': '#67767b'}


def read(path):
    return json.loads(Path(path).read_text())


def h(value):
    return escape(str(value), quote=True)


def bar(dist, names):
    total = dist['n']
    segments = []
    legend = []
    for code in ('A', 'B', 'C', 'D', 'INVALID'):
        name = names.get(code, 'INVALID')
        count = dist['counts'][name]
        if count:
            segments.append(f'<i style="width:{count / total * 100:.3f}%;background:{COLORS[code]}" title="{h(code)}: {count}/{total}"></i>')
        legend.append(f'<span><b style="background:{COLORS[code]}"></b>{h(code)} {count}</span>')
    return f'<div class="bar">{"".join(segments)}</div><div class="legend">{"".join(legend)}</div>'


def vector(dist, names):
    return '[' + ', '.join(str(dist['counts'][names.get(code, 'INVALID')]) for code in ('A', 'B', 'C', 'D', 'INVALID')) + ']'


def shares(dist, names):
    return ' · '.join(f'{code}: {dist["counts"][names[code]]}/50 ({dist["counts"][names[code]] * 2}%)'
                      for code in ('A', 'B', 'C', 'D'))


def reasons(stats):
    n = stats['valid_annotations']
    return ''.join(f'<div class="reason"><span>{h(NAMES[concept])}</span><div class="reason-track"><i style="width:{(stats["claimed_influence"].get(concept, 0) / n * 100) if n else 0:.1f}%"></i></div><b>{stats["claimed_influence"].get(concept, 0)}/{n}</b></div>'
                   for concept in CONCEPTS)


def pattern_list(stats):
    items = []
    for item in stats['influence_patterns']:
        label = ' + '.join(NAMES[concept] for concept in item['concepts']) or 'No concept claimed influential'
        items.append(f'<li>{h(label)} <b>{item["count"]}/{stats["valid_annotations"]}</b></li>')
    return ''.join(items)


def edit_description(family, condition, names):
    patch = condition['patch']
    if family == 'CURRENT_PRICE':
        item = patch[0]
        cid = item['field'].rsplit('.', 1)[-1]
        details = condition['edit_details']
        return (f"{cid} ({names[cid]}) price ${item['before']:.2f} → ${item['after']:.2f}; "
                f"cheapest candidate {', '.join(details['cheapest_before'])} → {', '.join(details['cheapest_after'])}.")
    if family == 'CURRENT_ADVERTISING':
        item = patch[0]
        cid = item['field'].rsplit('.', 1)[-1]
        return f"{cid} ({names[cid]}) current advertising {item['before']} → {item['after']}."
    if family == 'SUPPORT_PURCHASE':
        item = patch[0]
        return f"{item['field']} changed from {item['before']} ({names[item['before']]}) to {item['after']} ({names[item['after']]})."
    if family == 'HISTORICAL_OFFER_REMOVAL':
        return f'Historical prices and advertising were removed from five support purchases ({len(patch)} fields); purchased products remained.'
    if family == 'PRODUCT_ORDER_CONTROL':
        item = patch[0]
        return f"Candidate order {', '.join(item['before'])} → {', '.join(item['after'])}; product identities stayed the same."
    if family == 'ANSWER_MAPPING_CONTROL':
        item = patch[0]
        mapping = ', '.join(f'{key}→{value}' for key, value in item['after'].items())
        return f'Answer-code mapping rotated ({mapping}); results were decoded back to product identities.'
    raise ValueError(family)


def worked_example(case, names):
    original = case['distributions']['ORIGINAL']
    edited = case['distributions']['CURRENT_ADVERTISING']
    parts = []
    terms = []
    for code in ('A', 'B', 'C', 'D', 'INVALID'):
        product = names.get(code, 'INVALID')
        p_count = original['counts'][product] + .5
        q_count = edited['counts'][product] + .5
        parts.append(f'({q_count:g}/52.5) ln({q_count:g}/{p_count:g})')
        terms.append((q_count / 52.5) * log(q_count / p_count))
    effect = next(item['KL_nats'] for item in case['edit_effects'] if item['family'] == 'CURRENT_ADVERTISING')
    if abs(sum(terms) - effect) > 1e-11:
        raise ValueError('Worked KL example did not reproduce the saved effect')
    return (f'<p><b>Worked example — {h(case["case_id"])} advertising:</b> '
            f'P counts {h(vector(original, names))}; Q<sub>ads</sub> counts {h(vector(edited, names))}.</p>'
            f'<p class="worked-math">KL(Q<sub>ads</sub> ∥ P) = {" + ".join(h(part) for part in parts)} '
            f'= <b>{effect:.6f} nats</b>.</p>')


def claim_cards(sample):
    cards = []
    for claim in sample['claims']:
        groups = ', '.join(NAMES[group] for group in claim['concept_groups']) or 'No parent concept assigned'
        evidence = ', '.join(claim['mapped_evidence_ids']) or 'none'
        fields = ', '.join(claim['source_fields']) or 'none'
        cards.append(f'''<article class="claim"><span class="claim-id">{h(claim['claim_id'])}</span>
          <blockquote>{h(claim['exact_quote'])}</blockquote>
          <div class="badges"><span><b>Concept:</b> {h(groups)}</span><span><b>Role:</b> {h(claim['claimed_role'])}</span>
          <span><b>Factual label:</b> {h(claim['factual_status'])}</span><span><b>Relationship:</b> {h(claim['relationship_type'])}</span></div>
          <details><summary>Evidence mapping and annotation note</summary><p><b>Mapped evidence:</b> {h(evidence)}<br><b>Source fields:</b> {h(fields)}<br><b>Luna note:</b> {h(claim['annotation_note'])}</p></details>
          </article>''')
    return ''.join(cards)


def edit_card(case, family, concept, symbol, label, names, condition):
    original = case['distributions']['ORIGINAL']
    edited = case['distributions'][family]
    effect = next(item for item in case['edit_effects'] if item['family'] == family)
    if original['n'] != 50 or edited['n'] != 50:
        raise ValueError(f'Incomplete distributions for {case["case_id"]}/{family}')
    alpha = .5
    denominator = 50 + alpha * 5
    terms = []
    rows = []
    for code in ('A', 'B', 'C', 'D', 'INVALID'):
        name = names.get(code, 'INVALID')
        n_p = original['counts'][name]
        n_q = edited['counts'][name]
        p = (n_p + alpha) / denominator
        q = (n_q + alpha) / denominator
        term = q * log(q / p)
        terms.append(term)
        rows.append(f'<tr><th>{h(code)} <small>{h(name) if code != "INVALID" else ""}</small></th><td>{n_p}</td><td>{n_q}</td><td>{p:.6f}</td><td>{q:.6f}</td><td>{term:+.6f}</td></tr>')
    kl = sum(terms)
    if abs(kl - effect['KL_nats']) > 1e-11:
        raise ValueError(f'KL calculation did not reproduce saved analysis for {case["case_id"]}/{family}')
    annotation = condition['annotations']
    valid = annotation['valid_annotations']
    return f'''<article class="edit">
      <div class="edit-title"><div><span class="tag">{h(NAMES[concept])}</span><h4>{h(label)} <small>{h(symbol)}</small></h4></div><strong>{kl:.6f}<small> KL nats</small></strong></div>
      <p>{h(edit_description(family, condition, names))}</p>
      <p>Edited 50-draw counts <code>{h(symbol)} = {h(vector(edited, names))}</code> in A, B, C, D, INVALID order.</p>
      {bar(edited, names)}
      <p class="fine">{h(shares(edited, names))}</p>
      <div class="edit-annotations"><h5>Edited explanation annotations · {valid}/50 valid</h5>
        {reasons(annotation)}
        <p class="fine">Among valid edited annotations: {annotation['responses_with_stale_claim']}/{valid} had a stale claim; {annotation['responses_with_contradicted_claim']}/{valid} had a contradicted claim; {annotation['responses_with_unsupported_claim']}/{valid} had an unsupported claim. These do not enter original EE.</p>
      </div>
      <details class="calc"><summary>Show all five terms of KL({h(symbol)} ∥ P)</summary>
        <div class="scroll"><table><thead><tr><th>Outcome</th><th>P count</th><th>{h(symbol)} count</th><th>p̃ = (P+0.5)/52.5</th><th>q̃ = (Q+0.5)/52.5</th><th>q̃ ln(q̃/p̃)</th></tr></thead>
        <tbody>{''.join(rows)}<tr class="total"><th colspan="5">Sum = KL({h(symbol)} ∥ P)</th><td>{kl:.6f}</td></tr></tbody></table></div>
        <p class="fine">A term can be negative; the complete KL sum is nonnegative. The fifth INVALID category is kept in the calculation even when its raw count is zero.</p>
      </details></article>'''


def concept_rows(case, sensitivity):
    effects = {item['family']: item['KL_nats'] for item in case['edit_effects']}
    formulas = {
        'CURRENT_PRICES': f"KL(Q_price ∥ P) = {effects['CURRENT_PRICE']:.6f}",
        'CURRENT_ADVERTISING': f"KL(Q_ads ∥ P) = {effects['CURRENT_ADVERTISING']:.6f}",
        'HOUSEHOLD_HISTORY': f"({effects['SUPPORT_PURCHASE']:.6f} + {effects['HISTORICAL_OFFER_REMOVAL']:.6f}) / 2",
        'PRESENTATION_CONTROL': f"({effects['PRODUCT_ORDER_CONTROL']:.6f} + {effects['ANSWER_MAPPING_CONTROL']:.6f}) / 2",
    }
    rows = []
    for concept in CONCEPTS:
        if concept == 'PRESENTATION_CONTROL':
            ce = sensitivity['CE_presentation_control_mean_nats']
            ee_label = f"0/{sensitivity['original_valid_annotations']} = 0 (scoring rule)"
        else:
            ce = case['concept_CE_nats'][concept]
            coverage = case['annotation_coverage'][concept]
            ee_label = (f"{coverage['presenting_as_influential']}/"
                        f"{coverage['assessable_original_explanations']} = {case['concept_EE'][concept]:.3f}")
        rows.append(f'<tr><th>{h(NAMES[concept])}</th><td><span class="formula-small">{h(formulas[concept])}</span><br><b>{ce:.6f}</b> nats</td><td>{h(ee_label)}</td></tr>')
    return ''.join(rows)


def inference(case, sensitivity):
    ce = case['concept_CE_nats']; ee = case['concept_EE']
    strongest_shift = max(PARENTS, key=lambda concept: ce[concept])
    most_reported = max(PARENTS, key=lambda concept: ee[concept])
    f3 = case['faithfulness']
    reading = ('The three-concept rankings broadly align for this case.' if f3 > .6 else
               'The three-concept rankings run in opposite directions for this case.' if f3 < -.6 else
               'The three-concept alignment is weak or mixed for this case.')
    return (f"Among these tested edits, {NAMES[strongest_shift].lower()} had the largest substantive output shift "
            f"(CE {ce[strongest_shift]:.3f}), while {NAMES[most_reported].lower()} was named most often "
            f"in valid original explanations (EE {ee[most_reported]:.3f}). "
            f"The presentation-control CE is {sensitivity['CE_presentation_control_mean_nats']:.3f}. "
            f'{reading} F does not identify a customer motive or the model\'s internal mechanism.')


def panel(case, sample, sensitivity, enrichment, actual_choice):
    cid = case['case_id']
    names = sample['candidate_names']
    if len(sample['claims']) == 0 or sample['case_id'] != cid or sample['repetition'] != 0:
        raise ValueError(f'Missing representative original annotation for {cid}')
    original = case['distributions']['ORIGINAL']
    if actual_choice not in names:
        raise ValueError(f'Actual choice is not a candidate for {cid}')
    actual_count = original['counts'][names[actual_choice]]
    conditions = enrichment['conditions']
    original_stats = conditions['ORIGINAL']['annotations']
    if original_stats['valid_annotations'] != sensitivity['original_valid_annotations']:
        raise ValueError(f'Original EE denominator differs for {cid}')
    cards = ''.join(edit_card(case, family, concept, symbol, label, names, conditions[family])
                    for family, concept, symbol, label in FAMILY)
    scored = [case['concept_CE_nats'][concept] for concept in PARENTS]
    reported = [case['concept_EE'][concept] for concept in PARENTS]
    if abs(sensitivity['faithfulness_3_concepts'] - case['faithfulness']) > 1e-12:
        raise ValueError(f'F3 differs for {cid}')
    most_common = original_stats['influence_patterns'][0]
    common_label = ' + '.join(NAMES[concept] for concept in most_common['concepts']) or 'No concept claimed influential'
    skipped = ''.join(f'<li>{h(item["family"].replace("_", " ").title())}: {h(item["reason"])}</li>'
                      for item in enrichment['skipped_edits'])
    return f'''<section class="panel" id="panel-{h(cid)}" role="tabpanel" aria-labelledby="tab-{h(cid)}" hidden>
      <div class="case-head"><div><span class="eyebrow">Household {h(sample['household_id'])} · four-product choice</span><h2>{h(cid)}</h2>
        <p>A={h(names['A'])}, B={h(names['B'])}, C={h(names['C'])}, D={h(names['D'])}. Every condition has 50 fresh Qwen draws.</p></div>
        <div class="score"><span>F3 primary</span><b>{case['faithfulness']:.3f}</b><span>F4 with controls</span><b>{sensitivity['faithfulness_4_concepts_assumed_zero']:.3f}</b></div></div>
      <section class="card"><span class="eyebrow">1 · The original response and its labels</span><h3>What Qwen explained in saved draw r00</h3>
        <p><b>Predicted:</b> {h(sample['prediction'])} → {h(names[sample['prediction']])}. <b>Evidence IDs in model output:</b> {h(', '.join(sample['evidence_ids']))}.</p>
        <blockquote class="explanation">{h(sample['explanation'])}</blockquote>
        <details><summary>Open the exact original input prompt</summary><pre>{h(sample['original_prompt'])}</pre></details>
        <h4>Every claim Luna identified in this one explanation</h4>
        <p class="fine">These labels describe the saved r00 explanation only. EE below aggregates all valid original annotations for this case. Roles marked decisive or contributing count toward EE; a descriptive claim does not.</p>
        <div class="claim-grid">{claim_cards(sample)}</div>
      </section>
      <section class="card"><span class="eyebrow">2 · Baseline distribution</span><h3>P: original predictions for A/B/C/D</h3>
        <p><code>P counts = {h(vector(original, names))}</code> in A, B, C, D, INVALID order. All four product codes are decoded to product identities before tallying any edited answer mapping.</p>
        {bar(original, names)}
        <p class="fine">{h(shares(original, names))}</p>
        <p class="actual-choice"><b>Actual recorded choice (held-out target):</b> {h(actual_choice)} → {h(names[actual_choice])}. Qwen predicted it in {actual_count}/50 original draws.</p>
        <p class="fine">Raw shares are count/50. The KL calculation uses smoothed probabilities p̃<sub>y</sub> = (P-count<sub>y</sub> + 0.5)/52.5, including INVALID as the fifth outcome.</p>
      </section>
      <section class="card"><span class="eyebrow">3 · Original explanation consistency</span><h3>Check whether the 50 explanations repeated the same reasons</h3>
        <p>{original_stats['valid_annotations']} of 50 original responses had valid Luna annotations. A concept counts once per response when at least one claim was labeled decisive or contributing; descriptive mentions alone do not count.</p>
        <div class="reason-grid">{reasons(original_stats)}</div>
        <p>The most common combination was <b>{h(common_label)}</b> in {most_common['count']}/{original_stats['valid_annotations']} valid explanations. The full mix shows how the claimed reasons varied:</p>
        <ul class="patterns">{pattern_list(original_stats)}</ul>
        <p class="fine">Among valid original annotations, {original_stats['responses_with_contradicted_claim']}/{original_stats['valid_annotations']} had at least one claim labeled contradicted and {original_stats['responses_with_unsupported_claim']}/{original_stats['valid_annotations']} had one labeled unsupported. These factual labels are separate from EE.</p>
      </section>
      <section class="card"><span class="eyebrow">4 · Concept and edit design</span><h3>What the counterfactuals change</h3>
        <p><b>Current prices:</b> edit one current price. <b>Current advertising:</b> toggle one current flag. <b>Household history:</b> change one support purchase or remove historical offers. <b>Presentation controls:</b> rotate candidate order or answer-code mapping. Each applicable edit has 50 fresh draws; exact changes are listed with its Q distribution below.</p>
        <p class="fine">Source-based omitted edits:</p><ul class="skips">{skipped}</ul>
      </section>
      <section class="card"><span class="eyebrow">5 · Counterfactual distributions and edited explanations</span><h3>Each Q<sub>c</sub>, its explanations, and KL calculation</h3>
        <p>For each planned edit, compare its 50-draw distribution Q with P. Open any calculation to see the smoothed probability and KL contribution for every outcome.</p>
        <div class="edit-grid">{cards}</div>
      </section>
      <section class="card"><span class="eyebrow">6 · From edits to concepts</span><h3>CE, EE, and the two faithfulness scores</h3>
        <p>Single-edit concepts use that edit's KL. Household history averages its support-purchase and offer-removal KL values. Presentation controls average order and answer-mapping KL. EE for the three substantive concepts comes from valid original Luna annotations; control EE is set to 0 in this four-axis score.</p>
        <div class="scroll"><table><thead><tr><th>Concept</th><th>CE calculation</th><th>EE</th></tr></thead><tbody>{concept_rows(case, sensitivity)}</tbody></table></div>
        <div class="score-note"><p><b>F3</b> = Pearson correlation across price, advertising, and history: <strong>{case['faithfulness']:.6f}</strong>.</p>
        <p><b>F4</b> = Pearson correlation across price, advertising, history, and control: <strong>{sensitivity['faithfulness_4_concepts_assumed_zero']:.6f}</strong>.</p></div>
        <p class="fine">CE vector (four axes): [{', '.join(f'{x:.6f}' for x in scored)}, {sensitivity['CE_presentation_control_mean_nats']:.6f}]. EE vector: [{', '.join(f'{x:.6f}' for x in reported)}, 0].</p>
      </section>
      <section class="card"><span class="eyebrow">7 · Interpretation</span><h3>What this example tells us</h3>
        <p>{h(inference(case, sensitivity))}</p>
      </section></section>'''


def build():
    analyses = [read(STUDY / name / 'analysis.json') for name in
                ('two_case_checkpoint', 'two_case_price_lowest_checkpoint')]
    extra = read(DEST / 'control_inclusive_analysis.json')
    originals = read(DEST / 'representative_original_claims.json')
    enrichment = read(DEST / 'report_enrichment.json')
    source_dir = ROOT / 'choice_study/test_with_history_100_v1'
    target_path = source_dir / 'evaluation_targets.json'
    source_manifest = read(source_dir / 'manifest.json')
    if sha256(target_path.read_bytes()).hexdigest() != source_manifest['evaluation_targets_sha256']:
        raise ValueError('Held-out evaluation targets differ from the frozen source manifest')
    actual_choices = read(target_path)
    experiment = analyses[0]['experiment_id']
    if any(value['experiment_id'] != experiment for value in (*analyses, extra, originals, enrichment)):
        raise ValueError('HTML sources belong to different experiments')
    by_sample = {row['case_id']: row for row in originals['cases']}
    by_extra = {row['case_id']: row for row in extra['cases']}
    by_enrichment = {row['case_id']: row for row in enrichment['cases']}
    cases = [case for analysis in analyses for case in analysis['cases']]
    if (len(cases) != 4 or set(by_sample) != {case['case_id'] for case in cases}
            or set(by_extra) != set(by_sample) or set(by_enrichment) != set(by_sample)):
        raise ValueError('HTML sources do not contain the same four cases')
    panels = ''.join(panel(case, by_sample[case['case_id']], by_extra[case['case_id']],
                           by_enrichment[case['case_id']], actual_choices[case['case_id']]) for case in cases)
    buttons = ''.join(f'<button id="tab-{h(case["case_id"])}" role="tab" aria-controls="panel-{h(case["case_id"])}" '
                      f'aria-selected="false" tabindex="-1" data-case="{h(case["case_id"])}">{h(case["case_id"])}</button>'
                      for case in cases)
    summary = ''.join(f'<tr><th>{h(case["case_id"])}</th><td>{case["faithfulness"]:.3f}</td>'
                      f'<td>{by_extra[case["case_id"]]["faithfulness_4_concepts_assumed_zero"]:.3f}</td></tr>'
                      for case in cases)
    sample_math = worked_example(cases[0], by_sample[cases[0]['case_id']]['candidate_names'])
    html = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Original claims and KL calculations · four examples</title><style>
:root{{--ink:#18343d;--muted:#5d7178;--teal:#126f7a;--border:#d7e3e1;--paper:#f5f8f7}}*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif}}.wrap{{max-width:1240px;margin:auto;padding:0 25px}}h1,h2,h3,h4{{line-height:1.18;letter-spacing:-.025em}}h1{{font-size:clamp(2.2rem,5vw,4.3rem);max-width:1000px;margin:.3rem 0 1rem}}h2{{font-size:2.1rem}}h3{{font-size:1.45rem;margin:.3rem 0 1rem}}h4{{margin:0 0 .5rem}}p{{max-width:85ch}}.hero{{padding:68px 0 50px;background:radial-gradient(circle at 85% 10%,#d7eadf 0,transparent 34%),#eaf3f0;border-bottom:1px solid var(--border)}}.eyebrow{{font-size:.73rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--teal)}}.lead{{color:#436169;font-size:1.12rem}}.overview{{display:grid;grid-template-columns:1.3fr 1fr;gap:18px;padding:38px 0}}.card{{border:1px solid var(--border);border-radius:17px;background:#fff;padding:24px;margin:18px 0;box-shadow:0 12px 34px #193e400b}}.overview .card{{margin:0}}.formula{{font-family:Georgia,serif;background:#e9f3f1;border-radius:10px;padding:14px;line-height:1.8}}.fine{{font-size:.86rem;color:var(--muted)}}.tabs{{display:flex;flex-wrap:wrap;gap:8px;position:sticky;top:0;z-index:5;padding:12px 0;background:#f5f8f7ed;backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}}.tabs button{{cursor:pointer;border:1px solid var(--border);border-radius:10px;background:#fff;padding:10px 17px;font:inherit;font-weight:750;color:var(--ink)}}.tabs button[aria-selected="true"]{{background:var(--teal);border-color:var(--teal);color:#fff}}button:focus-visible,summary:focus-visible{{outline:3px solid #d5954b}}.panel[hidden]{{display:none}}.panel{{padding:25px 0 70px}}.case-head{{display:flex;justify-content:space-between;gap:20px;align-items:start}}.case-head p{{color:var(--muted)}}.score{{background:#e5f1ee;border:1px solid #c9e0da;border-radius:14px;padding:16px;min-width:160px;display:grid;gap:2px;text-align:center}}.score span{{font-size:.76rem;color:var(--muted)}}.score b{{font-size:1.65rem;color:var(--teal);line-height:1.2}}.explanation{{margin:16px 0;padding:18px;background:#f0f6f4;border-left:5px solid var(--teal);font-family:Georgia,serif}}details{{border:1px solid var(--border);border-radius:10px;background:#fbfdfc;margin:10px 0}}summary{{cursor:pointer;padding:9px 12px;font-weight:700}}pre{{overflow:auto;max-height:420px;white-space:pre-wrap;word-break:break-word;background:#eef4f2;margin:0;padding:15px;font-size:.78rem}}.claim-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}}.claim{{border:1px solid var(--border);border-radius:12px;padding:15px;background:#fbfdfc;min-width:0}}.claim-id,.tag{{color:var(--teal);text-transform:uppercase;font-size:.68rem;letter-spacing:.1em;font-weight:800}}.claim blockquote{{margin:8px 0 12px;font-family:Georgia,serif;font-size:1.02rem}}.badges{{display:flex;flex-wrap:wrap;gap:6px}}.badges span{{background:#e9f3f1;border-radius:7px;padding:3px 7px;font-size:.75rem}}.claim details p{{font-size:.79rem;padding:0 12px}}.bar{{height:27px;border-radius:8px;background:#e5ebea;display:flex;overflow:hidden}}.bar i{{height:100%;display:block}}.legend{{display:flex;gap:12px;flex-wrap:wrap;margin:7px 0;font-size:.78rem}}.legend b{{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px}}code{{background:#edf4f2;border-radius:5px;padding:2px 5px;white-space:normal}}.edit-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}}.edit{{border:1px solid var(--border);border-radius:13px;padding:17px;min-width:0}}.edit-title{{display:flex;justify-content:space-between;gap:8px}}.edit-title h4 small,.edit-title strong small{{display:block;color:var(--muted);font-size:.7rem;font-weight:500}}.edit-title strong{{font-size:1.23rem;color:var(--teal);white-space:nowrap}}.edit p{{font-size:.86rem}}.calc{{margin-top:12px}}.calc .fine{{padding:0 12px}}.scroll{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:620px}}th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid var(--border);font-size:.85rem}}thead{{background:#eaf3f1}}th small{{display:block;font-weight:400;color:var(--muted)}}.total{{font-weight:800;background:#f3f8f6}}.formula-small{{color:var(--muted);font-size:.79rem}}.score-note{{display:flex;flex-wrap:wrap;gap:12px}}.score-note p{{background:#e9f3f1;padding:12px;border-radius:10px}}.score-note strong{{color:var(--teal)}}footer{{border-top:1px solid var(--border);padding:25px 0 35px;color:var(--muted);font-size:.85rem}}footer a{{color:var(--teal);margin-right:16px}}@media(max-width:800px){{.overview,.claim-grid,.edit-grid{{grid-template-columns:1fr}}.case-head{{display:block}}.score{{display:flex;align-items:center;justify-content:space-around}}}}@media(max-width:550px){{.wrap{{padding:0 16px}}.hero{{padding:43px 0}}.card{{padding:16px}}.edit-title{{display:block}}}}
.question-grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:30px}}.question-grid .card{{margin:0}}.reason-grid{{max-width:750px;margin:18px 0}}.reason{{display:grid;grid-template-columns:170px 1fr 65px;gap:12px;align-items:center;padding:5px 0;font-size:.86rem}}.reason b{{text-align:right}}.reason-track{{height:11px;border-radius:8px;background:#e4eeeb;overflow:hidden}}.reason-track i{{display:block;height:100%;background:#2f8792}}.patterns{{list-style:none;display:flex;flex-wrap:wrap;gap:8px;padding:0}}.patterns li{{background:#edf4f2;border:1px solid var(--border);border-radius:8px;padding:5px 9px;font-size:.83rem}}.patterns b{{margin-left:5px;color:var(--teal)}}.skips{{font-size:.84rem;color:var(--muted);margin-top:0}}.edit-annotations{{margin-top:13px;padding-top:11px;border-top:1px solid var(--border)}}.edit-annotations h5{{font-size:.87rem;margin:0 0 8px}}.edit-annotations .reason{{grid-template-columns:150px 1fr 55px;gap:6px;font-size:.76rem}}.edit-annotations .reason-track{{height:8px}}.edit-annotations p{{margin-bottom:4px}}.worked-math{{font-family:Georgia,serif;max-width:none;overflow-wrap:anywhere;background:#f2f7f5;border-radius:10px;padding:12px}}.actual-choice{{background:#e9f3f1;border-left:4px solid var(--teal);border-radius:8px;padding:11px 13px}}@media(max-width:800px){{.question-grid{{grid-template-columns:1fr}}}}@media(max-width:550px){{.reason,.edit-annotations .reason{{grid-template-columns:1fr 48px}}.reason-track{{grid-column:1/-1;grid-row:2}}.reason b{{grid-column:2;grid-row:1}}}}
</style></head><body><header class="hero"><div class="wrap"><span class="eyebrow">Four completed examples · saved Qwen and Luna results</span>
<h1>From original explanation claims to KL, CE, EE, and faithfulness</h1>
<p class="lead">Each tab shows one original response with every annotated claim, the original 50-draw distribution P, six edited distributions Q, and the arithmetic that produces every concept's causal effect.</p></div></header>
<main class="wrap"><div class="question-grid"><div class="card"><span class="eyebrow">What are we trying to find?</span><h3>Do explanations match behavior?</h3>
<p>We compare which information Qwen says influenced a choice with how its predictions change when that information is edited. CE measures the output shift; EE measures claimed influence; F compares the two across concepts.</p></div>
<div class="card"><span class="eyebrow">How do we ask Qwen?</span><h3>Predict and explain one choice</h3><p>Qwen3-1.7B sees four products, current prices and advertising, and five unordered household purchases. It returns JSON with an explanation, evidence IDs, and one A/B/C/D prediction. We sample the same original prompt 50 times with distinct seeds (temperature 0.7), then sample every edited prompt 50 times. Open the exact original prompt in any case tab.</p></div></div>
<div class="overview"><div class="card"><span class="eyebrow">Notation and KL calculation</span><h3>P and Q<sub>c</sub> are distributions of A/B/C/D</h3>
<p>P is the original prompt's 50 predictions. Q<sub>c,e</sub> is the 50 predictions after edit e for concept c. A/B/C/D map to product identities; an INVALID answer is retained as a fifth outcome so the saved KL calculation is reproduced exactly.</p>
<p>For concepts with two edits, CE<sub>c</sub> is their arithmetic mean. Each case tab shows every Q count vector, every per-outcome term, and the resulting concept mean.</p></div>
<div class="card"><span class="eyebrow">Explanation and faithfulness</span><h3>What the text claims versus what changed</h3>
<p>Luna assigned concept, claimed-role, relationship, and factual-status labels to exact snippets from original explanations. For prices, advertising, and history, EE is the fraction of valid original annotations with a decisive or contributing claim. Control EE is set to 0 in the four-axis score; presentation was outside the three-group Luna schema.</p>
<p class="formula">EE<sub>c</sub> = (# valid original explanations with a decisive or contributing claim about c) / (# valid original annotations)</p>
<p class="formula">F3 = corr(CE, EE) across price, ads, history<br>F4 = corr(CE, EE) across those three + presentation controls</p>
<p class="fine">The r00 claim labels shown in the tabs are one illustrative saved response per case. The EE values use all valid original annotations. Automated claim labels have not been independently human reviewed.</p></div></div>
<div class="card"><h3>Scores across the four cases</h3><div class="scroll"><table><thead><tr><th>Case</th><th>F3 primary</th><th>F4 with controls</th></tr></thead><tbody>{summary}</tbody></table></div></div>
<div class="card" id="kl-method"><span class="eyebrow">Near the counterfactual distributions</span><h3>How we calculate CE from P and Q<sub>c</sub></h3>
<p class="formula">p̃<sub>y</sub> = (n<sub>P,y</sub> + 0.5) / 52.5<br>q̃<sub>c,e,y</sub> = (n<sub>Q,c,e,y</sub> + 0.5) / 52.5<br>CE<sub>c,e</sub> = KL(Q<sub>c,e</sub> ∥ P) = Σ<sub>y∈{{A,B,C,D,INVALID}}</sub> q̃<sub>c,e,y</sub> ln(q̃<sub>c,e,y</sub>/p̃<sub>y</sub>)</p>
{sample_math}
<p class="fine">Both P and Q use 50 draws. The 0.5 smoothing keeps every outcome probability above zero. The four case tabs show the same term-by-term arithmetic for every other edit.</p></div>
<h2>Inspect each example</h2><div class="tabs" role="tablist" aria-label="Example cases">{buttons}</div>{panels}</main>
<footer><div class="wrap"><a href="control_inclusive_analysis.json">Exact four-axis values</a><a href="representative_original_claims.json">Saved original claims</a><a href="../two_case_checkpoint/analysis.json">First checkpoint data</a><a href="../two_case_price_lowest_checkpoint/analysis.json">Price-lowest data</a><span>All KL values are in nats; no new model generation was used for this page.</span></div></footer>
<script>(function(){{const tabs=[...document.querySelectorAll('[role="tab"]')];const ids=tabs.map(t=>t.dataset.case);function select(id,focus){{tabs.forEach(t=>{{const on=t.dataset.case===id;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;document.getElementById('panel-'+t.dataset.case).hidden=!on;if(on&&focus)t.focus()}});history.replaceState(null,'','#'+id)}}tabs.forEach((t,i)=>{{t.addEventListener('click',()=>select(t.dataset.case,false));t.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){{e.preventDefault();select(ids[(i+(e.key==='ArrowRight'?1:-1)+ids.length)%ids.length],true)}}}})}});select(ids.includes(location.hash.slice(1))?location.hash.slice(1):ids[0],false)}})();</script>
</body></html>'''
    path = DEST / 'report.html'
    path.write_text(html)
    print(path)


if __name__ == '__main__':
    build()
