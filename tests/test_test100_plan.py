"""Focused frozen-test planning checks; no predictor or annotator is called."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from choice_trust.development_pilot import FAMILIES, verify_edit
from choice_trust.test100_plan import (
    DEFAULT_CASES, build_plan, prepare, select_cases, verify_manifest,
)


class Test100PlanChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = [json.loads(line) for line in DEFAULT_CASES.read_text().splitlines()]
        cls.manifest, cls.targets = build_plan()

    def test_selection_is_outcome_blind_balanced_and_source_order_stable(self):
        selected, remaining = select_cases(self.rows)
        changed = deepcopy(list(reversed(self.rows)))
        for row in changed:
            row["target"] = "IGNORE OUTCOMES"
        selected_changed, remaining_changed = select_cases(changed)
        ids = [row["case_id"] for row, _ in selected]
        self.assertEqual(ids, [row["case_id"] for row, _ in selected_changed])
        self.assertEqual(remaining, remaining_changed)
        self.assertEqual(len(ids), 100)
        self.assertEqual(len(set(ids)), 100)
        self.assertEqual(len(remaining), 704)
        self.assertFalse(set(ids) & set(remaining))
        self.assertEqual({row["split"] for row, _ in selected}, {"test"})
        capacities = Counter(str(row["household_id"]) for row in self.rows
                             if row["split"] == "test" and not row.get("synthetic"))
        counts = Counter(str(row["household_id"]) for row, _ in selected)
        self.assertEqual(len(counts), len(capacities))
        self.assertEqual(sum(counts.values()), 100)
        for household, count in counts.items():
            if count < max(counts.values()) - 1:
                self.assertEqual(count, capacities[household])

    def test_all_eight_families_integrity_and_separate_targets(self):
        m = self.manifest
        self.assertEqual(len(m["entries"]), 900)
        self.assertEqual(m["development_price_bounds_cents"], [30, 1930])
        self.assertEqual(len(self.targets), 100)
        selected = {row["case_id"]: row for row in self.rows if row["case_id"] in self.targets}
        self.assertEqual({e["family"] for e in m["entries"]}, {"ORIGINAL", *FAMILIES})
        self.assertNotIn("UNCHANGED_RERUN", {e["family"] for e in m["entries"]})
        for index, item in enumerate(m["selected_cases"]):
            self.assertEqual(item["price_variant"], "preserve" if index % 2 == 0 else "reverse")
            self.assertEqual(self.targets[item["case_id"]], selected[item["case_id"]]["target"])
        for entry in m["entries"]:
            self.assertEqual(entry["condition"], "with_history")
            self.assertEqual(set(entry["original_source"]), {"candidates", "current", "support"})
            self.assertEqual(len(entry["original_source"]["support"]), len(selected[entry["case_id"]]["support"]))
            if entry["applicable"]:
                self.assertTrue(verify_edit(entry, m["development_price_bounds_cents"])["target_excluded"])
                if entry["family"] == "HISTORICAL_OFFER_REMOVAL":
                    before = entry["original_source"]["support"]
                    after = entry["edited_source"]["support"]
                    self.assertEqual([h["purchased"] for h in before], [h["purchased"] for h in after])
                    self.assertTrue(all(v is None for h in after for field in ("prices", "advertised")
                                        for v in h[field].values()))
            else:
                self.assertTrue(entry["skip_reason"])
                self.assertEqual(entry["initial_status"], "not_applicable")

    def test_freeze_reuse_is_read_only_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "study"
            with patch("choice_trust.test100_plan.build_plan", return_value=(deepcopy(self.manifest), deepcopy(self.targets))) as build:
                first = prepare(out)
                before = {p.name: p.read_bytes() for p in out.iterdir()}
                second = prepare(out)
                self.assertEqual(build.call_count, 1)
            self.assertEqual(first["plan_id"], second["plan_id"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in out.iterdir()})
            with self.assertRaisesRegex(ValueError, "seed/source"):
                prepare(out, seed=43)
            path = out / "manifest.json"
            corrupted = json.loads(path.read_text())
            corrupted["entries"][0]["original_source"]["current"]["prices"]["A"] = 0
            path.write_text(json.dumps(corrupted))
            with self.assertRaisesRegex(ValueError, "seal"):
                verify_manifest(out)

    def test_incomplete_stage_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            artifact = out / "selected_cases.json"
            artifact.write_text("preserve this partial stage")
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                prepare(out)
            self.assertEqual(artifact.read_text(), "preserve this partial stage")


if __name__ == "__main__":
    unittest.main()
