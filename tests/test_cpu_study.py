"""Orchestration regressions use synthetic records; no model or network calls."""
import copy
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiment import digest, read_jsonl
from choice_trust.interventions import planned_specs
from choice_trust.storage import seal
from scripts import run_cpu_real_v2 as study


def cases_fixture(validation=2, test=20):
    rows = []
    for split, count in (("development", 2), ("validation", validation), ("test", test)):
        for i in range(count):
            rows.append(dict(schema_version=2, case_id=f"{split}-{i}",
                dataset_id="synthetic-study-test", task="purchase", split=split,
                group_id=f"group-{split}-{i}", synthetic=True, outcome="a", time=None,
                candidates=[dict(id="a", name="Product A", attributes={"price": "P_a"}),
                            dict(id="b", name="Product B", attributes={"price": "P_b"})],
                evidence=[dict(id=f"P_{cid}", candidate_id=cid, source="synthetic fixture",
                    type="price", value=price, units="fixture units", editable=True,
                    pre_decision=True, policy=dict(kind="numeric", multipliers=[.8, 1.2],
                        development_bounds=[1, 20])) for cid, price in (("a", 5), ("b", 8))],
                constraints=[]))
    return rows


def prepare_fixture(root, validation=2, test=20):
    cases = cases_fixture(validation, test)
    data = root / "data"
    data.mkdir()
    path = data / "cases.jsonl"
    path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    path.with_name("manifest.json").write_text(json.dumps({"cases_hash": digest(cases)}))
    return cases, path


def complete_synthetic_snapshot(cases, plan):
    """Materialize accounted-for fixture attempts, including explicit failures/skips."""
    preds, exps, interventions = {}, {}, {}
    index = {c["case_id"]: c for c in cases}
    for stage in plan["stages"]:
        for cid in stage["case_ids"]:
            for condition in stage["conditions"]:
                key = cid, condition
                pid = digest([cid, condition, "prediction"])
                common = dict(case_id=cid, condition=condition, split=index[cid]["split"])
                if stage["command"] == "predict":
                    preds[key] = dict(common, record_id=pid)
                elif stage["command"] == "explain":
                    exps[key] = dict(common, record_id=digest([pid, "explanation"]),
                        record_hash=digest([cid, condition, "synthetic explanation"]),
                        parse_ok=False, citation_valid=False, abstained=False,
                        truncated=False, parsed=None)
                else:
                    for spec in planned_specs(index[cid], condition, exps[key],
                            plan["random_controls"], plan["seed"], plan["permutations"], stage["suite"]):
                        rid = digest([pid, spec])
                        interventions[rid] = dict(record_id=rid, status="skipped")
    return {"predictions": [seal(r) for r in preds.values()],
            "explanations": [seal(r) for r in exps.values()],
            "interventions": [seal(r) for r in interventions.values()]}


AUDIT_FIELDS = ["case_id", "condition", "explanation_hash", "correct", "provided_evidence",
                "explanation", "supported_claims", "total_factual_claims", "reviewer_notes"]


def audit_rows(data):
    return [dict(case_id=e["case_id"], condition=e["condition"], explanation_hash=e["record_hash"],
        correct="", provided_evidence="synthetic fixture", explanation="synthetic fixture",
        supported_claims="", total_factual_claims="", reviewer_notes="")
        for e in data["explanations"] if e["split"] == "test"]


