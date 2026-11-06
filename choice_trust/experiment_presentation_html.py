"""Accessible two-tab, offline HTML for the actual saved joint experiment."""
import base64
from collections import Counter
from copy import deepcopy
from difflib import SequenceMatcher
import html
import json
import re
from .experiment_presentation import LABELS, PURPOSES, FAMILIES, CONDITIONS, SPLITS
from .observations import canonical_price

SPLIT_NAMES = {'development': 'Development', 'validation': 'Validation', 'test': 'Test'}
CONDITION_NAMES = {'no_history': 'Without support', 'with_history': 'With history'}
ROLES = {'decisive': 'Decisive reason', 'contributing': 'Contributing reason', 'descriptive_only': 'Description',
         'explicitly_irrelevant': 'Explicitly irrelevant', 'unclear': 'Unclear'}
GROUPS = {'CURRENT_PRICES': 'Current prices', 'CURRENT_ADVERTISING': 'Current advertising', 'HOUSEHOLD_HISTORY': 'Household history'}
FACTS = {'supported': 'Supported', 'contradicted': 'Contradicted', 'unsupported_by_supplied_information': 'Unsupported by supplied information',
         'not_applicable': 'Not a factual assertion', 'unclear': 'Unclear'}


def esc(value):
    return html.escape(str(value), quote=True)


def dollar(value):
    result = canonical_price(value)
    return '$' + result if result is not None else 'NOT_PROVIDED'


def product(entry, cid, *, canonical=False):
    candidates = entry['original_source']['candidates'] if canonical else entry['observations']['candidates']
    return next((c['name'].capitalize() for c in candidates if c['id'] == cid), 'Not available')


def fraction(label, numerator, denominator):
    return f'<math display="block" aria-label="{esc(label)} equals {esc(numerator)} divided by {esc(denominator)}"><mrow><mtext>{esc(label)}</mtext><mo>=</mo><mfrac><mtext>{esc(numerator)}</mtext><mtext>{esc(denominator)}</mtext></mfrac></mrow></math>'


def rate_text(rate):
    if not rate or not rate['denominator']:
        return 'Not available'
    return f"{rate['percentage']:.1f}% ({rate['numerator']}/{rate['denominator']})"


def coverage(rate, label):
    if not rate or not rate['denominator']:
        return f'<span class="coverage">{esc(label)}: no eligible source records.</span>'
    return f'<span class="coverage">{esc(label)}: {rate["percentage"]:.1f}% · {rate["numerator"]}/{rate["denominator"]}</span>'


def result(rate, *, cov=None, cov_label='Annotation coverage', extra=''):
    if rate is None:
        return '<span class="value na">Not measured</span>'
    if rate['denominator']:
        body = f'<span class="value">{rate["percentage"]:.1f}%</span><span class="count">{rate["numerator"]}/{rate["denominator"]}</span>'
    else:
        body = '<span class="value na">Not available</span><span class="count">0/0 eligible</span>'
    return body + (coverage(cov, cov_label) if cov is not None else '') + extra


def matrix(data, getter, cov_key=None, cov_label='Annotation coverage', *, accuracy=False, include_test_without_support=False):
    columns = []
    splits = SPLITS if accuracy else ('test',)
    for split in splits:
        conditions = CONDITIONS if accuracy and (split != 'test' or include_test_without_support) else ('with_history',)
        cells = []
        for condition in conditions:
            cohort = data[split][condition]
            value = getter(cohort) if cohort else None
            cov = value.get(cov_key) if value and cov_key else None
            extra = ''
            if value and 'classification_coverage' in value:
                extra += coverage(value['classification_coverage'], 'Classified / valid pairs')
            if value and 'eligible_coverage' in value:
                extra += coverage(value['eligible_coverage'], 'Eligible / annotated claims')
            if value and 'claim_status_counts' in value:
                counts = value['claim_status_counts']
                extra += '<span class="coverage">Excluded claims: ' + str(counts.get('unsupported_by_supplied_information', 0)) + ' unsupported; ' + str(counts.get('unclear', 0)) + ' unclear; ' + str(counts.get('not_applicable', 0)) + ' not applicable.</span>'
            cells.append('<div class="condition"><span class="condition-label">' + CONDITION_NAMES[condition] + '</span>'
                         + result(value, cov=cov, cov_label=cov_label, extra=extra) + '</div>')
        columns.append('<div class="split"><h4>' + SPLIT_NAMES[split] + '</h4><div class="conditions' + (' single' if len(conditions) == 1 else '') + '">' + ''.join(cells) + '</div></div>')
    return '<div class="matrix' + ('' if accuracy else ' test-only') + '">' + ''.join(columns) + '</div>'


def metric(title, question, label, numerator, denominator, symbols, body, interpretation, direction, note=''):
    return '<article class="metric"><h3>' + esc(title) + '</h3><p class="question">' + esc(question) + '</p><div class="formula">' \
        + fraction(label, numerator, denominator) + '</div><p class="symbols">' + esc(symbols) + '</p>' + body \
        + '<p class="interpretation">' + esc(interpretation) + '<span class="direction">' + esc(direction) + '</span></p>' \
        + ('<p class="method-note muted">' + esc(note) + '</p>' if note else '') + '</article>'


