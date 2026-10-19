"""Research integrity checks; run with python -m unittest discover -s tests -v."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from experiment import (LABELS, MockBackend, counterfactual, evidence, matched_random_sets,
                        parse_explanation, prediction_prompt, read_jsonl)
from prepare_data import BRAND_MAP, build_cases


def fixture_rows():
    rows = []
    for household in range(10):
        for occasion in range(8):
            rows.append({"source_row": len(rows) + 1, "household_id": str(household),
                         "prices": {label: 4.0 + i + occasion / 10 for i, label in enumerate(LABELS)},
                         "ads": {label: label == "A" for label in LABELS}, "choice": LABELS[household % 4]})
    return rows


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.cases, self.manifest = build_cases(fixture_rows(), seed=42)
        self.case = self.cases[0]

    def test_query_label_is_not_sent(self):
        changed = copy.deepcopy(self.case)
        changed["target"] = "NEVER_SEND_THIS_LABEL"
        for condition in ("no_history", "with_history"):
            self.assertEqual(prediction_prompt(self.case, condition), prediction_prompt(changed, condition))

    def test_support_and_queries_disjoint_and_households_separate(self):
        sets = list(map(set, self.manifest["split_household_ids"].values()))
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])
        for allocation in self.manifest["household_allocation"].values():
            self.assertFalse(set(allocation["support_source_rows"]) & set(allocation["query_source_rows"]))
        self.assertEqual(self.cases, build_cases(fixture_rows(), seed=42)[0])

    def test_interventions_keep_candidate_set(self):
        text = prediction_prompt(self.case, "with_history", keep={"P_A"})
        for label, brand in BRAND_MAP.items():
            self.assertIn(f"{label}: {brand}", text)
        self.assertIn("[H1] NOT_PROVIDED", text)
        self.assertNotIn("[H1]", prediction_prompt(self.case, "no_history"))

    def test_random_controls_match_evidence_roles(self):
        facts = evidence(self.case, "with_history")
        for selected in matched_random_sets(facts, ["P_A", "F_A", "H1"], 20, 42):
            self.assertEqual(sorted(facts[i]["role"] for i in selected), ["ad", "history", "price"])

    def test_invalid_citations_are_not_scored(self):
        text = json.dumps({"evidence_ids": ["H1"], "explanation": "Invented history"})
        obj, error = parse_explanation(text, set(evidence(self.case, "no_history")))
        self.assertIsNone(obj)
        self.assertIn("Unavailable", error)

    def test_counterfactual_does_not_mutate_original(self):
        original = copy.deepcopy(self.case)
        obj = {"evidence_ids": ["P_A"], "counterfactual": {"evidence_id": "P_A", "change": "increase",
                "expected_effect_on_chosen_probability": "decrease"}}
        changed, expected, error = counterfactual(self.case, obj)
        self.assertIsNone(error)
        self.assertEqual(expected, "decrease")
        self.assertEqual(self.case, original)
        self.assertAlmostEqual(changed["query"]["prices"]["A"], original["query"]["prices"]["A"] * 1.2)

    def test_only_incomplete_tail_can_be_recovered(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.jsonl"
            path.write_text('{"ok": 1}\n{"partial":', encoding="utf-8")
            self.assertEqual(read_jsonl(path, True), [{"ok": 1}])
            self.assertEqual(path.read_text(), '{"ok": 1}\n')
            path.write_text('{"bad":\n{"ok": 1}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                read_jsonl(path, True)

    def test_mock_scores_are_finite_and_normalized(self):
        probs = MockBackend().score("", case=self.case, condition="with_history")["probabilities"]
        self.assertEqual(set(probs), set(LABELS))
        self.assertAlmostEqual(sum(probs.values()), 1)
        self.assertTrue(all(0 < p < 1 for p in probs.values()))


if __name__ == "__main__":
    unittest.main()
