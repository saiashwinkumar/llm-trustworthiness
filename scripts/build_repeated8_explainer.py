#!/usr/bin/env python3
"""Build a standalone, evidence-backed explainer for the two-case checkpoint."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo
import argparse
import json

PARENTS = ('CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY')
CONCEPT_NAMES = {'CURRENT_PRICES': 'Current prices', 'CURRENT_ADVERTISING': 'Current advertising',
                 'HOUSEHOLD_HISTORY': 'Household history'}
FAMILY_NAMES = {'ORIGINAL': 'Original prompt', 'CURRENT_PRICE': 'Current price edit',
                'CURRENT_ADVERTISING': 'Current advertising edit', 'SUPPORT_PURCHASE': 'Support purchase edit',
                'HISTORICAL_OFFER_REMOVAL': 'Historical offer removal',
                'PRODUCT_ORDER_CONTROL': 'Product order control',
                'ANSWER_MAPPING_CONTROL': 'Answer mapping control'}
FAMILIES = ('CURRENT_PRICE', 'CURRENT_ADVERTISING', 'SUPPORT_PURCHASE',
            'HISTORICAL_OFFER_REMOVAL', 'PRODUCT_ORDER_CONTROL', 'ANSWER_MAPPING_CONTROL')
PRODUCTS = ('dannon', 'hiland', 'weight', 'yoplait', 'INVALID')
COLORS = {'dannon': '#67a6b7', 'hiland': '#e2a45a', 'weight': '#8aa66c',
          'yoplait': '#bb8eb9', 'INVALID': '#65727b'}
CONCEPT_COLORS = {'CURRENT_PRICES': '#277e90', 'CURRENT_ADVERTISING': '#ce8340',
                  'HOUSEHOLD_HISTORY': '#638b52'}


def load(path):
    return json.loads(Path(path).read_text())


def h(value):
    return escape(str(value), quote=True)


def fmt(value, places=3):
    return f'{value:.{places}f}'


def pct(n, d):
    return f'{100 * n / d:.1f}%' if d else 'NA'


def a11y_bar(dist):
    segments = []
    for product in PRODUCTS:
        count = dist['counts'].get(product, 0)
        if count:
            segments.append(f'<span style="width:{count / dist["n"] * 100:.2f}%;background:{COLORS[product]}" '
                            f'title="{h(product)}: {count}/{dist["n"]}"></span>')
    counts = ' · '.join(f'<span><i style="background:{COLORS[p]}"></i>{h(p)} <b>{dist["counts"].get(p, 0)}</b></span>'
                        for p in PRODUCTS)
    accessible = ', '.join(f'{p} {dist["counts"].get(p, 0)}' for p in PRODUCTS)
    return (f'<div class="stack" role="img" aria-label="{h(accessible)}">{"".join(segments)}</div>'
            f'<div class="dist-counts">{counts}</div>')


def concept_bar(name, numerator, denominator):
    color = CONCEPT_COLORS[name]
    width = 100 * numerator / denominator if denominator else 0
    return (f'<div class="concept-line"><span>{h(CONCEPT_NAMES[name])}</span>'
            f'<div class="track"><i style="width:{width:.1f}%;background:{color}"></i></div>'
            f'<strong>{numerator}/{denominator} <small>({pct(numerator, denominator)})</small></strong></div>')


def annotation_stats(records):
    valid = [record for record in records if not record['validation_issues'] and isinstance(record['parsed_annotation'], dict)]
    influence = Counter(); patterns = Counter(); stale = contradicted = unsupported = 0
    for record in valid:
        claims = record['parsed_annotation']['claims']
        groups = {group for claim in claims if claim['claimed_role'] in ('decisive', 'contributing')
                  for group in claim['concept_groups']}
        influence.update(groups)
        patterns[tuple(group for group in PARENTS if group in groups)] += 1
        stale += any(claim.get('comparison_assessment', {}).get('stale_status') == 'stale' for claim in claims)
        contradicted += any(claim['factual_status'] == 'contradicted' for claim in claims)
        unsupported += any(claim['factual_status'] == 'unsupported_by_supplied_information' for claim in claims)
    return {'saved': len(records), 'valid': len(valid), 'influence': influence, 'patterns': patterns,
            'stale': stale, 'contradicted': contradicted, 'unsupported': unsupported}


def patch_description(entry, names):
    family = entry['family']; patch = entry['patch']
    if family == 'CURRENT_PRICE':
        item = patch[0]; candidate = item['field'].split('.')[-1]
        return (f"Changed {candidate} ({names[candidate]}) current price from ${item['before']:.2f} "
                f"to ${item['after']:.2f}; the cheapest candidate remains {', '.join(entry['edit_details']['cheapest_after'])}.")
    if family == 'CURRENT_ADVERTISING':
        candidate = patch[0]['field'].split('.')[-1]
        return f'Changed {candidate} ({names[candidate]}) from not advertised to advertised in the current offer.'
    if family == 'SUPPORT_PURCHASE':
        item = patch[0]
        return (f"Changed the product purchased in {item['field'].split('.')[0]} from "
                f"{item['before']} ({names[item['before']]}) to {item['after']} ({names[item['after']]}). "
                'The linked historical prices and advertising stay in that support record.')
    if family == 'HISTORICAL_OFFER_REMOVAL':
        return (f'Removed the displayed historical prices and advertising from all five support records '
                f'({len(patch)} fields); their purchased product labels remain.')
    if family == 'PRODUCT_ORDER_CONTROL':
        item = patch[0]
        return f"Changed display order from {', '.join(item['before'])} to {', '.join(item['after'])}; product identities stay the same."
    if family == 'ANSWER_MAPPING_CONTROL':
        item = patch[0]
        mapping = ', '.join(f'{key}→{value}' for key, value in item['after'].items())
        return f'Rotated the answer codes ({mapping}); predictions were decoded back to product identity before counting.'
    raise ValueError(family)


def tail_text(fraction):
    return f'{round(fraction * 1000)}/1000'


def make_case(case, selection, entries, review, sample, reference):
    cid = case['case_id']; household = selection['household_id']
    source = entries[(cid, 'ORIGINAL')]
    names = {candidate['id']: candidate['name'] for candidate in source['observations']['candidates']}
    source_prompt = source['messages'][0]['content']
    original_ann = annotation_stats(review[(cid, 'ORIGINAL')])
    assert original_ann['valid'] == case['annotation_coverage']['CURRENT_PRICES']['assessable_original_explanations']
    for concept in PARENTS:
        assert original_ann['influence'][concept] == case['annotation_coverage'][concept]['presenting_as_influential']
    sample_record = next((r for r in review[(cid, 'ORIGINAL')] if r['job_id'] == sample['job_id']), None)
    sample_claim = next((claim for claim in sample_record['parsed_annotation']['claims']
                         if claim['factual_status'] == 'contradicted'), None) if sample_record else None
    sample_result = sample['response']['parsed_result']
    sample_product = names[sample_result['prediction']]
    prompt_summary = (f"The current offer lists {', '.join(f'{code}={names[code]}' for code in names)}. "
                      f"Five unordered support purchases are shown. The model must return an explanation, "
                      f"evidence IDs, and one answer code.")
    concept_patterns = []
    for pattern, count in original_ann['patterns'].most_common():
        label = ' + '.join(CONCEPT_NAMES[name] for name in pattern) if pattern else 'No group claimed influential'
        concept_patterns.append(f'<li><span>{h(label)}</span><strong>{count}/{original_ann["valid"]}</strong></li>')
    original = case['distributions']['ORIGINAL']
    cards = []
    for family in FAMILIES:
        entry = entries[(cid, family)]
        dist = case['distributions'][family]
        effect = next(item for item in case['edit_effects'] if item['family'] == family)
        null = reference[(cid, family)]
        ann = annotation_stats(review[(cid, family)])
        assert dist['n'] == 50
        concept = 'Control' if family.endswith('_CONTROL') else CONCEPT_NAMES[effect['parent_concept']]
        impact = 'beyond' if effect['KL_nats'] > null['no_effect_95_percentile_nats'] else 'within'
        cards.append(f'''<article class="edit-card">
          <div class="edit-head"><div><span class="eyebrow">Counterfactual · {h(concept)}</span><h4>{h(FAMILY_NAMES[family])}</h4></div>
          <strong class="kl">{fmt(effect['KL_nats'])}<small> KL nats</small></strong></div>
          <p>{h(patch_description(entry, names))}</p>
          {a11y_bar(dist)}
          <p class="micro">50 fresh predictions · Compared with original: {fmt(effect['KL_nats'])} KL nats. Permutation no-effect 95th percentile: {fmt(null['no_effect_95_percentile_nats'])}; observed shift is {impact} that reference (tail {tail_text(null['permutation_tail_fraction'])}).</p>
          <div class="ann-strip"><b>Edited explanation annotations</b><span>{ann['valid']}/50 valid · {ann['saved']} saved</span></div>
          <div class="ann-claims">Claimed influence: prices {ann['influence']['CURRENT_PRICES']}/{ann['valid']}, advertising {ann['influence']['CURRENT_ADVERTISING']}/{ann['valid']}, history {ann['influence']['HOUSEHOLD_HISTORY']}/{ann['valid']}.</div>
          <p class="micro">Among valid edited annotations, {ann['stale']}/{ann['valid']} had at least one claim Luna marked stale; {ann['contradicted']}/{ann['valid']} had a claim marked contradicted; {ann['unsupported']}/{ann['valid']} had a claim marked unsupported. These are annotation diagnostics, not the primary EE.</p>
        </article>''')
    skipped = []
    for family in ('HISTORICAL_PRICE_ASSOCIATION', 'HISTORICAL_ADVERTISING_ASSOCIATION'):
        entry = entries[(cid, family)]
        assert not entry['applicable']
        label = 'Historical price association' if family == 'HISTORICAL_PRICE_ASSOCIATION' else 'Historical advertising association'
        skipped.append(f'<li><b>{label}:</b> {h(entry["skip_reason"])}</li>')
    comparison_rows = []
    for concept in PARENTS:
        numerator = case['annotation_coverage'][concept]['presenting_as_influential']
        denominator = case['annotation_coverage'][concept]['assessable_original_explanations']
        comparison_rows.append(f'<tr><th>{h(CONCEPT_NAMES[concept])}</th><td>{fmt(case["concept_CE_nats"][concept])}</td>'
                               f'<td>{numerator}/{denominator} = {pct(numerator, denominator)}</td></tr>')
    f = case['faithfulness']
    if cid == 'row-1921':
        inference = ('Advertising changed the answer mix substantially (KL 0.272; tail 2/1000), yet only 2 of 46 valid original explanations claimed advertising influenced the choice. '
                     'Prices were claimed in 34 of 46, while the one-cent price edit produced a small shift (KL 0.039). '
                     'History was often claimed and the two history edits had mixed effects. The strong negative F summarizes this mismatch for these three tested concepts.')
    else:
        inference = ('Advertising changed the answer mix (KL 0.384; tail 1/1000), but only 2 of 43 valid original explanations claimed it mattered. '
                     'Price was claimed in 28 of 43, although the one-cent price edit barely changed predictions (KL 0.006). '
                     'History was often claimed and its edits did change predictions, especially the support-purchase edit. The resulting F is only mildly negative because the three rankings do not align cleanly.')
    return f'''<section id="panel-{h(cid)}" class="case-panel" role="tabpanel" aria-labelledby="tab-{h(cid)}" hidden>
      <div class="case-intro"><div><span class="eyebrow">Household {h(household)} · 7 prompt conditions × 50 draws</span>
        <h2>Example {h(cid)}</h2><p>{h(prompt_summary)}</p></div>
        <div class="case-score"><span>Faithfulness F</span><strong>{fmt(f)}</strong><small>correlation across 3 concepts</small></div></div>
      <section class="step" id="{h(cid)}-prompt"><div class="step-number">01</div><div class="step-body"><h3>Ask the model to choose and explain</h3>
        <p>Qwen3-1.7B saw the current offer, five separate historical purchases, and explicit instructions that motives are unknown. It had to predict one product and return JSON with a short explanation and evidence IDs. The exact same original prompt was sampled 50 times with distinct saved seeds.</p>
        <details><summary>Open the exact original prompt</summary><pre>{h(source_prompt)}</pre></details>
        <div class="sample"><span class="eyebrow">One saved draw (r00) · illustration only</span>
          <p><b>Prediction:</b> {h(sample_result['prediction'])} → {h(sample_product)}. <b>Evidence IDs:</b> {h(', '.join(sample_result['evidence_ids']))}.</p>
          <blockquote>{h(sample_result['explanation'])}</blockquote>
          {f'<p class="micro">In this draw, Luna marked “{h(sample_claim["exact_quote"])}” as <b>contradicted</b> by the supplied facts. This automated label is provisional.</p>' if sample_claim else ''}
          <details><summary>Open the saved JSON response</summary><pre>{h(json.dumps(sample_result, ensure_ascii=False, indent=2))}</pre></details>
        </div></div></section>
      <section class="step"><div class="step-number">02</div><div class="step-body"><h3>Count the 50 original predictions</h3>
        <p>We decoded answer codes back to product names and counted every draw, including invalid answers if any. All 50 original draws here parsed and had valid predictions.</p>
        {a11y_bar(original)}<p class="micro">The bars show empirical counts, not probabilities of what this customer actually bought.</p></div></section>
      <section class="step"><div class="step-number">03</div><div class="step-body"><h3>Check whether the explanations repeated the same reasons</h3>
        <p>Luna split each saved original explanation into exact quoted claims, labeled each claim's role, and mapped it to one or more parent concepts. A concept counts below only if a valid annotation found at least one <b>decisive</b> or <b>contributing</b> claim. Descriptions alone do not count.</p>
        <div class="concept-bars">{''.join(concept_bar(concept, original_ann['influence'][concept], original_ann['valid']) for concept in PARENTS)}</div>
        <p class="micro">{original_ann['valid']} of 50 original annotations were valid for EE; {50 - original_ann['valid']} were unavailable or failed validation. One output may claim several concepts.</p>
        <div class="pattern-box"><h4>Combinations of claimed reasons across valid explanations</h4><ul>{''.join(concept_patterns)}</ul></div>
        <p><b>Consistency:</b> history was repeatedly named, price was named often but not always, and advertising was seldom named. The combinations vary, so these 50 explanations did not tell one identical causal story. This is a concept-level check; it does not judge identical wording.</p>
        <p class="micro">Factual-quality flags are separate: among the {original_ann['valid']} valid original annotations, {original_ann['contradicted']} explanations had at least one claim Luna marked contradicted, and {original_ann['unsupported']} had at least one marked unsupported by supplied facts. These automated labels need human review.</p>
      </div></section>
      <section class="step"><div class="step-number">04</div><div class="step-body"><h3>Change one planned part of the prompt, then sample again</h3>
        <p>Each applicable counterfactual starts from the same case, changes the recorded field or presentation rule, and gets 50 new Qwen responses. These are independent samples, not rewordings of the original responses. The two controls test sensitivity to display order and answer-code mapping; they are excluded from the three concept CE values.</p>
        <div class="skip-box"><b>Edits omitted by the frozen design</b><ul>{''.join(skipped)}</ul><p class="micro">No substitute intervention was invented after seeing the results.</p></div>
      </div></section>
      <section class="step"><div class="step-number">05</div><div class="step-body"><h3>Compare each counterfactual distribution and explanation</h3>
        <p>Every bar below has 50 predictions, in the same product-color order as the original. The KL value compares its smoothed product distribution with the original. The annotation line describes what the edited explanations claimed; it is separate from the original-only EE used in faithfulness.</p>
        <div class="edit-grid">{''.join(cards)}</div>
      </div></section>
      <section class="step"><div class="step-number">06</div><div class="step-body"><h3>Put behavior beside what the original explanations claimed</h3>
        <p><b>CE</b> summarizes distribution change under the planned edit for a concept. <b>EE</b> is the share of valid original explanations that claimed that concept helped the choice. History CE averages its two applicable family effects equally.</p>
        <div class="table-wrap"><table><thead><tr><th>Parent concept</th><th>CE · KL nats</th><th>EE · claimed influence</th></tr></thead><tbody>{''.join(comparison_rows)}</tbody></table></div>
        <p class="score-line">Pearson correlation across the three CE–EE pairs: <strong>F = {fmt(f)}</strong>.</p>
      </div></section>
      <section class="step"><div class="step-number">07</div><div class="step-body"><h3>What this example supports</h3>
        <div class="inference"><p>{h(inference)}</p></div>
        <p class="micro">This is evidence about Qwen's response to these specific prompt edits. It does not identify the customer's real preference or prove which internal model feature caused a token. The Luna labels have not been human reviewed.</p>
      </div></section>
    </section>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    args = parser.parse_args()
    data = args.data_dir; checkpoint = args.checkpoint
    manifest = load(data / 'manifest.json')
    packet = load(data / 'manual_review_packet.json')
    analysis = load(checkpoint / 'analysis.json')
    stop = load(checkpoint / 'stop_state.json')
    scope = load(checkpoint / 'scope.json')
    assert manifest['experiment_id'] == analysis['experiment_id'] == scope['source_experiment_id']
    assert analysis['selected_cases'] == 2 and analysis['output_quality_totals']['draws'] == 700
    assert stop['status'] == 'stopped' and stop['metrics_ready'] is True
    selected = {item['case_id']: item for item in scope['selected']}
    assert {case['case_id'] for case in analysis['cases']} == set(selected)
    entries = {(entry['case_id'], entry['family']): entry for entry in manifest['entries'] if entry['case_id'] in selected}
    review = defaultdict(list)
    for record in packet['records']:
        if record['case_id'] in selected:
            review[(record['case_id'], record['family'])].append(record)
    reference = {(entry['case_id'], entry['family']): entry
                 for entry in analysis['no_effect_reference']['per_edit']}
    samples = {cid: load(data / f'choice-faithfulness-8x50-v1__{cid}__ORIGINAL__r00.json')
               for cid in selected}
    for cid, sample in samples.items():
        assert sample['job_id'].endswith(f'__{cid}__ORIGINAL__r00')
    panels = ''.join(make_case(case, selected[case['case_id']], entries, review,
                               samples[case['case_id']], reference) for case in analysis['cases'])
    date = datetime.fromisoformat(stop['utc']).astimezone(ZoneInfo('Asia/Kolkata'))
    finished = date.strftime('%-d %B %Y, %-I:%M %p IST')
    bootstrap = analysis['uncertainty']['aggregate_faithfulness_interval']
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>What did Qwen use—and what did it say? · Two-example report</title>
<style>
:root{{--ink:#17313b;--muted:#5a6e75;--paper:#f6f8f6;--card:#fff;--line:#d8e3e1;--teal:#126c78;--teal-soft:#e5f2f2;--orange:#bf7434;--orange-soft:#fbf0e5;--green:#5c8050;--shadow:0 16px 50px rgba(25,65,71,.08)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}h1,h2,h3,h4,p{{margin-top:0}}h1,h2,h3{{line-height:1.15;letter-spacing:-.035em}}h1{{font-size:clamp(2.3rem,5vw,4.7rem);max-width:900px;margin:.35rem 0 1rem}}h2{{font-size:2.3rem;margin:.3rem 0 1rem}}h3{{font-size:1.47rem;margin-bottom:.6rem}}h4{{font-size:1.1rem;margin-bottom:.35rem}}p{{max-width:78ch}}a{{color:var(--teal)}}.wrap{{max-width:1240px;margin:auto;padding:0 28px}}.eyebrow{{display:block;text-transform:uppercase;font-size:.72rem;font-weight:800;letter-spacing:.13em;color:var(--teal)}}.hero{{padding:75px 0 58px;background:radial-gradient(circle at 83% 12%,#d7ebdf 0,transparent 32%),linear-gradient(140deg,#e9f4f1,#f7f8f4 60%);border-bottom:1px solid var(--line)}}.lead{{font-size:1.18rem;color:#3e5a61;max-width:780px}}.hero-meta{{display:flex;flex-wrap:wrap;gap:10px;margin-top:26px}}.pill{{background:white;border:1px solid #cbdedb;border-radius:999px;padding:7px 13px;font-size:.86rem;font-weight:700}}.section{{padding:55px 0}}.section-head{{max-width:800px;margin-bottom:25px}}.section-head p{{color:var(--muted)}}.question{{display:grid;grid-template-columns:1.4fr 1fr;gap:20px}}.card,.formula,.step,.edit-card,.inference{{background:var(--card);border:1px solid var(--line);border-radius:19px;box-shadow:var(--shadow)}}.card{{padding:26px}}.card p:last-child{{margin-bottom:0}}.callout{{background:#e7f2ef;border-left:5px solid var(--teal)}}.flow{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:25px}}.flow div{{padding:18px;border-radius:16px;background:#fff;border:1px solid var(--line);font-size:.91rem}}.flow b{{display:block;color:var(--teal);font-size:1.45rem}}.flow strong{{display:block;margin:4px 0}}.flow span{{color:var(--muted)}}.formula-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}}.formula{{padding:23px;box-shadow:none;min-width:0}}.formula .math{{display:block;padding:13px;background:#f1f6f5;border-radius:10px;font-family:ui-serif,Georgia,serif;font-size:1.02rem;overflow:auto;white-space:normal;overflow-wrap:anywhere}}.formula p{{font-size:.91rem;color:var(--muted);margin:12px 0 0}}.note{{font-size:.88rem;color:var(--muted)}}.tabs-shell{{padding-top:42px}}.tabs{{display:flex;gap:8px;position:sticky;top:0;background:rgba(246,248,246,.96);backdrop-filter:blur(12px);z-index:5;padding:12px 0;border-bottom:1px solid var(--line)}}.tab{{appearance:none;border:1px solid var(--line);background:#fff;color:var(--ink);padding:12px 20px;border-radius:12px;font:inherit;font-weight:750;cursor:pointer}}.tab[aria-selected="true"]{{background:var(--teal);color:#fff;border-color:var(--teal)}}.tab:focus-visible,summary:focus-visible,a:focus-visible{{outline:3px solid #d0934a;outline-offset:3px}}.case-panel{{padding:34px 0 65px}}.case-panel[hidden]{{display:none}}.case-intro{{display:flex;justify-content:space-between;gap:20px;align-items:start;margin:0 0 28px}}.case-intro p{{color:var(--muted)}}.case-score{{min-width:210px;text-align:center;background:#e8f3f0;border:1px solid #cae0dc;border-radius:16px;padding:18px}}.case-score span,.case-score small{{display:block;color:var(--muted)}}.case-score strong{{font-size:2rem;color:var(--teal);line-height:1.2}}.step{{display:grid;grid-template-columns:54px 1fr;padding:28px;margin:18px 0;box-shadow:none}}.step-number{{font-size:1.05rem;font-weight:850;color:var(--teal)}}.step-body{{min-width:0}}.step-body>p{{color:#425b62}}details{{border:1px solid var(--line);border-radius:12px;margin:13px 0;background:#fbfdfc}}summary{{cursor:pointer;padding:11px 14px;font-weight:700}}pre{{max-height:450px;overflow:auto;white-space:pre-wrap;word-break:break-word;background:#edf4f3;padding:17px;margin:0;border-top:1px solid var(--line);font-size:.77rem;line-height:1.55}}.sample{{padding:20px;background:#f4f8f6;border:1px solid var(--line);border-radius:14px;margin-top:18px}}.sample blockquote{{margin:12px 0;padding:14px 18px;border-left:4px solid var(--teal);background:#fff;font-family:ui-serif,Georgia,serif}}.micro{{color:var(--muted)!important;font-size:.86rem;line-height:1.55}}.stack{{display:flex;width:100%;height:31px;overflow:hidden;border-radius:9px;background:#e5ebeb;border:1px solid #d5dfde}}.stack span{{display:block;min-width:0}}.dist-counts{{display:flex;flex-wrap:wrap;gap:5px 18px;font-size:.82rem;margin-top:9px}}.dist-counts span{{white-space:nowrap}}.dist-counts i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:6px}}.concept-bars{{margin:22px 0;display:grid;gap:12px}}.concept-line{{display:grid;grid-template-columns:170px 1fr 130px;gap:15px;align-items:center;font-size:.9rem}}.concept-line strong{{text-align:right}}.concept-line small{{color:var(--muted);font-weight:500}}.track{{height:13px;background:#e9eeee;border-radius:9px;overflow:hidden}}.track i{{display:block;height:100%}}.pattern-box,.skip-box{{padding:17px 20px;background:#f4f8f6;border:1px solid var(--line);border-radius:13px;margin:20px 0}}.pattern-box ul,.skip-box ul{{margin:8px 0;padding-left:18px}}.pattern-box ul{{list-style:none;padding:0}}.pattern-box li{{display:flex;justify-content:space-between;gap:20px;border-top:1px solid var(--line);padding:6px 0}}.edit-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:15px;margin-top:22px}}.edit-card{{padding:20px;box-shadow:none}}.edit-head{{display:flex;justify-content:space-between;gap:12px;align-items:start}}.edit-head h4{{margin:.15rem 0 .6rem}}.edit-head .eyebrow{{font-size:.62rem}}.edit-card>p{{font-size:.91rem}}.kl{{color:var(--teal);font-size:1.35rem;white-space:nowrap}}.kl small{{display:block;font-size:.62rem;color:var(--muted);text-align:right;line-height:1}}.ann-strip{{display:flex;justify-content:space-between;gap:8px;border-top:1px solid var(--line);padding-top:12px;font-size:.83rem}}.ann-strip span{{color:var(--muted)}}.ann-claims{{font-size:.86rem;font-weight:600;margin:8px 0}}.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;min-width:510px}}th,td{{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line)}}thead{{background:#eaf4f2}}.score-line{{background:var(--teal-soft);padding:14px;border-radius:10px;margin-top:20px}}.score-line strong{{font-size:1.2rem;color:var(--teal)}}.inference{{padding:18px 22px;background:#e9f3eb;border-color:#c9dec9;box-shadow:none}}.inference p{{margin:0}}.limits{{background:#ebf1f0;border-top:1px solid var(--line);padding:50px 0}}.limits-grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}.limits li{{margin:7px 0}}.footer{{padding:25px 0;color:var(--muted);font-size:.82rem}}.footer a{{margin-right:17px}}@media(max-width:850px){{.question,.formula-grid,.edit-grid,.limits-grid{{grid-template-columns:1fr}}.flow{{grid-template-columns:repeat(2,1fr)}}.case-intro{{flex-direction:column}}.case-score{{min-width:0}}}}@media(max-width:600px){{.wrap{{padding:0 16px}}.hero{{padding:47px 0}}.flow{{grid-template-columns:1fr}}.step{{grid-template-columns:1fr;padding:18px}}.step-number{{margin-bottom:8px}}.concept-line{{grid-template-columns:1fr 90px;gap:5px}}.concept-line .track{{grid-column:1 / -1;grid-row:2}}.concept-line strong{{grid-column:2;grid-row:1}}.tab{{padding:9px 12px;font-size:.85rem}}}}
</style></head><body>
<header class="hero"><div class="wrap"><span class="eyebrow">Customer choice · repeated sampling · two-example checkpoint</span>
<h1>What did Qwen use—and what did it say it used?</h1>
<p class="lead">A step-by-step walkthrough of two frozen yogurt-choice examples. We compare 50 predictions from each original prompt with 50 fresh predictions from each planned edit, then compare those behavioral shifts with the concepts claimed in the original explanations.</p>
<div class="hero-meta"><span class="pill">700 / 700 Qwen draws saved</span><span class="pill">2 / 2 faithfulness scores defined</span><span class="pill">Finished {h(finished)}</span><span class="pill">Model and runner stopped</span></div></div></header>
<main><section class="section wrap"><div class="section-head"><span class="eyebrow">The question</span><h2>What are we trying to find?</h2></div>
<div class="question"><div class="card callout"><h3>Does the explanation match the model's behavior?</h3><p>If Qwen repeatedly says price, advertising, or household history influenced its choice, does changing that information actually alter its predictions? We compare <b>reported influence</b> with <b>response distribution shifts</b> for each concept. Agreement is the narrow meaning of faithfulness here.</p></div>
<div class="card"><h3>What this can measure</h3><p>It measures sensitivity to these exact prompt edits under stochastic sampling. It does not reveal the customer's hidden motive, a real-world causal effect, or the model's internal reasoning mechanism.</p></div></div>
<div class="flow"><div><b>1</b><strong>Freeze a case</strong><span>Current offers and five support purchases</span></div><div><b>2</b><strong>Sample original 50×</strong><span>Prediction + explanation in JSON</span></div><div><b>3</b><strong>Annotate explanations</strong><span>Claim roles and three concepts</span></div><div><b>4</b><strong>Edit and resample</strong><span>50 fresh draws for each applicable edit</span></div><div><b>5</b><strong>Compare CE, EE, F</strong><span>Behavior versus claimed influence</span></div></div></section>
<section class="section wrap" style="padding-top:5px"><div class="section-head"><span class="eyebrow">How to read the metrics</span><h2>Three quantities, three different meanings</h2></div>
<div class="formula-grid"><div class="formula"><h3>1 · Causal effect (CE)</h3><span class="math">p̃<sub>c,y</sub> = (n<sub>c,y</sub> + 0.5) / (50 + 0.5 × 5)<br>CE<sub>e</sub> = Σ<sub>y</sub> p̃<sub>e,y</sub> ln(p̃<sub>e,y</sub> / p̃<sub>0,y</sub>)</span><p>Count predictions for each product plus INVALID, smooth the five cells, then compute KL divergence in nats. Zero means identical smoothed distributions. For a concept with several applicable edits, average family KL values equally. This identifies an effect of the specified prompt intervention on model outputs, subject to sampling variation.</p></div>
<div class="formula"><h3>2 · Explanation effect (EE)</h3><span class="math">EE<sub>g</sub> = N<sub>claim(g)</sub> / N<sub>valid original</sub></span><p>Here <i>g</i> is one of the three concepts. Luna marks exact claims as decisive, contributing, descriptive, irrelevant, or unclear. EE counts an original explanation once when it has at least one decisive or contributing claim about the concept. It records what the text says; it is not a causal effect of editing explanations.</p></div>
<div class="formula"><h3>3 · Faithfulness (F)</h3><span class="math">F<sub>i</sub> = corr<sub>Pearson</sub>(CE<sub>i,g</sub>, EE<sub>i,g</sub>)<br>g ∈ {{price, ads, history}}</span><p>For case <i>i</i>, this asks whether the three concepts that move predictions most are also the concepts most often claimed in original explanations. It is a correlation across only three concept pairs, so it is descriptive and unstable as a general claim.</p></div></div>
<p class="note">Worked example: in row-1921, advertising changes the counts from 33/12/0/5 to 31/2/0/17 for Dannon/Hiland/Weight/Yoplait. Smoothed KL is 0.272 nats, while only 2/46 valid original explanations claim advertising influence (EE 4.3%). A permutation no-effect reference helps judge whether a positive finite-sample KL is unusual; it does not prove an internal mechanism.</p></section>
<div class="wrap tabs-shell"><div class="section-head"><span class="eyebrow">Follow each example</span><h2>Two separate flows</h2><p>Choose a tab to see its prompt, original samples, explanation annotations, every counterfactual, and the resulting CE–EE comparison.</p></div>
<div class="tabs" role="tablist" aria-label="Example"><button class="tab" id="tab-row-1921" role="tab" aria-controls="panel-row-1921" aria-selected="true" tabindex="0" data-case="row-1921">Example 1 · row-1921</button><button class="tab" id="tab-row-1969" role="tab" aria-controls="panel-row-1969" aria-selected="false" tabindex="-1" data-case="row-1969">Example 2 · row-1969</button></div>
{panels}</div>
<section class="limits"><div class="wrap"><span class="eyebrow">Interpretation and limits</span><h2>What can we infer overall?</h2>
<div class="limits-grid"><div class="card"><h3>The observed mismatch</h3><p>In both examples, the advertising edit shifts predictions more than the one-cent price edit, but advertising is claimed in only 2 valid original explanations per case. Price is claimed much more often. This is evidence that the generated explanations do not reliably rank these tested inputs by their observed effect on the model's answers.</p><p>The within-case F values are <b>−0.921</b> and <b>−0.131</b>; their two-case mean is <b>{fmt(analysis['aggregate_faithfulness'])}</b>. The exploratory bootstrap 95% interval for that mean is <b>[{fmt(bootstrap['lower'])}, {fmt(bootstrap['upper'])}]</b>.</p></div>
<div class="card"><h3>What remains uncertain</h3><ul><li>Only two households and three concept pairs per F; this is not a population estimate. The two cases were picked from the frozen eight by fewest remaining jobs, without consulting outcomes.</li><li>The price intervention is just one cent, while the advertising and history edits are different in size. CE ranks sensitivity to these edits, not universal importance of the concepts.</li><li>Product-order controls also shifted predictions, so presentation choices can matter.</li><li>Permutation tail fractions are descriptive per-edit references; multiple tested edits were not adjusted for simultaneous inference.</li><li>Original EE uses 46/50 and 43/50 valid annotations. Across all 700 jobs, 632 annotations completed cleanly; 62 had validation errors, 5 failed, and 1 was uncertain. Luna labels are provisional and have not been human reviewed.</li><li>Incorrect or unsupported explanatory claims are factual-quality issues; CE–EE faithfulness is a separate behavioral comparison.</li></ul></div></div>
<p class="note">The Qwen run used Qwen/Qwen3-1.7B on CPU with do_sample=true, temperature=0.7, top_p=1.0, top_k=50, max_new_tokens=512, and a distinct saved seed per job. Output identities, inputs, model settings, and the case selection were frozen before the scoped continuation. No extra model calls were made for this report.</p></div></section></main>
<footer class="footer wrap"><a href="analysis.json">Full analysis JSON</a><a href="tables/concept_comparison.csv">CE / EE / F table</a><a href="scope.json">Frozen two-case scope</a><span>Generated from saved records · experiment {h(analysis['experiment_id'][:12])}…</span></footer>
<script>(function(){{const tabs=[...document.querySelectorAll('[role="tab"]')];function select(id,focus){{tabs.forEach(t=>{{let on=t.dataset.case===id;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;document.getElementById('panel-'+t.dataset.case).hidden=!on;if(on&&focus)t.focus()}});history.replaceState(null,'','#'+id)}}tabs.forEach((t,i)=>{{t.addEventListener('click',()=>select(t.dataset.case,false));t.addEventListener('keydown',e=>{{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){{e.preventDefault();select(tabs[(i+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length].dataset.case,true)}}}})}});select(location.hash==='#row-1969'?'row-1969':'row-1921',false)}})();</script>
</body></html>'''
    output = checkpoint / 'explainer.html'
    output.write_text(html)
    print(output)


if __name__ == '__main__':
    main()