def explanation_denominators(cohort):
    columns = [
        ('family', 'Family'), ('valid_prediction_pairs', 'Valid prediction pairs'),
        ('yes_changed', 'Yes / changed'), ('yes_unchanged', 'Yes / unchanged'),
        ('no_changed', 'No / changed'), ('no_unchanged', 'No / unchanged'),
        ('p_change_given_claimed_influence', 'P(change | claimed influence)'),
        ('p_change_given_no_influence_asserted', 'P(change | no influence asserted)'),
        ('unclear_excluded', 'Unclear excluded'), ('unassessable_excluded', 'Unassessable excluded'),
        ('invalid_prediction_pairs_excluded', 'Invalid prediction pairs excluded')]
    rows = []
    for row in cohort['conditional_change_by_family'] + [cohort['conditional_change_overall_pair_weighted']]:
        cells = []
        for key, _ in columns:
            value = row[key]
            if key == 'family':
                cells.append('<th scope="row">' + esc(LABELS.get(value, 'Overall · pair-weighted')) + '</th>')
            else:
                value = rate_text(value) if key.startswith('p_change_') else value
                cells.append('<td>' + esc(value) + '</td>')
        rows.append('<tr' + (' class="overall"' if row['family'] == 'OVERALL_PAIR_WEIGHTED' else '') + '>' + ''.join(cells) + '</tr>')
    coverage_columns = [
        ('linked_originals', 'Linked originals'), ('original_responses', 'Original responses'),
        ('linked_edited', 'Linked edited'), ('edited_responses', 'Edited responses'),
        ('linked_total', 'Linked total'), ('distinct_responses', 'Distinct responses'),
        ('excluded_annotation_sources', 'Excluded annotation sources'), ('missing_annotations', 'Missing annotations')]
    counts = cohort['annotation_coverage']
    return ('<details id="explanation-denominators" class="report-details"><summary>Conditional-change counts and annotation coverage</summary><h3 id="conditional-counts-title">Conditional-change denominators · Test with history</h3>'
        '<p class="method-note">Yes means the explanation claimed influence; No means no relevant influence was asserted. '
        'The claimed-influence denominator is Yes / changed + Yes / unchanged. The no-influence-asserted denominator is No / changed + No / unchanged. '
        'Unclear and unassessable labels are excluded from both rates; invalid prediction pairs are excluded before classification. '
        'Not-applicable edits are omitted. The six substantive families are shown here; presentation controls use the separate invariance metrics. '
        'Overall counts pool pairs, and several edits share an original query.</p>'
        '<p class="small muted">Scroll horizontally to see all columns.</p>'
        '<div class="table-scroll denominator-scroll" role="region" aria-labelledby="conditional-counts-title" tabindex="0">'
        '<table class="denominator-table"><thead><tr>' + ''.join('<th scope="col">' + esc(label) + '</th>' for _, label in columns)
        + '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
        '<h3 id="annotation-coverage-title">Annotation coverage · distinct responses</h3>'
        '<p class="method-note">Linked means an eligible, traceable annotation of a complete source explanation. '
        'Each response is counted once, including the original responses and all applicable edited responses across all eight families. '
        'Excluded annotations remain saved; missing annotations are separate. These are response counts, not pair counts.</p>'
        '<div class="table-scroll denominator-scroll" role="region" aria-labelledby="annotation-coverage-title" tabindex="0">'
        '<table class="annotation-coverage-table"><thead><tr>' + ''.join('<th scope="col">' + esc(label) + '</th>' for _, label in coverage_columns)
        + '</tr></thead><tbody><tr>' + ''.join('<td>' + esc(counts[key]) + '</td>' for key, _ in coverage_columns)
        + '</tr></tbody></table></div></details>')


def claim_level_summary(cohort):
    checks = [
        ('facts_original', 'Factual contradictions · original explanations',
         'A factual statement conflicts with the facts supplied in the original input.'),
        ('facts_edited', 'Factual contradictions · edited explanations',
         'A factual statement conflicts with the facts supplied in the edited input.'),
        ('stale_claims', 'Outdated facts after an edit',
         'A statement treats information changed or removed by the edit as still current.')]
    rows = []
    for key, label, meaning in checks:
        value = cohort[key]
        number = (f'<strong>{value["numerator"]:,} of {value["denominator"]:,}</strong> '
                  f'<span class="claim-summary-rate">{value["percentage"]:.1f}%</span>') if value['denominator'] else 'Not available'
        rows.append('<tr><th scope="row">' + esc(label) + '</th><td data-exact-source="claim-summary-' + key + '">'
            + number + '</td><td>' + esc(meaning) + '</td></tr>')
    return ('<section id="claim-level-summary"><h3 id="claim-level-title">Claim-level results · Test with history</h3>'
        '<p>Each claim is an individual statement in an explanation. The middle column shows '
        '<strong>claims with an issue out of claims assessed</strong>. Lower rates mean fewer flagged issues among the claims checked.</p>'
        '<div class="table-scroll" role="region" aria-labelledby="claim-level-title" tabindex="0">'
        '<table class="claim-summary-table"><thead><tr><th scope="col">Check</th>'
        '<th scope="col">Claims with an issue / assessed</th><th scope="col">What counts as an issue?</th></tr></thead><tbody>'
        + ''.join(rows) + '</tbody></table></div>'
        '<p class="method-note">Each check has its own eligible claims, so its denominator differs. '
        'Claims excluded from a check are not assumed correct. These are automated annotation results, not human-reviewed judgments.</p></section>')


def annotation_label_tables(inventory):
    excluded_count = inventory['layers']['excluded'][-1]['responses']
    titles = {'factual_status': 'Factual assessment', 'claimed_role': 'Claimed role',
        'concept_groups': 'Concept groups', 'relationship_type': 'Relationship types',
        'direction': 'Direction toward products', 'temporal_scope': 'Temporal scope', 'stale_status': 'Staleness labels'}

    def label_name(dimension, label):
        if dimension == 'factual_status': return FACTS.get(label, label)
        if dimension == 'claimed_role': return ROLES.get(label, label)
        if dimension == 'concept_groups': return GROUPS.get(label, 'No concept assigned' if label == 'no_concept_group' else label)
        if dimension == 'direction' and ':' in label:
            kind, cid = label.split(':', 1)
            return ('Favors ' if kind == 'favors' else 'Disfavors ') + inventory['candidate_names'].get(cid, cid)
        return {'not_annotated': 'No comparison label', 'not_applicable': 'Not applicable',
                'no_stated_direction': 'No stated direction'}.get(label, label.replace('_', ' ').capitalize())

    def table(layer, dimension):
        labels = inventory['domains'][dimension]
        if dimension == 'factual_status':
            first = ['supported', 'contradicted', 'unsupported_by_supplied_information', 'unclear', 'not_applicable']
            labels = first + [label for label in labels if label not in first]
        header = '<th scope="col">Family</th><th scope="col">Responses</th><th scope="col">Claims</th>'
        header += ''.join('<th scope="col" title="' + esc(label) + '">' + esc(label_name(dimension, label)) + '</th>' for label in labels)
        rows = []
        for row in inventory['layers'][layer]:
            family = row['family']
            name = LABELS.get(family, {'ORIGINAL': 'Original · baseline', 'ALL_EDITED': 'All edited', 'ALL_DISTINCT': 'All distinct responses'}.get(family, family))
            cells = '<th scope="row">' + esc(name) + '</th>'
            values = [('responses', row['responses']), ('claims', row['claims'])]
            values += [(label, row['counts'][dimension].get(label, 0)) for label in labels]
            for label, count in values:
                marker = ':'.join((layer, dimension, family, label))
                cells += '<td data-label-count="' + esc(marker) + '">' + str(count) + '</td>'
            rows.append('<tr' + (' class="overall"' if family in ('ALL_EDITED', 'ALL_DISTINCT') else '') + '>' + cells + '</tr>')
        caption = titles[dimension] + ' · ' + ('eligible annotations' if layer == 'eligible' else 'excluded annotations · audit only')
        return ('<div class="table-scroll label-count-scroll" role="region" aria-label="' + esc(caption) + '" tabindex="0">'
            '<table class="annotation-count-table" data-label-table="' + layer + ':' + dimension + '">'
            '<caption class="sr-only">' + esc(caption) + '</caption><thead><tr>' + header + '</tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table></div>')

    def other_labels(layer):
        return ''.join('<details class="label-category"><summary>' + esc(titles[dimension]) + '</summary>'
            + table(layer, dimension) + '</details>' for dimension in titles if dimension != 'factual_status')

    return ('<section id="annotation-label-counts"><h3>Annotation label counts by intervention family · Test with history</h3>'
        '<p>Every saved claim in an eligible annotation is counted, including unsupported and unclear claims. '
        'These are counts of annotation labels, with no factual-status exclusions. Original explanations form a separate baseline; '
        'each response is counted once. A family identifies the edit that generated the explanation; all claims in that explanation are counted, '
        'including claims about unchanged information.</p><details class="label-category"><summary>Factual assessment labels</summary>' + table('eligible', 'factual_status')
        + '<p class="method-note"><strong>Supported:</strong> backed by supplied facts. <strong>Contradicted:</strong> conflicts with supplied facts. '
        '<strong>Unsupported:</strong> supplied facts do not establish the claim. <strong>Unclear:</strong> the factual judgment is unresolved. '
        '<strong>Not a factual assertion:</strong> the claim does not assert a checkable fact.</p></details>'
        '<p class="method-note">Other label categories are below. A claim can have multiple concept groups or product directions, '
        'so those columns can sum above the claim count. Product directions are decoded with each response’s answer mapping. '
        'Original annotations have no edited-scenario comparison labels.</p>' + other_labels('eligible')
        + '<details class="excluded-labels"><summary>Labels in the ' + str(excluded_count) + ' excluded annotation records · audit only</summary>'
        '<p class="method-note">These raw labels are preserved separately because the record failed validation or its source explanation was truncated. '
        'They do not enter the eligible tables or the metric calculations.</p>' + table('excluded', 'factual_status')
        + other_labels('excluded') + '</details></section>')


