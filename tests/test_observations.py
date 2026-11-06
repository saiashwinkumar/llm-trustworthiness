"""Focused checks against existing prepared purchase records."""
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path
import unittest

from choice_trust.observations import generate_observations, inputs_from_prepared_yogurt, render_observations


CASES = Path(__file__).resolve().parents[1] / "data/processed/cases.jsonl"


def actual_case(case_id):
    with CASES.open(encoding="utf-8") as handle:
        for line in handle:
            case = json.loads(line)
            if case["case_id"] == case_id:
                return case
    raise AssertionError(f"missing prepared case {case_id}")


class ObservationChecks(unittest.TestCase):
    def test_real_case_values_relationships_and_provenance(self):
        case = actual_case("row-2")
        output = generate_observations(**inputs_from_prepared_yogurt(case, with_history=True))
        obs = {o["id"]: o for o in output["audit"]["source_comparisons"]}
        ids = list(case["brand_map"])
        self.assertEqual(len(obs), len(output["audit"]["source_comparisons"]))
        self.assertEqual(output["text"], render_observations(output["observations"], history_provided=True))
        for cid in ids:
            self.assertEqual(obs[f"P_{cid}"]["value"], case["query"]["prices"][cid])
            self.assertEqual(obs[f"P_{cid}"]["sources"], [f"current.prices.{cid}"])
            self.assertEqual(obs[f"F_{cid}"]["value"], case["query"]["ads"][cid])
            self.assertEqual(obs[f"F_{cid}"]["sources"], [f"current.advertised.{cid}"])
        cheapest = min(case["query"]["prices"], key=case["query"]["prices"].get)
        self.assertEqual(obs["OBS:current:cheapest"]["value"], [cheapest])
        self.assertEqual(obs["OBS:current:advertised"]["value"]["none_advertised"],
                         not any(case["query"]["ads"].values()))
        counts = Counter(h["choice"] for h in case["support"])
        among = advertised = 0
        for h in case["support"]:
            hid = h["evidence_id"]
            purchased = h["choice"]
            self.assertEqual(obs[hid]["value"],
                             {"prices": h["prices"], "advertised": h["ads"], "purchased": purchased})
            self.assertIn(f"{hid}.purchased", obs[hid]["sources"])
            self.assertEqual(obs[f"{hid}:purchase"]["sources"], [f"{hid}.purchased"])
            minimum = min(Decimal(str(v)) for v in h["prices"].values())
            expected_gap = Decimal(str(h["prices"][purchased])) - minimum
            among += expected_gap == 0
            advertised += h["ads"][purchased]
            self.assertEqual(obs[f"{hid}:gap"]["value"]["gap_decimal"], str(expected_gap))
            self.assertEqual(obs[f"{hid}:cheapest"]["value"]["among_cheapest"], expected_gap == 0)
            self.assertEqual(obs[f"{hid}:advertised"]["value"], h["ads"][purchased])
            self.assertIn(f"{hid}.purchased", obs[f"{hid}:cheapest"]["sources"])
            self.assertEqual(set(obs[f"{hid}:cheapest"]["sources"]),
                             {f"{hid}.purchased"} | {f"{hid}.prices.{cid}" for cid in ids})
        for cid in ids:
            v = obs[f"OBS:support:count:{cid}"]["value"]
            self.assertEqual((v["numerator"], v["denominator"]), (counts[cid], len(case["support"])))
            self.assertEqual(set(obs[f"OBS:support:count:{cid}"]["sources"]),
                             {f"{h['evidence_id']}.purchased" for h in case["support"]})
        self.assertEqual(obs["OBS:history:cheapest_count"]["value"]["numerator"], among)
        self.assertEqual(obs["OBS:history:advertised_count"]["value"]["numerator"], advertised)
        self.assertEqual(obs["OBS:history:cheapest_count"]["value"]["eligible_denominator"], len(case["support"]))

    def test_conditions_and_actual_advertisement(self):
        case = actual_case("row-39")
        no = generate_observations(**inputs_from_prepared_yogurt(case, with_history=False))
        yes = generate_observations(**inputs_from_prepared_yogurt(case, with_history=True))
        no_obs = {o["id"]: o for o in no["audit"]["source_comparisons"]}
        yes_obs = {o["id"]: o for o in yes["audit"]["source_comparisons"]}
        self.assertEqual(no_obs["OBS:support:availability"]["status"], "unavailable")
        self.assertEqual(yes_obs["OBS:support:availability"]["value"], len(case["support"]))
        zero = generate_observations(**{**inputs_from_prepared_yogurt(case, with_history=False), "support": []})
        zero_obs = {o["id"]: o for o in zero["audit"]["source_comparisons"]}
        self.assertEqual(zero_obs["OBS:support:availability"]["value"], 0)
        self.assertEqual(zero_obs["OBS:support:availability"]["status"], "available")
        self.assertFalse(any(h["evidence_id"] in no_obs for h in case["support"]))
        self.assertEqual(no_obs["OBS:current:advertised"]["value"]["known_advertised"],
                         [cid for cid, flag in case["query"]["ads"].items() if flag])
        self.assertEqual({k: no_obs[k] for k in no_obs if k.startswith(("P_", "F_", "OBS:current:"))},
                         {k: yes_obs[k] for k in yes_obs if k.startswith(("P_", "F_", "OBS:current:"))})

    def test_actual_price_tie_is_explicit(self):
        case = actual_case("row-20")
        output = generate_observations(**inputs_from_prepared_yogurt(case, with_history=False))
        order = next(o for o in output["audit"]["source_comparisons"] if o["id"] == "OBS:current:price_order")
        self.assertIn(["A", "C"], order["value"]["tiers"])
        self.assertIn("A (dannon) = C (weight)", order["statement"])


if __name__ == "__main__":
    unittest.main()