def write_audit(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_audit(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


class CPUStudyTests(unittest.TestCase):
    def test_formal_scope_counts_and_preselected_subsets(self):
        with tempfile.TemporaryDirectory() as directory:
            cases, path = prepare_fixture(Path(directory), validation=306, test=804)
            plan = study.make_plan(cases, path, mock=True)
            stages = {s["name"]: s for s in plan["stages"]}
            expected = {"validation_predictions": 612, "test_predictions": 1608,
                "validation_explanations": 40, "test_explanations": 200,
                "test_explanation_tests": 200, "test_systematic_with_history": 30}
            for name, total in expected.items():
                s = stages[name]
                self.assertEqual(len(s["case_ids"]) * len(s["conditions"]), total)
            explained = set(stages["test_explanations"]["case_ids"])
            self.assertEqual(explained, set(stages["test_explanation_tests"]["case_ids"]))
            self.assertTrue(set(stages["test_systematic_with_history"]["case_ids"]) <= explained)
            self.assertTrue(set(plan["manual_review_case_ids"]) <= explained)
            self.assertEqual(len(plan["manual_review_case_ids"]) * len(plan["conditions"]), 40)
            smoke = study.make_plan(cases, path, mock=True, smoke_limit=2)
            self.assertEqual(smoke["role"], "validation_smoke")
            self.assertEqual(smoke["random_controls"], 1)
            self.assertTrue(all(s["split"] == "validation" and len(s["case_ids"]) == 2
                                for s in smoke["stages"]))

    def test_missing_prerequisites_leave_intervention_totals_undetermined(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases, path = prepare_fixture(root)
            plan = study.make_plan(cases, path, mock=True)
            empty = dict(predictions=[], explanations=[], interventions=[])
            with patch.object(study, "read_snapshot", return_value=(None, empty)):
                summary = study.summarize(root / "out", cases, plan)
            self.assertFalse(summary["automated_execution_complete"])
            self.assertFalse(summary["full_study_complete"])
            for row in summary["rows"]:
                if "explanation_tests" in row["stage"] or "systematic" in row["stage"]:
                    self.assertIsNone(row["planned_measurements"])
                    self.assertIsNone(row["missing_measurements"])
                    self.assertEqual(row["prerequisite_missing_cases"], row["planned"])
                    self.assertEqual(row["completed"], 0)

    def test_freeze_requires_finished_validation_and_explicit_review_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, path = prepare_fixture(root)
            out, control = root / "out", root / "control"
            command = ["freeze", "--mock", "--cases", str(path), "--out", str(out), "--control", str(control)]
            incomplete = {"rows": [dict(phase="validation", missing=1)]}
            with patch.object(study, "summarize", return_value=incomplete):
                with self.assertRaisesRegex(ValueError, "Validation stages are incomplete"):
                    study.main(command)
            self.assertFalse((control / "protocol_frozen.json").exists())
            finished = {"rows": [dict(phase="validation", missing=0)]}
            with patch.object(study, "summarize", return_value=finished):
                with self.assertRaisesRegex(ValueError, "ack-validation-review"):
                    study.main(command)
            self.assertFalse((control / "protocol_frozen.json").exists())
            with patch.object(study, "summarize", return_value=finished), \
                    patch.object(study, "checkpoint", return_value={"fixture_integrity": "fixed"}), \
                    patch.object(study, "report") as report:
                study.main(command + ["--ack-validation-review", "--review-note", "Fixture validation inspected"])
            checkpoint = json.loads((control / "protocol_frozen.json").read_text())
            self.assertEqual(checkpoint["review_note"], "Fixture validation inspected")
            self.assertEqual(checkpoint["integrity"], {"fixture_integrity": "fixed"})
            report.assert_called_once()

    def test_changed_plan_and_frozen_integrity_refuse_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases, path = prepare_fixture(root)
            out, control = root / "out", root / "control"
            control.mkdir()
            plan = study.make_plan(cases, path, mock=True)
            plan_path = control / "study_plan.json"
            study.ensure_plan(plan_path, plan)
            changed = copy.deepcopy(plan)
            changed["integrity"]["shared_helpers_sha256"] = "changed"
            with self.assertRaisesRegex(ValueError, "Plan/data/code changed"):
                study.ensure_plan(plan_path, changed)
            self.assertEqual(json.loads(plan_path.read_text()), plan)
            (control / "protocol_frozen.json").write_text(json.dumps({"integrity": {"fixed": "old"}}))
            with patch.object(study, "checkpoint", return_value={"fixed": "new"}), \
                    patch.object(study, "run_stage") as run_stage:
                with self.assertRaisesRegex(ValueError, "Frozen data/model/code/plan changed"):
                    study.main(["test", "--mock", "--cases", str(path), "--out", str(out), "--control", str(control)])
            run_stage.assert_not_called()

    def test_zero_subprocess_exit_cannot_pass_missing_saved_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases, path = prepare_fixture(root)
            control = root / "control"
            control.mkdir()
            plan = study.make_plan(cases, path, mock=True)
            stage = plan["stages"][0]
            args = SimpleNamespace(cases=path, case_rows=cases, control=control, timeout=1, mock=True)
            process = SimpleNamespace(stdout=iter(["fixture subprocess exited successfully\n"]), wait=lambda: 0)
            summary = {"rows": [dict(stage=stage["name"], missing=1)]}
            with patch.object(study.subprocess, "Popen", return_value=process), \
                    patch.object(study, "summarize", return_value=summary), \
                    patch.object(study, "write_summary") as write_summary:
                with self.assertRaisesRegex(ValueError, "saved stage coverage is incomplete"):
                    study.run_stage(stage, args, root / "out", plan, control / "study_plan.json")
            events = read_jsonl(control / "stage_events.jsonl")
            self.assertEqual([r["event"] for r in events], ["start", "failed"])
            self.assertEqual(events[-1]["returncode"], 0)
            write_summary.assert_not_called()

    def test_forty_hash_bound_reviews_are_required_after_automated_attempts_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases, path = prepare_fixture(root)
            plan = study.make_plan(cases, path, mock=True)
            data = complete_synthetic_snapshot(cases, plan)
            out = root / "out"
            out.mkdir()
            write_audit(out / "manual_audit.csv", audit_rows(data))
            with patch.object(study, "read_snapshot", return_value=(None, data)):
                summary = study.summarize(out, cases, plan)
            self.assertTrue(summary["automated_execution_complete"])
            self.assertFalse(summary["full_study_complete"])
            self.assertEqual(summary["manual_grounding"]["planned"], 40)
            self.assertEqual(summary["manual_grounding"]["reviewed"], 0)
            study.review_sample(out, data, plan)
            sample_path = out / "manual_review_sample.csv"
            sample = read_audit(sample_path)
            self.assertEqual(len(sample), 40)
            self.assertTrue(all(not r["supported_claims"] and not r["total_factual_claims"] for r in sample))
            sample[0].update(supported_claims="2", total_factual_claims="3")
            write_audit(sample_path, sample)
            study.review_sample(out, data, plan)
            self.assertEqual(study.audit_state(out, data, plan)["reviewed"], 1)
            self.assertFalse(study.audit_state(out, data, plan)["complete"])
            for row in sample[1:]:
                row.update(supported_claims="1", total_factual_claims="1")
            write_audit(sample_path, sample)
            study.review_sample(out, data, plan)
            with patch.object(study, "read_snapshot", return_value=(None, data)):
                summary = study.summarize(out, cases, plan)
            self.assertEqual(summary["manual_grounding"]["reviewed"], 40)
            self.assertTrue(summary["full_study_complete"])
            self.assertGreater(sum(r["invalid"] for r in summary["rows"]), 0,
                "Accounted-for invalid attempts are not silently treated as passing explanations.")

    def test_review_sample_rejects_stale_duplicate_and_partial_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases, path = prepare_fixture(root)
            plan = study.make_plan(cases, path, mock=True)
            data = complete_synthetic_snapshot(cases, plan)
            out = root / "out"
            out.mkdir()
            rows = audit_rows(data)
            write_audit(out / "manual_audit.csv", rows)
            sample = out / "manual_review_sample.csv"
            stale = copy.deepcopy(rows)
            stale[0]["explanation_hash"] = "stale-source-hash"
            write_audit(sample, stale)
            with self.assertRaisesRegex(ValueError, "stale, duplicate or unplanned"):
                study.review_sample(out, data, plan)
            write_audit(sample, rows + [rows[0]])
            with self.assertRaisesRegex(ValueError, "stale, duplicate or unplanned"):
                study.review_sample(out, data, plan)
            partial = copy.deepcopy(rows)
            partial[0]["supported_claims"] = "1"
            write_audit(sample, partial)
            with self.assertRaisesRegex(ValueError, "Complete both review counts"):
                study.review_sample(out, data, plan)
            self.assertEqual(study.audit_state(out, data, plan)["reviewed"], 0)


if __name__ == "__main__":
    unittest.main()
