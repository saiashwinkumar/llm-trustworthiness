"""Annotation traceability checks. Literal test payloads are not model results."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import shutil

from choice_trust.explanation_annotation import (
    select_saved_explanation, load_guide, build_annotation_messages,
    validate_annotations, concept_summary, annotate_explanation, save_annotation,
)

ROOT = Path(__file__).resolve().parents[1]


class AnnotationChecks(unittest.TestCase):
    def setUp(self):
        self.example = select_saved_explanation(ROOT / "choice_study/joint_observation_runs")
        self.guide = load_guide(ROOT / "docs/EXPLANATION_ANNOTATION_GUIDE.md")
        self.claim = dict(claim_id="C1", exact_quote=self.example["explanation"].split(".")[0],
                          concept_groups=["CURRENT_PRICES"], relationship_type="current_price_comparison",
                          claimed_role="descriptive_only", direction={"favors": [], "disfavors": []},
                          mapped_evidence_ids=["P_A", "P_B", "P_C", "P_D"],
                          source_fields=[f"current.prices.{c}" for c in "ABCD"],
                          factual_status="unclear", annotation_note="Structural test fixture, not a semantic assessment")

    def validate(self, claims):
        return validate_annotations(json.dumps({"claims": claims}), explanation=self.example["explanation"],
                                    candidates=self.example["candidates"], provenance=self.example["provenance"])

    def test_exact_saved_input_and_no_target(self):
        inputs = {k: self.example[k] for k in ("explanation", "predicted_candidate", "model_citations", "candidates", "observations", "provenance")}
        messages = build_annotation_messages(**inputs, guide=self.guide)
        # JSON escaping may encode newlines, but the exact factual text roundtrips.
        self.assertIn(json.dumps(self.example["observations"]["text"]), messages[0]["content"])
        self.assertNotIn("target", inputs)
        self.assertNotIn("correct", self.example)
        self.assertTrue(self.example["condition"] == "with_history")
        self.assertEqual(self.example["provenance"]["H1"]["concept_groups"], ["HOUSEHOLD_HISTORY"])
        self.assertEqual(self.example["observations"]["version"], "compact-factual-observations-v2")
        self.assertEqual(self.example["source_prompt_version"], "joint-compact-factual-observation-v2")
        self.assertIn("[P_A] A: $9.80", self.example["observations"]["text"])
        self.assertNotIn("[OBS:", self.example["observations"]["text"])
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(select_saved_explanation(Path(directory)))

    def test_legacy_history_cannot_override_current_prompt_selection(self):
        paths = sorted((ROOT / "choice_study/joint_observation_runs").glob("*/*.json"))
        records = [(p, json.loads(p.read_text())) for p in paths]
        legacy = next(p for p, r in records if r["observation_version"] == "factual-observations-v1" and r["condition"] == "with_history")
        current_no = next(p for p, r in records if r["observation_version"] == "compact-factual-observations-v2" and r["condition"] == "no_history")
        current_yes = next(p for p, r in records if r["observation_version"] == "compact-factual-observations-v2" and r["condition"] == "with_history")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("00-old", "01-current"):
                (root / name).mkdir()
            shutil.copy2(legacy, root / "00-old" / legacy.name)
            self.assertIsNone(select_saved_explanation(root))
            shutil.copy2(current_no, root / "01-current" / current_no.name)
            self.assertEqual(select_saved_explanation(root)["condition"], "no_history")
            shutil.copy2(current_yes, root / "01-current" / current_yes.name)
            selected = select_saved_explanation(root)
            self.assertEqual(selected["condition"], "with_history")
            self.assertEqual(selected["source_prompt_version"], "joint-compact-factual-observation-v2")
            # Legacy access remains explicit, with its own original facts.
            old = select_saved_explanation(root, observation_version="factual-observations-v1", prompt_version="joint-factual-observation-v1")
            self.assertIn("[OBS:", old["observations"]["text"])

    def test_invalid_quotes_ids_groups_candidates_and_fields_remain_visible(self):
        parsed, checks = self.validate([self.claim])
        self.assertTrue(checks["structure_and_traceability_ok"])
        bad = copy.deepcopy(self.claim)
        bad.update(exact_quote="invented test quote", concept_groups=["BRAND_LOYALTY"],
                   mapped_evidence_ids=["MISSING"], source_fields=["H999.purchased"],
                   direction={"favors": ["MISSING"], "disfavors": []})
        parsed, checks = self.validate([bad])
        self.assertEqual(parsed["claims"][0], bad)
        self.assertFalse(checks["structure_and_traceability_ok"])
        self.assertGreaterEqual(len(checks["claim_checks"][0]["issues"]), 5)
        # Malformed fields must produce diagnostics, rather than validator crashes.
        bad["relationship_type"] = []
        _, checks = self.validate([bad])
        self.assertFalse(checks["structure_and_traceability_ok"])

    def test_malformed_response_and_mixed_summary(self):
        parsed, diagnostics = validate_annotations("not json", explanation=self.example["explanation"],
             candidates=self.example["candidates"], provenance=self.example["provenance"])
        self.assertIsNone(parsed)
        self.assertFalse(diagnostics["parse_ok"])
        contributing = {**self.claim, "claim_id": "C2", "claimed_role": "contributing"}
        parsed, diagnostics = self.validate([self.claim, contributing])
        result = {"parsed_annotations": parsed, "diagnostics": diagnostics}
        rows = concept_summary(result)
        self.assertIn("claimed influence", rows[0]["signals"])
        self.assertIn("description only", rows[0]["signals"])
        self.assertTrue(rows[0]["mixed signals; review"])
        self.assertIn("not mentioned", rows[1]["signals"])
        result["diagnostics"]["generation_truncated"] = True
        self.assertIn("coverage unavailable", concept_summary(result)[1]["signals"])

    def test_one_callback_and_invalid_raw_response_preserved(self):
        calls = []
        def generate(messages):
            calls.append(messages)
            return {"text": "  invalid JSON test payload\n", "truncated": True}
        inputs = {k: self.example[k] for k in ("explanation", "predicted_candidate", "model_citations", "candidates", "observations", "provenance")}
        result = annotate_explanation(**inputs, guide=self.guide, generate=generate,
                                      annotator_model=self.example["predictor_model"], predictor_model=self.example["predictor_model"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["raw_annotation_response"], "  invalid JSON test payload\n")
        self.assertIsNone(result["parsed_annotations"])
        self.assertTrue(result["diagnostics"]["generation_truncated"])
        with tempfile.TemporaryDirectory() as directory:
            path = save_annotation(result, Path(directory), self.example)
            saved = json.loads(path.read_text())
            self.assertEqual(saved["annotation_input"]["model_citations"], self.example["model_citations"])
            self.assertEqual(saved["raw_annotation_response"], result["raw_annotation_response"])


if __name__ == "__main__":
    unittest.main()