def family_tables(data, kind='change', *, coverage_kind=None, substantive=False):
    blocks = []
    families = FAMILIES[:6] if substantive else FAMILIES
    for split in ('test',):
        rows = []
        for family in families:
            cells = []
            for condition in ('with_history',):
                c = data[split][condition]
                f = c['families'][family] if c else None
                cov = f.get(coverage_kind) if f and coverage_kind else None
                value = f[kind] if f else None
                if f and not f['applicable']:
                    content = '<span class="value na">Not applicable</span><span class="coverage">No supplied history.</span>'
                else:
                    content = result(value, cov=cov, cov_label='Linked original annotations')
                    if f and kind in ('p_claimed', 'p_not_claimed'):
                        content += coverage(f['classification_coverage'], 'Classified / valid pairs')
                    if f and not substantive:
                        content += f'<span class="coverage">Valid pairs: {f["valid_pairs"]}/{f["applicable"]} applicable</span>'
                cells.append('<td>' + content + '</td>')
            rows.append('<tr><th scope="row">' + esc(LABELS[family]) + '</th>' + ''.join(cells) + '</tr>')
        blocks.append('<section><h4>Test · With history</h4><table><thead><tr><th>Changed information</th><th>Result</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></section>')
    return '<div class="family-tables test-only">' + ''.join(blocks) + '</div>'


