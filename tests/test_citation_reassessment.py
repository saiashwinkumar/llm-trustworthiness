import json
from pathlib import Path
import tempfile
import unittest

from choice_trust.citations import assess_response
from choice_trust.model import parse_explanation
from choice_trust.interventions import explanation_tests
from scripts.reassess_citations import reassess
from test_explanation_contract import case_fixture
from choice_trust.schema import visible_evidence


class CitationReassessmentTests(unittest.TestCase):
    def test_separate_checks_and_no_mutation(self):
        raw = json.dumps(dict(evidence_ids=['a', 'a', 'missing'], explanation='x'))
        a = assess_response(raw, ['a'])
        self.assertTrue(a['json_readable'])
        self.assertFalse(a['required_fields_present'])
        self.assertEqual(a['missing_fields'], ['counterfactual'])
        self.assertEqual(a['unknown_ids'], {'evidence_ids': ['missing']})
        self.assertEqual(a['duplicate_ids'], {'evidence_ids': ['a']})
        self.assertFalse(a['usable_for_evidence_interventions'])

    def test_four_citations_actually_plan_evidence_interventions(self):
        case = dict(case_fixture(), case_id="citation-test")
        ids = ['P_A', 'P_B', 'P_C', 'P_D']
        e = parse_explanation({'text': json.dumps(dict(evidence_ids=ids, explanation='x', counterfactual=None))}, visible_evidence(case))
        specs = explanation_tests(case, 'no_history', e, 1, 42)
        for kind in ('cited_remove', 'cited_retain'):
            spec = next(s for s in specs if s['kind'] == kind)
            self.assertEqual(spec['evidence_ids'], ids)
            self.assertFalse(spec.get('skip_reason'))

    def test_non_object_and_bad_types_do_not_crash(self):
        for obj in ([], None, 5, {'evidence_ids': [1], 'explanation': 0, 'counterfactual': 'x'}):
            result = assess_response(json.dumps(obj), ['a'])
            self.assertTrue(result['json_readable'])
            self.assertFalse(result['usable_for_evidence_interventions'])

    def test_sidecar_preserves_source_and_prior_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / 'outputs_cpu_fixture'
            run.mkdir()
            (run / 'run_manifest.json').write_text(json.dumps(dict(backend='real_llm', prompt_version='old')))
            row = dict(case_id='row-1', condition='no_history', split='validation',
                       raw_explanation=json.dumps(dict(evidence_ids=list('abcd'), explanation='x', counterfactual=None)),
                       provided_evidence={i: {} for i in 'abcd'}, parse_ok=False,
                       citation_valid=False, parse_error='Expected 0-3 IDs', abstained=False)
            source = run / 'faithfulness.jsonl'
            source.write_text(json.dumps(row) + '\n')
            before = source.read_bytes()
            out = root / 'new-assessment'
            result = reassess(root, out)
            self.assertEqual(result['now_usable'], 1)
            self.assertEqual(result['newly_usable'], 1)
            saved = json.loads((out / 'assessments.jsonl').read_text())
            self.assertEqual(saved['original_record'], row)
            self.assertEqual(source.read_bytes(), before)
            with self.assertRaises(ValueError): reassess(root, out)


if __name__ == '__main__':
    unittest.main()
