"""Compact input, rounding and citation boundaries; no model calls."""
import copy
import json
import unittest

from choice_trust.observations import canonical_price, generate_observations
from choice_trust.joint_observation import build_joint_messages, parse_joint_response
from tests.test_observations import actual_case
from choice_trust.observations import inputs_from_prepared_yogurt


class CompactObservationChecks(unittest.TestCase):
    def test_real_case_partition_and_prompt(self):
        case = actual_case("row-2")
        inputs = inputs_from_prepared_yogurt(case, with_history=True)
        original = copy.deepcopy(inputs)
        out = generate_observations(**inputs)
        self.assertEqual(inputs, original)
        self.assertEqual(len(out["observations"]), 2 * len(inputs["candidates"]) + len(inputs["support"]))
        refs = [r for o in out["observations"] for r in o["sources"]]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertEqual(set(refs), set(out["source_group_assignment"]))
        for o in out["observations"]:
            self.assertTrue(all(out["source_group_assignment"][r] == o["group"] for r in o["sources"]))
        self.assertEqual(out["audit"]["source_values"]["current.prices.A"], 9.7999997)
        self.assertIn("[P_A] A: $9.80", out["text"])
        self.assertIn("[H2]", out["text"])
        self.assertIn("[H3]", out["text"])  # Equal-valued separate purchases remain separate.
        prompt = build_joint_messages(out, out["candidates"])[0]["content"]
        self.assertNotIn("OBS:", prompt)
        self.assertNotIn("ALLOWED OBSERVATION IDS", prompt)
        self.assertNotIn("excluded", prompt)
        for o in out["observations"]:
            self.assertEqual(prompt.count(f"[{o['id']}]"), 1)
        self.assertEqual(set(out["evidence_group_assignment"].values()),
                         {"CURRENT_PRICES", "CURRENT_ADVERTISING", "HOUSEHOLD_HISTORY"})
        payload = {"explanation": "parser boundary check", "evidence_ids": [o["id"] for o in out["observations"]], "prediction": "A"}
        _, good = parse_joint_response(json.dumps(payload), out["candidates"], out)
        self.assertTrue(good["citations_valid"])  # No three-citation limit.
        payload["evidence_ids"] = ["OBS:support:count:A"]
        _, bad = parse_joint_response(json.dumps(payload), out["candidates"], out)
        self.assertFalse(bad["citations_valid"])

    def test_canonical_rounding_and_display_based_relationships(self):
        self.assertEqual([canonical_price(v) for v in (9.7999997, 6.4000003, 8.600000300000001, 1.005, None)],
                         ["9.80", "6.40", "8.60", "1.01", None])
        candidates = [{"id": "one", "name": "One"}, {"id": "two", "name": "Two"}]
        current = {"prices": {"one": 8.604, "two": 8.60}, "advertised": {"one": False, "two": None}}
        support = [{"id": "H1", **copy.deepcopy(current), "purchased": "one"}]
        out = generate_observations(candidates, current, support)
        raw = {o["id"]: o for o in out["audit"]["source_comparisons"]}
        displayed = {o["id"]: o for o in out["audit"]["model_visible_comparisons"]}
        self.assertEqual(raw["OBS:current:cheapest"]["value"], ["two"])
        self.assertEqual(displayed["OBS:current:cheapest"]["value"], ["one", "two"])
        self.assertFalse(raw["H1:cheapest"]["value"]["among_cheapest"])
        self.assertTrue(displayed["H1:cheapest"]["value"]["among_cheapest"])
        self.assertEqual(displayed["H1:gap"]["value"]["gap_decimal"], "0.00")
        self.assertIn("[F_two] two: NOT_PROVIDED", out["text"])
        current["prices"]["two"] = None
        missing = generate_observations(candidates, current)
        self.assertIn("[P_two] two: NOT_PROVIDED", missing["text"])
        self.assertNotIn("$NOT_PROVIDED", missing["text"])

    def test_variable_sizes_and_absent_versus_empty_support(self):
        for count in (1, 5, 28):
            candidates = [{"id": f"item{i}", "name": f"Item {i}"} for i in range(count)]
            current = {"prices": {c["id"]: i + 1 for i, c in enumerate(candidates)}, "advertised": {}}
            absent = generate_observations(candidates, current)
            empty = generate_observations(candidates, current, [])
            self.assertNotIn("HOUSEHOLD_HISTORY", absent["text"])
            self.assertIn("Household history: NOT_PROVIDED", absent["text"])
            self.assertIn("HOUSEHOLD_HISTORY\nSupplied support records: 0.", empty["text"])
            self.assertEqual(len(absent["observations"]), 2 * count)
            json.dumps(empty, allow_nan=False)
            self.assertIn(f"item{count-1} = Item {count-1}", build_joint_messages(absent, candidates)[0]["content"])


if __name__ == "__main__":
    unittest.main()