def evaluation(data):
    m = data['metrics']
    pieces = ['<p class="lead">We predict which product a household purchased using current offers and, when available, examples of that household’s purchases. We then change specific pieces of information to test whether the model’s behavior agrees with the reasons stated in its explanation.</p>',
        '<div class="split-roles"><div><h3>Development</h3><p>Design and diagnose the method. The joint pilot used two queries, each with and without support.</p></div><div><h3>Validation</h3><p>Check and select settings before final evaluation. No joint validation run is saved, so its original accuracy is not measured.</p></div><div><h3>Test</h3><p>Evaluate the frozen method. The joint run used 100 selected queries with history and their 642 applicable edits.</p></div></div>',
        '<p class="method-note">The predictor is a fixed, pretrained <strong>Qwen3-1.7B</strong> checkpoint. Its weights were not trained or fine-tuned in this experiment. The current method returns an explanation and prediction jointly, using greedy generation. Input fields are partitioned into current prices, current advertising and household history; this organization does not establish statistical independence.</p>',
        '<div class="subtle-box"><strong>Reading the results</strong><p>Every rate shows its numerator and denominator. “Not measured” means no matching run; “Not available” means no assessable denominator. Neither means zero. Annotation results describe saved automated labels, not human-confirmed truth.</p><div class="formula">' + fraction('Coverage', 'N usable', 'N available') + '</div><p class="symbols">How much of the relevant data was assessable? N usable counts linked, eligible cases, pairs or explanations; N available counts that same unit in the source cohort. The unit is stated beside each coverage value.</p></div>',
        '<h2>Prediction performance</h2><p>The joint workflow is the experiment used throughout the complete example.</p>']
    pieces.append(metric('Original prediction accuracy · joint workflow', 'How often did the original prediction match the household’s observed purchase?',
        'Accuracy', 'N correct', 'N evaluated',
        'N correct: original predictions matching the observed product. N evaluated: original cases with a decodable product prediction and known observed purchase. Answer identifiers are decoded to canonical products before comparison.',
        matrix(m, lambda c: c['accuracy'], 'coverage', 'Prediction coverage'),
        'For example, the test result compares 100 original predictions with 100 observed purchases; edited scenarios have no observed customer outcome.', 'Higher desirable'))
    old = {s: {c: {'accuracy': data['legacy_accuracy'][s][c]} for c in CONDITIONS} for s in SPLITS}
    pieces.append(metric('Original prediction accuracy · existing score-then-explain workflow',
        'How accurate were the existing Development, Validation and Test predictions?',
        'Accuracy', 'N correct', 'N evaluated',
        'N correct counts predictions matching the observed product. N evaluated counts original cases with a valid product prediction and known observed purchase. Saved predictions in this workflow are already decoded product identities.',
        matrix(old, lambda c: c['accuracy'], 'coverage', 'Prediction coverage', accuracy=True, include_test_without_support=True),
        'These results describe the existing workflow and its larger cohorts; they are kept separate from the joint-workflow results above.', 'Higher desirable',
        'The existing workflow scores candidate answers first and generates explanations separately. The new joint workflow produces its explanation and prediction in one response. Their results are not pooled.'))
    pieces += ['<h2>Response to controlled changes</h2><p>All results below are for the joint workflow’s Test set with history. Each edited input received a fresh saved joint response. Only pairs with two valid product predictions enter the rates; predefined skips and malformed responses do not count as unchanged.</p>']
    tests = '<ul class="families-list">' + ''.join('<li><strong>' + esc(LABELS[f]) + ':</strong> ' + esc(PURPOSES[f]) + '</li>' for f in FAMILIES) + '</ul>'
    pieces.append(metric('Prediction change rate · each intervention family', 'How often did the predicted product change after a controlled edit?',
        'Change rate f', 'N changed,f', 'N valid,f',
        'f identifies the intervention family named in each row. N changed,f counts valid pairs choosing a different canonical product; N valid,f counts original–edited pairs with decodable predictions for that family.',
        tests + family_tables(m), 'A change measures sensitivity. Whether it is appropriate depends on the edit and any sufficiently specific deciding rule.', 'Neither direction alone establishes quality'))
    pieces.append(metric('Product-order invariance', 'Does the prediction survive a change in product display order?',
        'Order invariance', 'N unchanged,order', 'N valid,order',
        'N unchanged,order: valid order-control pairs choosing the same product. N valid,order: all decodable order-control pairs. Offers and product identities stay fixed.',
        matrix(m, lambda c: c['families']['PRODUCT_ORDER_CONTROL']['invariance']),
        'A higher rate means greater stability under this presentation-only control.', 'Higher desirable'))
    pieces.append(metric('Answer-mapping invariance', 'Does the same product remain selected when answer letters are relabelled?',
        'Mapping invariance', 'N unchanged,mapping', 'N valid,mapping',
        'N unchanged,mapping counts unchanged canonical products after decoding each response with its own answer mapping. N valid,mapping counts all decodable mapping-control pairs. Different letters can denote the same product.',
        matrix(m, lambda c: c['families']['ANSWER_MAPPING_CONTROL']['invariance']),
        'This checks product identity rather than equality of the raw answer letters.', 'Higher desirable'))
    pieces += ['<h2>Explanation evaluation</h2>',
        '<p class="method-note">These Test-with-history assessments use GPT-6 Luna annotations through the OpenAI API. Invalid quotations, evidence mappings or incomplete outputs are excluded from the aggregates. The annotations are automated, not human-reviewed.</p>',
        '<p class="method-note">A valid annotation format does not establish semantic correctness or complete claim coverage. All rates below describe only their stated annotated subset; incomplete coverage is not a full-experiment estimate.</p>']
    pieces.append(annotation_label_tables(data['annotation_label_inventory']))
    pieces.append(explanation_denominators(m['test']['with_history']))
    for key, title, label, numerator, denominator, question, interpretation in [
        ('p_claimed', 'P(change | claimed influence)', 'P(change | claimed)', 'N changed and claimed', 'N eligible claimed',
         'When the explanation said the edited information mattered, how often did the product prediction change?',
         'A stated consideration need not imply a flip under every edit—for example, a small price edit can preserve the cheapest product.'),
        ('p_not_claimed', 'P(change | no claimed influence)', 'P(change | not claimed)', 'N changed and not claimed', 'N eligible not claimed',
         'When the explanation did not claim the edited information mattered, how often did the product prediction change?',
         '“Not claimed” means no relevant influence assertion in the available complete annotation; it does not prove the information had no influence.')]:
        kind = 'p_claimed' if key == 'p_claimed' else 'p_not_claimed'
        pieces.append(metric(title, question, label, numerator, denominator,
            'N changed and claimed / not claimed counts changed substantive pairs in the stated claim group. N eligible claimed / not claimed counts valid pairs with a linked original annotation and that assessable claim classification. A decisive or contributing role counts as a claim of influence even if its factual premise is false. Matches use the changed source fields or the affected support-frequency relationship; a household-history group label alone is insufficient.',
            matrix(m, lambda c, k=key: c[k], 'annotation_coverage', 'Linked original annotations / valid pairs')
            + '<div class="metric-breakdown"><h4>By intervention family</h4>' + family_tables(m, kind, coverage_kind='annotation_coverage', substantive=True) + '</div>',
            interpretation, 'Neither direction alone establishes quality',
            'Overall values are pair-weighted across the six substantive families. Several edits share an original query, so these pairs are not independent observations. Unclear and missing claim classifications are excluded.'))
    pieces.append(claim_level_summary(m['test']['with_history']))
    claim_details = []
    for key, title, which in [('facts_original', 'Factual contradiction · original explanations', 'original'), ('facts_edited', 'Factual contradiction · edited explanations', 'edited')]:
        claim_details.append(metric(title, f'Among assessable factual claims in {which} explanations, how many contradict the supplied information?',
            'Contradiction rate', 'N contradicted', 'N supported + N contradicted',
            'N contradicted and N supported are the annotation guide’s factual-status labels for distinct claims. Unsupported assertions—including motives, unknown actual purchases and actual paid prices—are excluded, as are unclear claims and pure influence claims labelled not applicable. Each explanation is counted once rather than repeated across pairs.',
            matrix(m, lambda c, k=key: c[k], 'response_coverage', 'Annotated / available explanations'),
            'A low value describes these automatic labels and this assessable subset; it does not establish that unsupported claims are correct or that all claims were captured.', 'Lower desirable'))
    claim_details.append(metric('Stale-fact rate · claim-level view', 'How often did an assessable claim incorrectly carry an old fact into the edited scenario?',
        'Claim stale rate', 'N stale claims', 'N eligible assessable current claims',
        'N stale claims counts saved comparison labels marked stale. N eligible assessable current claims includes only complete-source edited claims with temporal_scope=current_edited and stale_status=stale or not_stale. Explicit references to the original scenario, general/influence claims, unclear scope, unassessable and not-applicable staleness are excluded.',
        matrix(m, lambda c: c['stale_claims'], 'annotation_coverage', 'Annotated / available edited explanations'),
        'A stale claim treats information changed, removed or remapped by the edit as still currently applicable; a correct statement about the original scenario is not stale.', 'Lower desirable',
        'The frozen protocol does not specify a claim-level denominator. This requested descriptive view explicitly uses the eligibility definition above and is separate from the frozen response-level metric below; their denominators are not pooled.'))
    pieces.append('<details class="claim-metric-details"><summary>Detailed claim definitions, exclusions and coverage</summary>'
                  + ''.join(claim_details) + '</details>')
    pieces.append(metric('Stale-fact rate · frozen response-level definition', 'How many assessable edited explanations contain at least one stale claim?',
        'Response stale rate', 'N edited explanations with a stale claim', 'N assessable edited explanations',
        'The numerator counts distinct edited explanations with an explicit stale label. The denominator includes those positives and explanations with complete assessable stale-claim coverage establishing no stale claims. Missing annotations or incomplete negative assessments are excluded.',
        matrix(m, lambda c: c['stale_responses'], 'assessment_coverage', 'Assessable / available edited explanations'),
        'This retains the project’s established response-level definition. A contradiction unrelated to the intervention is not automatically stale.', 'Lower desirable'))
    return ''.join(pieces)


def source_tables(entry):
    source = entry['original_source']
    current = []
    for c in source['candidates']:
        cid = c['id']; flag = source['current']['advertised'].get(cid)
        current.append(f'<tr><th scope="row">{esc(c["name"].capitalize())} <small class="muted">({esc(cid)})</small></th><td>{esc(dollar(source["current"]["prices"].get(cid)))}</td><td>{"Not provided" if flag is None else "Advertised" if flag else "Not advertised"}</td></tr>')
    supports = []
    for record in source.get('support') or []:
        cells = []
        for c in source['candidates']:
            flag = record['advertised'].get(c['id'])
            cells.append('<td><span class="source-price">' + esc(dollar(record['prices'].get(c['id']))) + '</span><span class="source-ad">' + ('Not provided' if flag is None else 'Advertised' if flag else 'Not advertised') + '</span></td>')
        supports.append('<tr><th scope="row">' + esc(record['id']) + '</th><td>' + esc(product(entry, record['purchased'], canonical=True)) + '</td>' + ''.join(cells) + '</tr>')
    headings = ''.join('<th>' + esc(c['name'].capitalize()) + ' offer</th>' for c in source['candidates'])
    return '<h3>Current offers</h3><table><thead><tr><th>Product</th><th>Price</th><th>Advertising</th></tr></thead><tbody>' + ''.join(current) + '</tbody></table><h3>Supplied household purchases</h3><p class="note">These are unordered, separate purchases. Their identifiers do not establish recency.</p><div class="table-scroll"><table><thead><tr><th>Observation</th><th>Purchased</th>' + headings + '</tr></thead><tbody>' + ''.join(supports) + '</tbody></table></div>'


