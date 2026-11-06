"""Independent source-to-HTML integrity checks, without inference or network."""
from html.parser import HTMLParser
import json
import re


class Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.values = {}
        self.tabs = []
        self.panels = []
        self.external = []
        self.selects = 0
        self.math = 0
        self.highlights = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ('meta', 'link', 'br', 'hr', 'img', 'input'):
            keys = [attrs[k] for k in ('data-exact-source', 'data-claim-source', 'data-rule-source', 'data-label-count') if k in attrs]
            self.stack.append((tag, keys))
            for key in keys:
                if key in self.values:
                    raise AssertionError('Duplicate source-text marker: ' + key)
                self.values[key] = ''
        if attrs.get('role') == 'tab': self.tabs.append(attrs)
        if attrs.get('role') == 'tabpanel': self.panels.append(attrs)
        if tag == 'select': self.selects += 1
        if tag == 'math': self.math += 1
        if tag == 'mark' and attrs.get('data-change'): self.highlights += 1
        for name in ('src', 'href'):
            if attrs.get(name, '').startswith(('http:', 'https:', '//')):
                self.external.append(attrs[name])

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, text):
        for _, keys in self.stack:
            for key in keys:
                self.values[key] += text


def verify(page, data):
    parser = Extract(); parser.feed(page)
    assert len(parser.tabs) == len(parser.panels) == 2
    assert {t['aria-controls'] for t in parser.tabs} == {'evaluation', 'example'}
    assert not parser.external and parser.selects == 0
    assert parser.math >= 10 and parser.highlights > 0
    ex = data['example']; original = ex['entries']['ORIGINAL']; response = ex['records']['ORIGINAL']['response']
    expected = {'original-observations': original['observations']['text'],
                'original-prompt': original['messages'][0]['content'],
                'original-explanation': response['parsed_result']['explanation']}
    pilot = data['development_annotation_example']
    expected.update({'pilot-explanation': pilot['response']['response']['parsed_result']['explanation'],
                     'pilot-observations': pilot['entry']['observations']['text'],
                     'pilot-prompt': pilot['entry']['messages'][0]['content'],
                     'pilot-missed-influence': 'the choice is based on the lowest price.'})
    for claim in pilot['annotation']['claims']:
        expected[pilot['call_id'] + ':' + claim['claim_id']] = claim['exact_quote']
    assert pilot['review_label'] == 'agent-assisted' and not pilot['human_reviewed']
    assert pilot['call_id'] == 'row-1289__no_history__ORIGINAL'
    assert not pilot['annotation']['valid'] and pilot['annotation']['claims'][0]['factual_status'] == 'supported'
    assert 'pilot-error' in page and 'pilot-omission' in page
    for family, entry in ex['entries'].items():
        if family == 'ORIGINAL': continue
        if not entry['skip_reason'] and ex['records'][family]:
            expected[family + '-original-prompt'] = original['messages'][0]['content']
            expected[family + '-edited-prompt'] = entry['messages'][0]['content']
            expected[family + '-original-explanation'] = response['parsed_result']['explanation']
            expected[family + '-edited-explanation'] = ex['records'][family]['response']['parsed_result']['explanation']
    for family, annotation in ex['annotations'].items():
        if not annotation: continue
        entry = ex['entries'][family]
        explanation = ex['records'][family]['response']['parsed_result']['explanation']
        for claim in annotation['claims']:
            key = entry['call_id'] + ':' + claim['claim_id']
            expected[key] = claim['exact_quote']
            if annotation['valid']:
                assert claim['exact_quote'] in explanation
        for rule in annotation['rules']:
            expected[entry['call_id'] + ':' + rule['rule_id']] = rule['exact_quote']
    for key, value in expected.items():
        assert parser.values.get(key) == value, 'Displayed text differs from saved source: ' + key
    main = data['metrics']['test']['with_history']
    label_counts_checked = 0
    inventory = data['annotation_label_inventory']
    for layer, rows in inventory['layers'].items():
        for row in rows:
            for dimension, labels in inventory['domains'].items():
                values = [('responses', row['responses']), ('claims', row['claims'])]
                values += [(label, row['counts'][dimension].get(label, 0)) for label in labels]
                for label, count in values:
                    key = ':'.join((layer, dimension, row['family'], label))
                    assert parser.values.get(key) == str(count), 'Displayed label count differs: ' + key
                    label_counts_checked += 1
    assert 'Rule-consistency rate' not in page and '<strong>Rule consistency:</strong>' not in page
    for key in ('facts_original', 'facts_edited', 'stale_claims'):
        value = main[key]
        displayed = (f'{value["numerator"]:,} of {value["denominator"]:,} {value["percentage"]:.1f}%'
                     if value['denominator'] else 'Not available')
        assert parser.values.get('claim-summary-' + key) == displayed, 'Claim summary differs from saved metric: ' + key
    assert main['accuracy']['numerator'] == 42 and main['accuracy']['denominator'] == 100
    assert main['families']['PRODUCT_ORDER_CONTROL']['invariance']['numerator'] == 42
    assert main['families']['PRODUCT_ORDER_CONTROL']['invariance']['denominator'] == 99
    assert main['families']['ANSWER_MAPPING_CONTROL']['invariance']['numerator'] == 49
    assert main['families']['ANSWER_MAPPING_CONTROL']['invariance']['denominator'] == 100
    assert len(ex['pairs']) == 8
    return {'main_tabs': 2, 'exact_source_texts_checked': len(expected), 'offline_math_formulas': parser.math,
            'highlighted_spans': parser.highlights, 'external_asset_dependencies': len(parser.external),
            'source_texts_and_annotation_linkage': 'passed', 'canonical_prediction_counts': 'passed',
            'eight_intervention_families': 'passed', 'claim_summary_counts': 'passed',
            'annotation_label_counts_checked': label_counts_checked, 'rule_consistency_removed': True,
            'saved_development_pilot_example': 'passed', 'model_calls': 0}
