"""Available citations have no count cap; structural checks remain independent."""
import copy
import json
import unittest
from unittest.mock import Mock

from choice_trust.model import (
    PROMPT_VERSION,
    RemoteBackend,
    explanation_prompt,
    parse_explanation,
)
from choice_trust.schema import visible_evidence


def case_fixture():
    candidates = [dict(id=label, name="Brand " + label) for label in "ABCD"]
    facts = [dict(id="P_" + label, candidate_id=label, type="price", value=index + 1,
                  units="dataset units", editable=True,
                  policy=dict(development_bounds=[1, 20]))
             for index, label in enumerate("ABCD")]
    facts += [dict(id="H" + str(index), candidate_id=None, type="history",
                   value=dict(choice="A"), units="observation", editable=False)
              for index in range(1, 6)]
    return dict(task="purchase", candidates=candidates, evidence=facts,
                outcome="SHOULD_NEVER_APPEAR_IN_THE_PROMPT")


class ExplanationContractTests(unittest.TestCase):
    def setUp(self):
        self.case = case_fixture()
        self.facts = visible_evidence(self.case)

    def response(self, ids, **extra):
        obj = dict(evidence_ids=ids, explanation="A checkable concise reason.", counterfactual=None)
        obj.update(extra)
        return dict(text=json.dumps(obj), finish_reason="stop")

    def test_prompt_allows_all_available_citations_and_omits_observed_outcome(self):
        text = explanation_prompt(self.case, "full", "A")
        self.assertNotIn("THREE IDs TOTAL", text)
        self.assertEqual(PROMPT_VERSION, "common-evidence-v4-unlimited-citations")
        self.assertIn("There is no citation-count limit", text)
        self.assertIn("any number", text)
        self.assertIn("cite both sides", text)
        self.assertIn("No Markdown fences", text)
        self.assertNotIn(self.case["outcome"], text)
        self.assertNotIn("Return exactly one answer label", text)

    def test_prompt_only_offers_visible_ids_and_a_valid_json_example(self):
        text = explanation_prompt(self.case, "no_history", "A")
        marker = "from this allowed list:\n"
        offered = json.loads(text.split(marker, 1)[1].splitlines()[0])
        self.assertEqual(set(offered), {"P_A", "P_B", "P_C", "P_D"})
        self.assertNotIn('"H1"', text)
        example = text.split("For example, a valid abstention is: ", 1)[1].splitlines()[0]
        status = parse_explanation(dict(text=example), visible_evidence(self.case, "no_history"))
        self.assertTrue(status["parse_ok"])
        self.assertTrue(status["citation_valid"])
        self.assertTrue(status["abstained"])
        self.assertNotIn("proposed_new_value", text)

    def test_four_prices_and_five_history_ids_are_usable_without_trimming(self):
        for ids in (["P_A", "P_B", "P_C", "P_D"], ["H1", "H2", "H3", "H4", "H5"]):
            with self.subTest(ids=ids):
                raw = self.response(ids)
                before = copy.deepcopy(raw)
                status = parse_explanation(raw, self.facts)
                self.assertTrue(status["parse_ok"])
                self.assertTrue(status["citation_valid"])
                self.assertTrue(status["usable_for_evidence_interventions"])
                self.assertIsNone(status["parse_error"])
                self.assertEqual(raw, before)
                self.assertEqual(json.loads(raw["text"])["evidence_ids"], ids)

    def test_three_distinct_supported_ids_remain_valid(self):
        raw = self.response(["P_A", "P_B", "H1"], counterfactual=dict(
            evidence_id="P_A", value=1.2, expected_direction="decrease"))
        status = parse_explanation(raw, self.facts)
        self.assertTrue(status["parse_ok"])
        self.assertTrue(status["citation_valid"])
        self.assertIsNone(status["claim_error"])
        self.assertEqual(status["parsed"]["evidence_ids"], ["P_A", "P_B", "H1"])

    def test_duplicate_and_unavailable_ids_keep_distinct_failure_status(self):
        duplicate = parse_explanation(self.response(["P_A", "P_A"]), self.facts)
        self.assertTrue(duplicate["parse_ok"])
        self.assertFalse(duplicate["citation_assessment"]["citations_unique"])
        self.assertTrue(duplicate["citation_assessment"]["cited_ids_exist"])
        unavailable = parse_explanation(self.response(["NOT_AN_INPUT_ID"]), self.facts)
        self.assertTrue(unavailable["parse_ok"])
        self.assertFalse(unavailable["citation_valid"])
        self.assertIn("Unavailable", unavailable["parse_error"])

    def test_malformed_json_is_not_completed_or_repaired(self):
        for text in ('{"evidence_ids":["P_A"],"explanation":"unfinished',
                     '{"evidence_ids":["P_A"],"explanation":"x",}', None):
            with self.subTest(text=text):
                raw = dict(text=text, finish_reason="length")
                before = copy.deepcopy(raw)
                status = parse_explanation(raw, self.facts)
                self.assertFalse(status["parse_ok"])
                self.assertIsNone(status["parsed"])
                self.assertEqual(raw, before)

    def test_wrapped_json_readability_and_missing_required_claim_are_separate(self):
        obj = dict(evidence_ids=["P_A"], explanation="A concise recorded reason.")
        raw = dict(text="Recorded response:\n```json\n" + json.dumps(obj) + "\n```", finish_reason="stop")
        before = copy.deepcopy(raw)
        status = parse_explanation(raw, self.facts)
        self.assertTrue(status["parse_ok"])
        self.assertTrue(status["citation_valid"])
        self.assertEqual(status["parsed"], obj)
        self.assertFalse(status["citation_assessment"]["response_is_json"])
        self.assertEqual(status["citation_assessment"]["missing_fields"], ["counterfactual"])
        self.assertFalse(status["usable_for_evidence_interventions"])
        self.assertEqual(raw, before)

    def test_remote_explain_returns_the_original_invalid_response_without_retry(self):
        backend = RemoteBackend.__new__(RemoteBackend)
        raw = self.response(["P_A", "P_B", "P_C", "P_D"])
        raw["finish_reason"] = "length"
        backend.request = Mock(return_value=raw)
        backend.check_identity = Mock()
        result = backend.explain(self.case, "full", "A")
        self.assertIs(result, raw)
        backend.request.assert_called_once_with(
            "/explain", dict(prompt=explanation_prompt(self.case, "full", "A")))
        backend.check_identity.assert_called_once_with(raw)
        self.assertEqual(result["finish_reason"], "length")
        self.assertTrue(parse_explanation(result, self.facts)["parse_ok"])
        self.assertFalse(parse_explanation(result, self.facts)["usable_for_evidence_interventions"])


if __name__ == "__main__":
    unittest.main()