def exact_text(text, source, css='verbatim'):
    return '<div class="' + css + '" data-exact-source="' + esc(source) + '">' + esc(text) + '</div>'


def diff_text(before, after):
    tokens = lambda text: re.findall(r'\$?\d+(?:\.\d+)?|[A-Za-z_]\w*|\s+|[^\w\s]', text)
    a, b = tokens(before), tokens(after)
    left, right = [], []
    for kind, a0, a1, b0, b1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        x, y = ''.join(a[a0:a1]), ''.join(b[b0:b1])
        left.append(esc(x) if kind == 'equal' else '<mark class="removed" data-change="removed">' + esc(x) + '</mark>' if x else '')
        right.append(esc(y) if kind == 'equal' else '<mark class="added" data-change="added">' + esc(y) + '</mark>' if y else '')
    return ''.join(left), ''.join(right)


def full_prompt(entry, source):
    messages = entry['messages']
    if len(messages) != 1:
        return exact_text('\n\n'.join(m['role'] + ':\n' + m['content'] for m in messages), source, 'prompt')
    text = messages[0]['content']
    index = text.index('\nCANDIDATES\n')
    return '<p class="task-label">Exact saved task instruction and supplied facts</p><pre class="prompt" tabindex="0" data-exact-source="' + esc(source) + '"><span class="prompt-instruction">' + esc(text[:index]) + '</span><span class="prompt-facts">' + esc(text[index:]) + '</span></pre>'


def field_description(field, value, entry):
    parts = field.split('.')
    if field.startswith('presentation.'):
        if parts[-1] == 'order':
            return ' → '.join(product(entry, c, canonical=True) for c in value)
        return '; '.join(product(entry, c, canonical=True) + ' = ' + str(a) for c, a in value.items())
    if len(parts) == 2 and parts[1] == 'purchased':
        return parts[0] + ' purchased ' + product(entry, value)
    cid = parts[-1]
    who = product(entry, cid)
    context = 'Current' if parts[0] == 'current' else parts[0] + ' historical'
    if '.prices.' in field:
        return context + ' ' + who + ' offer: ' + dollar(value)
    if '.advertised.' in field:
        return context + ' ' + who + ': ' + ('NOT_PROVIDED' if value is None else 'advertised' if value else 'not advertised')
    return str(value)


def rule_html(annotation, source_id):
    rules = annotation.get('rules', [])
    if not rules:
        return '<p class="rule-note">No rule object was recorded by this annotator; this does not establish that no rule was missed.</p>'
    result = []
    for rule in rules:
        quote = '<blockquote data-rule-source="' + esc(source_id + ':' + rule['rule_id']) + '">' + esc(rule['exact_quote']) + '</blockquote>'
        result.append('<details class="rule"><summary>Saved decision-rule annotation ' + esc(rule['rule_id']) + '</summary>' + quote + '<p>Explicit: ' + ('yes' if rule['explicit'] else 'no') + '; sufficiently specified: ' + ('yes' if rule['sufficiently_specified'] else 'no') + '; eligible for later rule testing: ' + ('yes' if rule['eligible_for_counterfactual_testing'] else 'no') + '.</p><p>' + esc(rule['eligibility_reason']) + '</p></details>')
    return ''.join(result)


def annotation_html(annotation, entry, source_id, *, compact=False):
    if annotation is None:
        return '<details class="annotation-details"><summary>Saved annotation availability</summary><p class="note">No saved annotation is linked to this exact response in this report’s snapshot.</p></details>'
    claim_count = len(annotation['claims']); rule_count = len(annotation.get('rules', []))
    label = (str(claim_count) + (' claim' if claim_count == 1 else ' claims') + ' · '
             + str(rule_count) + (' decision-rule annotation' if rule_count == 1 else ' decision-rule annotations'))
    output = ['<details class="annotation-details"><summary>Saved annotation · ' + esc(label) + '</summary><p class="small muted">' + esc(annotation['method']) + ' · automated, not human-reviewed.</p>']
    if not annotation['valid']:
        diagnostics = annotation['diagnostics']
        issues = diagnostics.get('issues')
        if issues is None:  # The pilot predates Luna's flattened diagnostics.
            issues = list(diagnostics.get('schema_issues', []))
            if diagnostics.get('parse_error'): issues.append(diagnostics['parse_error'])
            issues += [str(check.get('claim_id', check.get('index'))) + ': ' + issue
                       for check in diagnostics.get('claim_checks', []) for issue in check['issues']]
        output.append('<div class="subtle-box"><strong>Traceability issue — excluded from aggregate metrics.</strong><p>' + esc('; '.join(issues)) + '</p></div>')
    values = annotation.get('job', {}).get('source_values') or entry['observations']['audit']['source_values']
    for claim in annotation['claims']:
        cid = source_id + ':' + claim['claim_id']
        names = ', '.join(GROUPS.get(g, g) for g in claim['concept_groups']) or 'No input concept assigned'
        relation = claim['relationship_type'].replace('_', ' ')
        evidence = '; '.join(field_description(f, values[f], entry) for f in claim['source_fields'] if f in values)
        direction = []
        for key, word in (('favors', 'Favors'), ('disfavors', 'Opposes')):
            if claim['direction'][key]:
                direction.append(word + ' ' + ', '.join(product(entry, c) for c in claim['direction'][key]))
        body = '<details class="claim"><summary>Claim ' + esc(claim['claim_id']) + ' · ' + esc(ROLES[claim['claimed_role']]) + ' · ' + esc(FACTS[claim['factual_status']]) + '</summary><blockquote data-claim-source="' + esc(cid) + '">' + esc(claim['exact_quote']) + '</blockquote>'
        body += '<p><span class="label">Concept / relationship</span><br>' + esc(names + ' · ' + relation) + '</p><p><span class="label">Claimed role</span><br>' + esc(ROLES[claim['claimed_role']] + (' · ' + '; '.join(direction) if direction else '')) + '</p>'
        body += '<p><span class="label">Mapped supporting or contradicting evidence</span><br>' + esc(evidence or 'No observation field was mapped; see the annotator’s justification below.') + '</p>'
        body += '<p><span class="label">Factual assessment by the annotator</span><br><strong>' + esc(FACTS[claim['factual_status']]) + '</strong> — ' + esc(claim['annotation_note']) + '</p>'
        comparison = claim.get('comparison_assessment')
        if comparison:
            body += '<p><span class="label">Edited-scenario comparison</span><br>' + esc(comparison['temporal_scope'].replace('_', ' ') + ' · ' + comparison['stale_status'].replace('_', ' ')) + '. ' + esc(comparison['reason']) + '</p>'
        output.append(body + '</details>')
    output.append(rule_html(annotation, source_id))
    output.append('</details>')
    return ''.join(output)


