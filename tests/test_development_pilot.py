"""Integrity/budget regressions using development records; no model inference."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from choice_trust.development_pilot import (plan_pilot, verify_edit, model_inputs, association_edit,
                                           history_statistics, patch_between, identity_presentation)
from choice_trust.pilot_execution import Pilot

ROOT = Path(__file__).resolve().parents[1]


class DevelopmentPilotChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = plan_pilot(ROOT / "data/processed/cases.jsonl")

    def test_predeclared_development_only_and_budgets(self):
        m = self.manifest
        self.assertEqual(len({c["household_id"] for c in m["selected_cases"]}), 2)
        self.assertEqual({c["split"] for c in m["selected_cases"]}, {"development"})
        self.assertEqual(m["budgets"]["planned_generations"], 32)
        self.assertEqual(len(m["annotation_call_ids"]), 6)
        self.assertEqual(len({e["call_id"] for e in m["entries"]}), len(m["entries"]))
        for e in m["entries"]:
            self.assertNotIn("target", e["original_source"])
            if not e["skip_reason"]:
                self.assertTrue(verify_edit(e, m["development_price_bounds_cents"])["regenerated"])

    def test_tampering_and_dependent_regeneration(self):
        e = deepcopy(next(e for e in self.manifest["entries"] if e["family"] == "CURRENT_PRICE"))
        e["edited_source"]["current"]["advertised"]["A"] = not e["edited_source"]["current"]["advertised"]["A"]
        e["patch"] = patch_between(e["original_source"], e["edited_source"], identity_presentation(e["original_source"]), e["presentation"])
        with self.assertRaisesRegex(ValueError, "Unrelated"):
            verify_edit(e, self.manifest["development_price_bounds_cents"])
        e = deepcopy(next(e for e in self.manifest["entries"] if e["family"] == "SUPPORT_PURCHASE" and not e["skip_reason"]))
        self.assertNotEqual(e["statistics_before"]["purchase_counts"], e["statistics_after"]["purchase_counts"])
        e["observations"]["text"] += "stale manual summary"
        with self.assertRaisesRegex(ValueError, "regenerated"):
            verify_edit(e, self.manifest["development_price_bounds_cents"])

    def test_vectors_missing_offers_and_answer_decoding(self):
        for e in self.manifest["entries"]:
            if e["skip_reason"]: continue
            if e["family"] in ("HISTORICAL_PRICE_ASSOCIATION", "HISTORICAL_ADVERTISING_ASSOCIATION"):
                self.assertEqual(e["statistics_before"]["purchase_counts"], e["statistics_after"]["purchase_counts"])
                self.assertNotEqual(e["edit_details"]["association_before"], e["edit_details"]["association_after"])
            if e["family"] == "HISTORICAL_OFFER_REMOVAL":
                self.assertEqual(e["statistics_after"]["among_cheapest"], [0, 0])
                self.assertIn("NOT_PROVIDED", e["observations"]["text"])
                self.assertTrue(all(v is None for h in e["edited_source"]["support"] for f in ("prices", "advertised") for v in h[f].values()))
            if e["family"] == "ANSWER_MAPPING_CONTROL":
                inputs = model_inputs(e["edited_source"], e["presentation"])
                names = {c["name"] for c in inputs["candidates"]}
                self.assertEqual(names, {c["name"] for c in e["original_source"]["candidates"]})
                self.assertNotEqual(e["presentation"]["answer_mapping"]["A"], "A")
        source = deepcopy(self.manifest["entries"][0]["original_source"])
        source = deepcopy(next(e["original_source"] for e in self.manifest["entries"] if e["condition"] == "with_history"))
        for h in source["support"]: h["advertised"] = {cid: False for cid in h["advertised"]}
        changed, detail = association_edit(source, "advertised")
        self.assertIsNone(changed)
        self.assertIn("never vary", detail["skip_reason"])

    def test_reuse_and_hard_budget_without_model_calls(self):
        class Config:
            def to_dict(self): return {"test_fixture": True}
        class Tokenizer:
            def apply_chat_template(self, messages, **kwargs): return json.dumps(messages)
        runtime = {"model_metadata": {"model_id": "Qwen/Qwen3-1.7B", "revision": "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e", "device": "cpu", "dtype": "torch.float32"},
                   "generation_config": Config(), "annotation_model": {}, "tokenizer": Tokenizer(), "model": None, "device": "cpu"}
        def fake(observations, candidates, **kwargs):
            from choice_trust.joint_observation import build_joint_messages
            messages = build_joint_messages(observations, candidates)
            return {"messages": messages, "rendered_prompt": json.dumps(messages), "raw_response": "TEST FIXTURE NOT A MODEL RESULT",
                    "parsed_result": {"prediction": candidates[0]["id"]}}
        with tempfile.TemporaryDirectory() as directory:
            pilot = Pilot.prepare(Path(directory) / "pilot").attach(runtime)
            with patch("choice_trust.pilot_execution.generate_joint_response", side_effect=fake) as mock:
                pilot.run("ORIGINAL"); pilot.run("ORIGINAL")
                self.assertEqual(mock.call_count, 4)
            self.assertEqual(pilot.status()["actual_generation_attempts"], 4)
            for i in range(28): pilot.reserve("generation", f"test-fixture-{i}")
            with self.assertRaisesRegex(RuntimeError, "budget"):
                pilot.reserve("generation", "over-cap")


if __name__ == "__main__": unittest.main()
