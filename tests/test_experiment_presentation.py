"""Focused offline checks of reporting semantics, identity and exact text."""
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import json
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from choice_trust.experiment_presentation import matched_influence, stale_metrics, assess_rule, select_example, conditional_change_counts, annotation_label_inventory
from choice_trust.experiment_presentation_html import diff_text, development_pilot_annotation
from verify_experiment_presentation import Extract


def annotation(claims, complete=True):
    return {'claims': claims, 'coverage_complete': complete}


def claim(field, role='contributing', status='contradicted', group='CURRENT_PRICES', relationship='current_price_comparison'):
    return {'claim_id': 'C1', 'concept_groups': [group], 'source_fields': [field] if field else [],
            'claimed_role': role, 'factual_status': status, 'relationship_type': relationship}


class PresentationTests(unittest.TestCase):
    def test_false_claim_still_claims_influence(self):
        a = annotation([claim('current.prices.A', role='decisive')])
        self.assertEqual(matched_influence(a, 'CURRENT_PRICE', [{'field': 'current.prices.A'}])['classification'], 'yes')

    def test_wrong_candidate_field_does_not_match(self):
        a = annotation([claim('current.prices.B')])
        self.assertEqual(matched_influence(a, 'CURRENT_PRICE', [{'field': 'current.prices.A'}])['classification'], 'no')

    def test_description_is_not_influence(self):
        a = annotation([claim('current.prices.A', role='descriptive_only')])
        self.assertEqual(matched_influence(a, 'CURRENT_PRICE', [{'field': 'current.prices.A'}])['classification'], 'no')

    def test_broad_group_is_unclear_and_missing_is_not_negative(self):
        a = annotation([claim(None)], complete=False)
        self.assertEqual(matched_influence(a, 'CURRENT_PRICE', [{'field': 'current.prices.A'}])['classification'], 'unclear')
        self.assertEqual(matched_influence(None, 'CURRENT_PRICE', [{'field': 'current.prices.A'}])['classification'], 'unassessable')

    def test_frequency_and_removed_offers_are_distinct(self):
        a = annotation([claim('H2.purchased', group='HOUSEHOLD_HISTORY', relationship='support_purchase_frequency')])
        self.assertEqual(matched_influence(a, 'SUPPORT_PURCHASE', [{'field': 'H1.purchased'}])['classification'], 'yes')
        self.assertEqual(matched_influence(a, 'HISTORICAL_OFFER_REMOVAL', [{'field': 'H1.prices.A'}])['classification'], 'no')

    def test_stale_denominators_and_original_reference(self):
        def c(scope, status):
            return {'comparison_assessment': {'temporal_scope': scope, 'stale_status': status}}
        a = {'x': annotation([c('current_edited', 'stale'), c('current_edited', 'not_stale'),
                             c('explicit_original_reference', 'not_stale'), c('current_edited', 'unassessable')])}
        result = stale_metrics(a, ['x', 'missing'])
        self.assertEqual((result['claims']['numerator'], result['claims']['denominator']), (1, 2))
        self.assertEqual((result['responses']['numerator'], result['responses']['denominator']), (1, 1))
        self.assertEqual(result['claims']['annotation_coverage']['denominator'], 2)

    def test_no_invented_rule_from_contributing_reason(self):
        rule = {'explicit': True, 'sufficiently_specified': True, 'eligible_for_counterfactual_testing': True,
                'rule_type': 'choose_uniquely_cheapest_current_product', 'scope': 'all_current_candidates', 'claim_ids': ['C1']}
        a = {'rules': [rule], 'claims': [claim('current.prices.A', role='contributing')]}
        result = assess_rule({}, a, {})
        self.assertFalse(result['assessable'])
        self.assertIn('contributing', result['reason'])

    def test_conditional_denominators_keep_missing_labels_and_controls_separate(self):
        def pair(label, changed, *, valid=True, applicable=True, family='CURRENT_PRICE'):
            return {'family': family, 'applicable': applicable, 'valid_prediction_comparison': valid,
                    'prediction_changed': changed, 'influence': {'classification': label}}
        pairs = [pair('yes', True), pair('yes', False), pair('no', True), pair('no', False),
                 pair('unclear', True), pair('unassessable', False), pair('yes', None, valid=False),
                 pair('yes', None, valid=False, applicable=False), pair('yes', True, family='PRODUCT_ORDER_CONTROL')]
        rows, overall = conditional_change_counts(pairs)
        self.assertEqual(rows[0]['valid_prediction_pairs'], 6)
        self.assertEqual(overall['p_change_given_claimed_influence']['denominator'], 2)
        self.assertEqual(overall['p_change_given_no_influence_asserted']['denominator'], 2)
        self.assertEqual(overall['p_change_given_claimed_influence']['numerator'], 1)
        self.assertEqual(overall['unclear_excluded'], 1)
        self.assertEqual(overall['unassessable_excluded'], 1)
        self.assertEqual(overall['invalid_prediction_pairs_excluded'], 1)
        self.assertEqual(overall['valid_prediction_pairs'], 6)

    def test_diffs_preserve_every_character_including_whitespace(self):
        before = 'A: $9.80\nB: $6.40 & <available>\n'
        after = 'B: $6.40\nA: $9.81 & <available>\n'
        a, b = diff_text(before, after)
        for markup, expected in ((a, before), (b, after)):
            parser = Extract(); parser.feed('<pre data-exact-source="x">' + markup + '</pre>')
            self.assertEqual(parser.values['x'], expected)

    def test_label_inventory_keeps_unsupported_exclusions_and_product_identity(self):
        candidates = [{'id': 'A', 'name': 'alpha'}, {'id': 'B', 'name': 'beta'}]
        def entry(family, mapping):
            return {'condition': 'with_history', 'family': family, 'original_source': {'candidates': candidates},
                    'presentation': {'answer_mapping': mapping}}
        a = {**claim('current.prices.A', status='supported'), 'concept_groups': ['CURRENT_PRICES', 'HOUSEHOLD_HISTORY'],
             'direction': {'favors': ['A'], 'disfavors': []}}
        b = {**claim(None, role='descriptive_only', status='unsupported_by_supplied_information'),
             'concept_groups': [], 'direction': {'favors': [], 'disfavors': []}}
        edited = {**a, 'direction': {'favors': ['B'], 'disfavors': []},
                  'comparison_assessment': {'temporal_scope': 'current_edited', 'stale_status': 'not_stale'}}
        eligible = {'original': annotation([a, b]), 'mapped': annotation([edited])}
        excluded = {'excluded': annotation([{**a, 'factual_status': 'contradicted'}])}
        run = {'entries': {'original': entry('ORIGINAL', {'A': 'A', 'B': 'B'}),
                          'mapped': entry('ANSWER_MAPPING_CONTROL', {'A': 'B', 'B': 'A'}),
                          'excluded': entry('SUPPORT_PURCHASE', {'A': 'A', 'B': 'B'})},
               'responses': dict.fromkeys(('original', 'mapped', 'excluded')), 'annotations': eligible,
               'raw_annotations': {**eligible, **excluded}}
        inventory = annotation_label_inventory(run)
        rows = {row['family']: row for row in inventory['layers']['eligible']}
        self.assertEqual(rows['ORIGINAL']['claims'], 2)
        self.assertEqual(rows['ORIGINAL']['counts']['factual_status']['unsupported_by_supplied_information'], 1)
        self.assertEqual(sum(rows['ORIGINAL']['counts']['concept_groups'].values()), 3)
        self.assertEqual(rows['ANSWER_MAPPING_CONTROL']['counts']['direction']['favors:A'], 1)
        self.assertNotIn('favors:B', rows['ANSWER_MAPPING_CONTROL']['counts']['direction'])
        self.assertEqual(rows['ALL_DISTINCT']['claims'], 3)
        self.assertEqual(inventory['layers']['excluded'][-1]['claims'], 1)
        self.assertEqual(rows['ORIGINAL']['counts']['stale_status']['not_annotated'], 2)

    def test_frozen_example_and_linked_source_in_generated_report(self):
        config = json.loads((ROOT / 'presentation/report_config.json').read_text())
        self.assertEqual(config['example_case_id'], 'row-44')
        page = (ROOT / 'presentation/index.html').read_text()
        parser = Extract(); parser.feed(page)
        self.assertEqual(len(parser.tabs), 2)
        self.assertFalse(parser.external)
        original = json.loads((ROOT / 'choice_study/test_with_history_100_v1/responses/row-44__with_history__ORIGINAL.json').read_text())
        self.assertIn(parser.values['row-44__with_history__ORIGINAL:C1'], original['response']['parsed_result']['explanation'])
        self.assertEqual(parser.values['original-prompt'], original['response']['messages'][0]['content'])

    def test_assembly_has_no_network_or_inference_path(self):
        from experiment_presentation_snapshot import latest_luna
        from presentation_snapshot import latest
        from choice_trust.experiment_presentation import assemble
        with tempfile.TemporaryDirectory() as temp, \
             patch('socket.create_connection', side_effect=AssertionError('Unexpected network')), \
             patch('choice_trust.luna_annotations.LunaInspection.annotate_one', side_effect=AssertionError('Unexpected annotation call')), \
             patch('choice_trust.luna_batch.LunaBatch.process', side_effect=AssertionError('Unexpected batch call')):
            data = assemble(latest_luna(), latest(), Path(temp) / 'config.json')
        self.assertEqual(data['model_calls'], 0)
        self.assertEqual(data['config']['example_case_id'], 'row-44')
        pilot = data['development_annotation_example']
        self.assertEqual(pilot['call_id'], 'row-1289__no_history__ORIGINAL')
        self.assertEqual(pilot['review_label'], 'agent-assisted')
        self.assertFalse(pilot['human_reviewed'])
        self.assertFalse(pilot['annotation']['valid'])
        self.assertEqual(pilot['annotation']['claims'][0]['factual_status'], 'supported')
        self.assertNotIn(pilot['annotation']['claims'][0]['exact_quote'], pilot['response']['response']['parsed_result']['explanation'])
        self.assertEqual(pilot['review']['proposed_claims'][0]['factual_status'], 'contradicted')
        pilot_parser = Extract(); pilot_parser.feed(development_pilot_annotation(pilot))
        self.assertEqual(pilot_parser.values['pilot-explanation'], pilot['response']['response']['parsed_result']['explanation'])
        self.assertEqual(pilot_parser.values[pilot['call_id'] + ':C1'], pilot['annotation']['claims'][0]['exact_quote'])
        cohort = data['metrics']['test']['with_history']
        for row in cohort['conditional_change_by_family'] + [cohort['conditional_change_overall_pair_weighted']]:
            expected = cohort if row['family'] == 'OVERALL_PAIR_WEIGHTED' else cohort['families'][row['family']]
            for key, metric in (('p_change_given_claimed_influence', 'p_claimed'),
                                ('p_change_given_no_influence_asserted', 'p_not_claimed')):
                self.assertEqual(row[key]['numerator'], expected[metric]['numerator'])
                self.assertEqual(row[key]['denominator'], expected[metric]['denominator'])
            self.assertEqual(row['valid_prediction_pairs'], sum(row[k] for k in (
                'yes_changed', 'yes_unchanged', 'no_changed', 'no_unchanged', 'unclear_excluded', 'unassessable_excluded')))
        coverage = cohort['annotation_coverage']
        self.assertEqual(coverage['linked_total'], coverage['linked_originals'] + coverage['linked_edited'])
        self.assertEqual(coverage['distinct_responses'], coverage['linked_total']
                         + coverage['excluded_annotation_sources'] + coverage['missing_annotations'])
        inventory = data['annotation_label_inventory']
        rows = {r['family']: r for r in inventory['layers']['eligible']}
        self.assertEqual(rows['ORIGINAL']['counts']['factual_status'], cohort['facts_original']['claim_status_counts'])
        self.assertEqual(rows['ALL_EDITED']['counts']['factual_status'], cohort['facts_edited']['claim_status_counts'])
        self.assertEqual(rows['ALL_DISTINCT']['responses'], data['valid_annotation_records'])
        self.assertEqual(inventory['layers']['excluded'][-1]['responses'],
                         data['all_annotation_records'] - data['valid_annotation_records'])
        for layer in inventory['layers'].values():
            for row in layer:
                for key, counts in row['counts'].items():
                    if key not in ('concept_groups', 'direction'):
                        self.assertEqual(sum(counts.values()), row['claims'])


if __name__ == '__main__':
    unittest.main()