def development_pilot_annotation(pilot):
    entry = pilot['entry']; annotation = pilot['annotation']; review = pilot['review']
    explanation = pilot['response']['response']['parsed_result']['explanation']
    missing = next(c for c in review['proposed_claims'] if c['exact_quote'] == 'the choice is based on the lowest price.')
    phrases = [('the cheapest product is D (Yoplait at $5.30)', 'pilot-error', 'False minimum: Hiland is cheaper.'),
               (missing['exact_quote'], 'pilot-omission', 'Explicit claimed influence omitted by the raw annotator.')]
    marks = sorted((explanation.index(quote), quote, css, title) for quote, css, title in phrases)
    pieces = []; cursor = 0
    for index, quote, css, title in marks:
        pieces += [esc(explanation[cursor:index]), '<mark class="' + css + '" title="' + esc(title) + '">' + esc(quote) + '</mark>']
        cursor = index + len(quote)
    pieces.append(esc(explanation[cursor:]))
    prices = entry['original_source']['current']['prices']
    price_rows = ''.join('<tr><th scope="row">' + esc(c['id'] + ' · ' + c['name'].capitalize())
        + '</th><td>' + esc(dollar(prices.get(c['id']))) + '</td><td>' + esc('P_' + c['id']) + '</td></tr>'
        for c in entry['original_source']['candidates'])
    questions = ''.join('<li>' + esc(q) + '</li>' for q in review['unresolved_questions_for_user'])
    return ('<section class="annotation-column pilot-example"><h3>Development-pilot LLM-assisted claim annotation</h3>'
        '<p class="small muted"><strong>row-1289 · Development · Without history.</strong> Qwen3-1.7B was both predictor and annotator.</p>'
        '<details id="development-pilot-example" class="annotation-details"><summary>Inspect the pilot example and three reliability failures</summary>'
        '<p class="review-label"><strong>Agent-assisted diagnostic review.</strong> Proposed corrections are pending user review; no human review is claimed.</p>'
        '<h4>Facts available to the predictor and annotator</h4><table class="pilot-prices"><thead><tr><th>Product</th><th>Current offer</th><th>Evidence ID</th></tr></thead><tbody>'
        + price_rows + '</tbody></table><p class="small">All current advertising flags are NOT_ADVERTISED. Household history is NOT_PROVIDED.</p>'
        '<h4>Exact generated explanation</h4><div class="quote-box"><div class="verbatim" data-exact-source="pilot-explanation">'
        + ''.join(pieces) + '</div></div><p class="small"><mark class="pilot-error">False price assertion</mark> · '
        '<mark class="pilot-omission">Missed influence statement</mark>. Saved prediction: D (Yoplait).</p>'
        '<h4>Why the annotation was unreliable</h4><table class="pilot-failures"><thead><tr><th>Failure</th><th>Evidence and interpretation</th></tr></thead><tbody>'
        '<tr><th scope="row">Factual label wrong</th><td>The raw C1 label is <mark class="pilot-error">supported</mark>. '
        'P_B gives Hiland ' + esc(dollar(prices['B'])) + ', below Yoplait at ' + esc(dollar(prices['D'])) + ' (P_D). '
        'The existing review proposes <strong>contradicted</strong> for the minimum/order assertion.</td></tr>'
        '<tr><th scope="row">Quotation not exact</th><td>The returned C1 quote rewrites the opening. It is not an exact substring of the explanation, '
        'so the saved quotation check fails even though the JSON parses and its evidence IDs exist.</td></tr>'
        '<tr><th scope="row">Important influence claim omitted</th><td>The raw annotation returns only C1 with role <strong>unclear</strong>. '
        'It does not separately capture <q data-exact-source="pilot-missed-influence">' + esc(missing['exact_quote']) + '</q> '
        'The existing review proposes <mark class="pilot-omission">decisive</mark> for this stated influence and <strong>not_applicable</strong> '
        'for factual truth. A false price premise does not erase the explanation’s claimed price influence.</td></tr></tbody></table>'
        '<p class="method-note">This diagnostic separates quotation traceability, factual-label correctness and material claim coverage. '
        'Valid JSON was insufficient for reliable annotation. It does not establish an annotation accuracy rate.</p>'
        '<h4>Untouched saved Qwen annotation</h4>' + annotation_html(annotation, entry, pilot['call_id'])
        + '<details class="annotation-details"><summary>Exact saved factual input, prompt and citations</summary>'
        + exact_text(entry['observations']['text'], 'pilot-observations', 'prompt') + full_prompt(entry, 'pilot-prompt')
        + '<p class="small">Original global citations: ' + esc(', '.join(pilot['response']['response']['parsed_result']['evidence_ids'])) + '.</p></details>'
        '<details class="annotation-details"><summary>Review questions still pending</summary><ul>' + questions + '</ul></details>'
        '</details></section>')


def findings_for_edit(pair, annotation):
    if not pair['applicable']:
        return '<p>' + esc(pair['skip_reason']) + '</p>'
    role = pair['influence']['classification']
    influence_text = {'yes': 'Yes — a matching decisive or contributing claim was recorded.',
        'no': 'No matching influence claim was recorded; this is not proof of non-use.',
        'unclear': 'Unclear — the saved claim does not identify a sufficiently specific role.',
        'unassessable': pair['influence'].get('reason', 'Not available.')}[role]
    if annotation and annotation['valid']:
        statuses = Counter(c['factual_status'] for c in annotation['claims'])
        factual = f"{statuses['contradicted']} contradicted / {statuses['supported'] + statuses['contradicted']} assessable factual claims; {statuses['unsupported_by_supplied_information']} unsupported claims kept separate."
        comparisons = [c.get('comparison_assessment') for c in annotation['claims']]
        positives = sum(isinstance(c, dict) and c['stale_status'] == 'stale' for c in comparisons)
        eligible = sum(isinstance(c, dict) and c['temporal_scope'] == 'current_edited' and c['stale_status'] in ('stale', 'not_stale') for c in comparisons)
        stale = f'{positives} saved stale labels; {eligible} eligible assessable current-claim labels.' if any(comparisons) else 'No saved edited staleness labels.'
    else:
        factual = stale = 'Not available — no matching traceable edited annotation.'
    return '<ul class="findings"><li><strong>Original explanation claimed the changed information mattered:</strong> ' + esc(influence_text) + '</li><li><strong>Contradiction:</strong> ' + esc(factual) + '</li><li><strong>Stale information:</strong> ' + esc(stale) + '</li></ul>'


def patch_table(entry, original):
    rows = []
    if entry['family'] == 'HISTORICAL_OFFER_REMOVAL':
        grouped = {}
        for patch in entry['patch']:
            grouped.setdefault(patch['field'].split('.')[0], []).append(patch)
        for hid, patches in grouped.items():
            before = '; '.join(field_description(p['field'], p['before'], original).removeprefix(hid + ' historical ') for p in patches)
            after = '; '.join(field_description(p['field'], p['after'], original).removeprefix(hid + ' historical ') for p in patches)
            rows.append('<tr><th scope="row">' + esc(hid + ' associated offers') + '</th><td>' + esc(before) + '</td><td><mark class="added">' + esc(after) + '</mark> <small class="muted">removed from input</small></td></tr>')
        return '<div class="table-scroll"><table class="edit-table"><thead><tr><th>Changed fields</th><th>Original values</th><th>Edited values</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
    for patch in entry['patch']:
        field = patch['field']
        before = field_description(field, patch['before'], original)
        after = field_description(field, patch['after'], original)
        label = field.replace('current.', 'Current ').replace('.prices.', ' price · ').replace('.advertised.', ' advertising · ').replace('.purchased', ' purchased product').replace('presentation.', 'Presentation ')
        rows.append('<tr><th scope="row">' + esc(label) + '</th><td>' + esc(before) + '</td><td><mark class="added">' + esc(after) + '</mark> <small class="muted">changed</small></td></tr>')
    return '<div class="table-scroll"><table class="edit-table"><thead><tr><th>Changed field</th><th>Original value</th><th>Edited value</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'


def example(data):
    ex = data['example']; original = ex['entries']['ORIGINAL']; response = ex['records']['ORIGINAL']['response']
    annotation = ex['annotations']['ORIGINAL']; case_id = data['config']['example_case_id']
    explanation = response['parsed_result']['explanation']; prediction = response['parsed_result']['prediction']
    canonical = ex['records']['ORIGINAL']['decoded_product_id']
    target = ex['target']
    title = lambda n, text: '<h2 class="step-title"><span class="step-number">' + str(n) + '.</span>' + esc(text) + '</h2>'
    output = ['<p class="lead">One household query, from its supplied records through all eight controlled-change families.</p>',
        '<p class="note">Example <strong>' + esc(case_id) + '</strong>, household ' + esc(original['household_id']) + '. Selected by saved-record completeness, breadth of applicable interventions, then numeric query ID—not prediction correctness or explanation quality. The selection is frozen for rebuilds.</p>',
        title(1, 'Purchase records'), source_tables(original),
        '<aside class="evaluation-box"><strong>Observed target purchase: ' + esc(product(original, target, canonical=True)) + '</strong><span>Hidden from the prediction prompt. This is used only to evaluate the original prediction.</span></aside>',
        title(2, 'Programmed factual observations'),
        '<p>Deterministic code generated the exact observations below from the supplied records. This is the saved string, not a reconstruction. Prices were assumed to be dollars and rounded to two decimals using decimal ROUND_HALF_UP, without scaling; missing values are NOT_PROVIDED.</p>',
        exact_text(original['observations']['text'], 'original-observations', 'prompt'),
        '<p class="method-note"><strong>Reading evidence codes:</strong> P_A means the current price of Dannon; F_A means Dannon’s current advertising flag. H1 means one complete supplied household purchase and its linked offers. A citation to H1 does not show that every field in H1 influenced the answer. The source groups partition fields and do not imply statistical independence.</p>',
        title(3, 'Joint model explanation and prediction'),
        '<p><strong>Predictor: ' + esc(ex['model']['model_id']) + '.</strong> One saved response contains both its explanation and final prediction.</p>',
        full_prompt(original, 'original-prompt'),
        '<div class="quote-box"><h4>Exact saved explanation</h4>' + exact_text(explanation, 'original-explanation') + '</div>',
        '<p><strong>Prediction:</strong> ' + esc(product(original, canonical, canonical=True)) + ' (answer ' + esc(prediction) + '). <strong>Observed purchase:</strong> ' + esc(product(original, target, canonical=True)) + '. <strong>Match:</strong> ' + ('yes' if canonical == target else 'no') + '.</p>',
        '<p class="small muted">Original global citations: ' + esc(', '.join(response['parsed_result']['evidence_ids'])) + '. This list does not establish which fields support each claim.</p>',
        title(4, 'Explanation claim annotation'),
        '<p>The development-pilot example shows a diagnosed failure of the earlier Qwen3-1.7B annotator. '
        'The Luna annotation concerns the main Test example, row-44. These are different cases and conditions, shown to illustrate the annotation workflows; '
        'they are not a matched comparison of annotator accuracy. Pilot labels do not enter the Test metrics.</p>',
        '<div class="two-col">' + development_pilot_annotation(data['development_annotation_example'])
        + '<section class="annotation-column"><h3>Test example · Luna-assisted annotation</h3>' + annotation_html(annotation, original, original['call_id']) + '</section></div>',
        title(5, 'Counterfactual edits and fresh model responses'),
        '<p>These edits test model behavior. Actual customer purchases under the edited scenarios are unknown. A prediction flip alone does not prove faithfulness, and an unchanged answer alone does not prove zero influence.</p>',
        '<p class="diff-label"><mark class="removed">− Removed or replaced text</mark> on the original side; <mark class="added">+ Added or replaced text</mark> on the edited side. Underlines and labels supplement color. Input panels open at changed lines; scroll to read the full prompt. A factual update can be appropriate; a changed explanation is not itself an error.</p>']
    changed_names, unchanged_names = [], []
    for family in FAMILIES:
        entry = ex['entries'][family]; record = ex['records'][family]; pair = ex['pairs'][family]
        output.append('<section class="family-section" id="family-' + family.lower() + '"><h3>' + esc(LABELS[family]) + '</h3><p>' + esc(PURPOSES[family]) + '</p>')
        if entry['skip_reason']:
            output.append('<p><strong>Not applicable:</strong> ' + esc(entry['skip_reason']) + '</p></section>')
            continue
        output.append(patch_table(entry, original))
        if family == 'ANSWER_MAPPING_CONTROL':
            output.append('<p class="method-note">The mapping table states product → answer identifier. Each response is decoded with its own mapping; a different letter can still name the same product. The prediction comparison below uses product names.</p>')
        if family == 'HISTORICAL_OFFER_REMOVAL':
            output.append('<p class="method-note">Only historical prices and advertising were removed. All five support purchase identities and purchased products remain supplied; the household history was not removed.</p>')
        if not record:
            output.append('<p>Edited response not available.</p></section>'); continue
        prompt_a, prompt_b = diff_text(original['messages'][0]['content'], entry['messages'][0]['content'])
        output.append('<h4>Complete saved inputs</h4><div class="two-col"><div><p class="diff-label">Original input · − replaced content</p><pre class="prompt" tabindex="0" data-exact-source="' + family + '-original-prompt">' + prompt_a + '</pre></div><div><p class="diff-label">Edited input · + changed content</p><pre class="prompt" tabindex="0" data-exact-source="' + family + '-edited-prompt">' + prompt_b + '</pre></div></div>')
        parsed = record['response']['parsed_result']
        if not isinstance(parsed, dict):
            output.append('<p>Saved edited response is incomplete or malformed; no replacement prediction or explanation was invented.</p></section>'); continue
        a, b = diff_text(explanation, parsed['explanation'])
        output.append('<h4>Exact explanations</h4><div class="two-col"><div class="quote-box"><h4>Original · − replaced text</h4><div class="verbatim" data-exact-source="' + family + '-original-explanation">' + a + '</div></div><div class="quote-box"><h4>Edited · + changed text</h4><div class="verbatim" data-exact-source="' + family + '-edited-explanation">' + b + '</div></div></div>')
        if pair['valid_prediction_comparison']:
            changed = pair['prediction_changed']
            (changed_names if changed else unchanged_names).append(LABELS[family])
            text = product(original, pair['original_product_id'], canonical=True) + ' → ' + product(original, pair['edited_product_id'], canonical=True)
            output.append('<div class="finding-strip"><span><strong>Predicted product:</strong> ' + esc(text) + '</span><span class="' + ('changed' if changed else 'unchanged') + '">' + ('Changed' if changed else 'Unchanged') + '</span><span>Edited answer: ' + esc(parsed['prediction']) + '</span></div>')
        else:
            output.append('<p>Prediction comparison not assessable.</p>')
        ann = ex['annotations'][family]
        output.append(findings_for_edit(pair, ann))
        output.append('<h4>Saved edited-explanation annotations</h4>' + annotation_html(ann, entry, entry['call_id'], compact=True))
        output.append('</section>')
    output.append(title(6, 'What this example demonstrates'))
    takeaways = ['The predicted product changed under: ' + (', '.join(changed_names) if changed_names else 'none of the measured edits') + '.',
        'The predicted product stayed the same under: ' + (', '.join(unchanged_names) if unchanged_names else 'none of the measured edits') + '.']
    reason_pairs = [p for p in ex['pairs'].values() if p['family'] in FAMILIES[:6] and p['valid_prediction_comparison'] and p['influence']['classification'] == 'yes']
    if reason_pairs:
        changed_reasons = sum(p['prediction_changed'] for p in reason_pairs)
        takeaways.append(f'Among the {len(reason_pairs)} edits linked to a stated reason by the saved annotation, {changed_reasons} changed the product and {len(reason_pairs) - changed_reasons} did not. A stated consideration alone does not require a prediction flip.')
    if annotation:
        counts = Counter(c['factual_status'] for c in annotation['claims'])
        takeaways.append(f'Luna labelled {counts["contradicted"]} original factual claims contradicted and {counts["unsupported_by_supplied_information"]} unsupported. Its original rule annotation is shown above; these are automated judgments rather than human-confirmed truth.')
    missing = sum(ex['annotations'][f] is None for f in FAMILIES)
    if missing:
        takeaways.append(f'{missing} of the eight edited explanations have no matching saved annotation here. Their contradiction and stale-fact results are unavailable; changed wording has not been assigned an error label.')
    takeaways.append('The records establish sensitivity to these particular edits, not the model’s internal causal process, customer motives, or what this household would buy under an edited offer.')
    output.append('<div class="takeaway"><p class="eyebrow">Record-supported takeaways</p><ul>' + ''.join('<li>' + esc(t) + '</li>' for t in takeaways) + '</ul></div>')
    return ''.join(output)


TAB_SCRIPT = r'''
(()=>{const tabs=[...document.querySelectorAll('[role=tab]')];
function showChangedLines(){if(document.getElementById('example').hidden)return;for(const panel of document.querySelectorAll('.family-section .prompt')){const mark=panel.querySelector('[data-change]');if(mark)panel.scrollTop=Math.max(0,mark.getBoundingClientRect().top-panel.getBoundingClientRect().top+panel.scrollTop-48);}}
function activate(tab,focus=false){for(const t of tabs){const on=t===tab;t.setAttribute('aria-selected',String(on));t.tabIndex=on?0:-1;document.getElementById(t.getAttribute('aria-controls')).hidden=!on;}if(focus)tab.focus();history.replaceState(null,'','#'+tab.getAttribute('aria-controls'));if(tab.getAttribute('aria-controls')==='example')requestAnimationFrame(showChangedLines);}
for(const t of tabs){t.addEventListener('click',()=>activate(t));t.addEventListener('keydown',e=>{let i=tabs.indexOf(t);if(e.key==='ArrowRight')i=(i+1)%tabs.length;else if(e.key==='ArrowLeft')i=(i+tabs.length-1)%tabs.length;else if(e.key==='Home')i=0;else if(e.key==='End')i=tabs.length-1;else return;e.preventDefault();activate(tabs[i],true);});}
const initial=tabs.find(t=>'#'+t.getAttribute('aria-controls')===location.hash);if(initial)activate(initial);
})();
'''


def render(data, css, source_packet, report_summary):
    # The HTML's downloadable views omit removed rule evaluations. The saved
    # calculation files and exact decision-rule annotations remain untouched.
    report_summary = deepcopy(report_summary)
    source_packet = deepcopy(source_packet)
    for conditions in report_summary['metrics'].values():
        for cohort in conditions.values():
            if cohort:
                cohort.pop('rule', None)
                for pair in cohort['pairs']: pair.pop('rule', None)
    for pair in source_packet['example']['pairs'].values(): pair.pop('rule', None)
    def download(obj, name, label):
        encoded = base64.b64encode(json.dumps(obj, ensure_ascii=False, indent=2).encode()).decode()
        return '<a data-download download="' + esc(name) + '" href="data:application/json;base64,' + encoded + '">' + esc(label) + '</a>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Saved-record evaluation of household product-choice predictions, explanations and controlled changes."><title>Household choice · experiment and evaluation</title><style>' + css + '</style></head><body><header><p class="eyebrow">Household product choice</p><h1>Predictions, reasons<br>and controlled changes</h1><nav class="tabs" role="tablist" aria-label="Presentation sections"><button type="button" role="tab" id="tab-evaluation" aria-controls="evaluation" aria-selected="true" tabindex="0">Evaluation</button><button type="button" role="tab" id="tab-example" aria-controls="example" aria-selected="false" tabindex="-1">One complete example</button></nav></header><main><section id="evaluation" role="tabpanel" aria-labelledby="tab-evaluation" tabindex="0">' + evaluation(data) + '</section><section id="example" role="tabpanel" aria-labelledby="tab-example" tabindex="0" hidden>' + example(data) + '</section></main><footer><p>Evidence comes from saved experimental records. Annotations are automated and not human-reviewed. No model calls were made to generate this presentation.</p>' + download(source_packet, 'complete-example-source-records.json', 'Exact example prompts, responses and annotations') + download(report_summary, 'evaluation-source-summary.json', 'Metric definitions, denominators and provenance') + '</footer><noscript><style>section[role=tabpanel][hidden]{display:block!important}</style><p>JavaScript is disabled; both presentation sections are shown.</p></noscript><script>' + TAB_SCRIPT + '</script></body></html>'
