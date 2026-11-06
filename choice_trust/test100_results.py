"""Read-only views of saved test-with-history study records.

This module imports no model, generator, runner, or annotation code. Loading and
rendering results only read files; they never infer, retry, repair, or save data.
Target outcomes are used only for ORIGINAL accuracy, never edited-scenario accuracy.
"""
from collections import Counter
from dataclasses import dataclass, field
from html import escape
import json
from pathlib import Path

DEFAULT_DIRECTORY = Path("choice_study/test_with_history_100_v1")
FAMILIES = (
    "CURRENT_PRICE", "CURRENT_ADVERTISING", "SUPPORT_PURCHASE",
    "HISTORICAL_PRICE_ASSOCIATION", "HISTORICAL_ADVERTISING_ASSOCIATION",
    "HISTORICAL_OFFER_REMOVAL", "PRODUCT_ORDER_CONTROL", "ANSWER_MAPPING_CONTROL",
)
FINISHED = {"completed", "reused"}


def _read(path, errors, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        return default


@dataclass
class SavedStudy:
    directory: Path
    manifest: dict
    targets: dict
    records: dict
    items: dict
    load_errors: list = field(default_factory=list)

    @property
    def entries(self):
        return self.manifest.get("entries", [])

    @property
    def selected_cases(self):
        selected = self.manifest.get("selected_cases", [])
        if selected:
            return [row if isinstance(row, dict) else {"case_id": row} for row in selected]
        return [{"case_id": row["case_id"]} for row in self.entries if row.get("family") == "ORIGINAL"]

    def entry(self, call_id):
        return next((row for row in self.entries if row.get("call_id") == call_id), None)

    def names(self, case_id):
        entry = next((row for row in self.entries if row.get("case_id") == case_id), {})
        source = entry.get("original_source", {})
        return {row["id"]: row.get("name", row["id"]) for row in source.get("candidates", [])}

    def product(self, case_id, product_id):
        names = self.names(case_id)
        return f"{names[product_id]} [product {product_id}]" if product_id in names else ("NOT_ASSESSABLE" if product_id is None else f"UNKNOWN_PRODUCT({product_id})")

    def target(self, case_id):
        value = self.targets.get(case_id)
        if isinstance(value, dict):
            value = value.get("product_id", value.get("canonical_product_id", value.get("target")))
        return value if value in self.names(case_id) else None

    def status(self, entry):
        if entry.get("skip_reason"):
            return "not_applicable"
        item = self.items.get(entry["call_id"], {})
        if item.get("status"):
            return item["status"]
        record = self.records.get(entry["call_id"])
        if record:
            return "reused" if record.get("reuse_provenance") else "completed"
        return "pending"

    def usable_prediction(self, entry):
        """Assess prediction parsing/identity; citation correctness is a separate axis."""
        record = self.records.get(entry["call_id"])
        if not record or self.status(entry) not in FINISHED:
            return False
        response = record.get("response", {})
        diagnostics = response.get("diagnostics", {})
        parsed = response.get("parsed_result")
        return (isinstance(parsed, dict)
                and diagnostics.get("parse_ok") is True
                and diagnostics.get("prediction_valid") is True
                and record.get("decoded_product_id") in self.names(entry["case_id"]))


def load_saved_results(directory=DEFAULT_DIRECTORY):
    """Read a fresh local snapshot. Missing directories are a pending snapshot."""
    directory = Path(directory)
    errors = []
    manifest = _read(directory / "manifest.json", errors, {}) or {}
    targets = _read(directory / "evaluation_targets.json", errors, {}) or {}
    if isinstance(targets.get("targets"), dict):
        targets = targets["targets"]
    records, items = {}, {}
    for entry in manifest.get("entries", []):
        cid = entry["call_id"]
        record = _read(directory / "responses" / f"{cid}.json", errors)
        item = _read(directory / "items" / f"{cid}.json", errors)
        if isinstance(record, dict):
            records[cid] = record
        if isinstance(item, dict):
            items[cid] = item
    return SavedStudy(directory, manifest, targets, records, items, errors)


def accuracy_summary(study):
    selected = {row["case_id"] for row in study.selected_cases}
    originals = [row for row in study.entries if row.get("family") == "ORIGINAL"]
    target_known = [row for row in originals if study.target(row["case_id"]) is not None]
    assessable = [row for row in target_known if study.usable_prediction(row)]
    correct = sum(study.records[row["call_id"]]["decoded_product_id"] == study.target(row["case_id"]) for row in assessable)
    return {
        "selected_cases": len(selected), "planned_originals": len(originals),
        "original_status_counts": dict(Counter(study.status(row) for row in originals)),
        "known_target_cases": len(target_known),
        "assessable_originals_with_known_target": len(assessable),
        "correct_originals": correct,
        "original_accuracy_among_assessable_known_targets": correct / len(assessable) if assessable else None,
        "observed_correct_fraction_of_all_selected": correct / len(selected) if selected else None,
        "unassessable_or_unresolved_selected": len(selected) - len(assessable),
        "missing_or_invalid_targets": len(originals) - len(target_known),
        "definition": "Assessable = completed/reused record with parsed JSON, valid prediction and decoded product identity, plus known original target. Citation validity reported separately. Observed correct/selected is incomplete-run coverage, not final accuracy.",
    }


def item_rows(study):
    rows = []
    originals = {row["case_id"]: row for row in study.entries if row.get("family") == "ORIGINAL"}
    for entry in study.entries:
        cid, case = entry["call_id"], entry["case_id"]
        record = study.records.get(cid, {})
        response = record.get("response", {})
        diagnostics = response.get("diagnostics", {})
        parsed = response.get("parsed_result")
        baseline = originals.get(case)
        original = study.records.get(baseline["call_id"], {}) if baseline else {}
        assessable = bool(baseline and study.usable_prediction(baseline) and study.usable_prediction(entry))
        item = study.items.get(cid, {})
        state = study.status(entry)
        consistency = []
        if state in FINISHED and not record:
            consistency.append("finished status has no readable response")
        if record and not item:
            consistency.append("response present; item status unavailable")
        if record and state not in FINISHED:
            consistency.append("response present with unresolved item status")
        rows.append({
            "call_id": cid, "case_id": case, "family": entry["family"],
            "status": state, "applicable": not bool(entry.get("skip_reason")),
            "skip_reason": entry.get("skip_reason"),
            "original_product_id": original.get("decoded_product_id"),
            "edited_product_id": record.get("decoded_product_id"),
            "original_product": study.product(case, original.get("decoded_product_id")),
            "response_product": study.product(case, record.get("decoded_product_id")),
            "comparison_assessable": assessable if entry["family"] != "ORIGINAL" else None,
            "product_changed": (original.get("decoded_product_id") != record.get("decoded_product_id")) if assessable and entry["family"] != "ORIGINAL" else None,
            "parse_ok": diagnostics.get("parse_ok"),
            "prediction_valid": diagnostics.get("prediction_valid"),
            "citations_valid": diagnostics.get("citations_valid"),
            "generation_truncated": diagnostics.get("generation_truncated"),
            "parse_error": diagnostics.get("parse_error"),
            "execution_error": item.get("error"),
            "consistency_warnings": consistency,
            "exact_patch": entry.get("patch", []),
            "exact_explanation": parsed.get("explanation") if isinstance(parsed, dict) else None,
            "review_status": "NOT_ANNOTATED; factual correctness, claimed influence and faithfulness UNREVIEWED",
        })
    return rows


def family_summary(study):
    all_rows = item_rows(study)
    rows = []
    for family in FAMILIES:
        planned = [row for row in all_rows if row["family"] == family]
        states = Counter(row["status"] for row in planned)
        applicable = [row for row in planned if row["applicable"]]
        measured = [row for row in applicable if row["comparison_assessable"]]
        changed = sum(row["product_changed"] is True for row in measured)
        finished_unassessable = sum(row["status"] in FINISHED and not row["comparison_assessable"] for row in applicable)
        rows.append({
            "family": family, "selected_cases": len(study.selected_cases),
            "planned_items": len(planned), "applicable": len(applicable),
            "not_applicable": states["not_applicable"],
            "completed": states["completed"], "reused": states["reused"],
            "pending": states["pending"], "failed": states["failed"],
            "uncertain": states["uncertain"] + states["execution_status_uncertain"],
            "other_unresolved_statuses": {key: value for key, value in states.items() if key not in FINISHED | {"pending", "failed", "uncertain", "execution_status_uncertain", "not_applicable"}},
            "assessable_original_edit_pairs": len(measured),
            "changed_products": changed,
            "changed_fraction_of_assessable_pairs": changed / len(measured) if measured else None,
            "finished_but_unassessable_pairs": finished_unassessable,
            "all_unassessable_or_unresolved_pairs": len(applicable) - len(measured),
            "skip_reasons": dict(Counter(row["skip_reason"] for row in planned if row["skip_reason"])),
        })
    return rows


def diagnostics_summary(study):
    rows = item_rows(study)
    saved = [row for row in rows if row["call_id"] in study.records]
    def count(field, value):
        return sum(row[field] is value for row in saved)
    status_counts = dict(Counter(row["status"] for row in rows))
    unresolved = sum(value for key, value in status_counts.items() if key not in FINISHED | {"not_applicable"})
    return {
        "planned_items": len(rows), "saved_response_records": len(saved),
        "status_counts": status_counts, "required_unresolved_items": unresolved,
        "study_complete": bool(rows) and unresolved == 0 and not study.load_errors and all(row["status"] not in FINISHED or row["call_id"] in study.records for row in rows),
        "parse_ok": count("parse_ok", True), "parse_failed": count("parse_ok", False),
        "parse_status_unavailable": count("parse_ok", None),
        "invalid_predictions": count("prediction_valid", False),
        "invalid_citations": count("citations_valid", False),
        "truncated_responses": count("generation_truncated", True),
        "record_state_consistency_warnings": sum(bool(row["consistency_warnings"]) for row in rows),
        "load_errors": study.load_errors,
        "annotation_status": "No bulk annotations launched; saved explanations are unannotated and unreviewed. Pilot annotations are not reliable labels for this stage.",
    }


def _table(rows):
    from IPython.display import display
    import pandas as pd
    with pd.option_context("display.max_columns", None, "display.max_colwidth", 120):
        display(pd.DataFrame(rows))


def _details(title, value):
    from IPython.display import HTML, display
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    display(HTML(f"<details><summary>{escape(title)}</summary><pre>{escape(text)}</pre></details>"))


def show_overview(study):
    print("READ-ONLY LOCAL SNAPSHOT:", study.directory.resolve())
    if not study.manifest:
        print("Manifest not available locally. No inference or synchronization was attempted.")
        if study.load_errors:
            _details("Read errors", study.load_errors)
        return
    print("Frozen plan:", study.manifest.get("plan_id", "NOT_PROVIDED"), "| protocol:", study.manifest.get("protocol_version", "NOT_PROVIDED"))
    accuracy = accuracy_summary(study)
    print("Original accuracy among assessable known-target predictions:", f"{accuracy['correct_originals']}/{accuracy['assessable_originals_with_known_target']}")
    print("Observed correct original predictions / ALL selected cases:", f"{accuracy['correct_originals']}/{accuracy['selected_cases']}", "(coverage-sensitive until all originals resolve)")
    _table([accuracy])
    _details("Execution, parsing and review status", diagnostics_summary(study))
    print("No edited-scenario customer accuracy is calculated: edited target purchases are unknown.")


def show_families(study):
    _table(family_summary(study))
    print("Change-rate denominator = assessable original/edited product-identity pairs, after answer remapping. Pending, failed, uncertain and finished-but-unassessable pairs are excluded and counted separately.")


def show_items(study):
    keys = ("case_id", "family", "status", "skip_reason", "original_product", "response_product", "product_changed", "parse_ok", "prediction_valid", "citations_valid", "generation_truncated", "execution_error", "consistency_warnings", "review_status")
    _table([{key: row[key] for key in keys} for row in item_rows(study)])


def show_examples(study, limit=4):
    """Show first measured pairs in manifest order, cycling through families.

    Deterministic availability selection only, never selected by correctness,
    prediction change, or explanation quality. These are examples, not annotations.
    """
    rows = item_rows(study)
    chosen = []
    for family in FAMILIES:
        row = next((row for row in rows if row["family"] == family and row["call_id"] in study.records and row["original_product_id"] is not None), None)
        if row:
            chosen.append(row)
        if len(chosen) >= limit:
            break
    if not chosen:
        print("No saved original/edited example pair available in this local snapshot.")
        return
    originals = {entry["case_id"]: entry for entry in study.entries if entry["family"] == "ORIGINAL"}
    print("Examples: first available saved pair per family, in fixed family order; no outcome-based selection.")
    for row in chosen:
        entry = study.entry(row["call_id"])
        baseline = originals[row["case_id"]]
        before = study.records.get(baseline["call_id"], {})
        after = study.records[row["call_id"]]
        print("\n", row["case_id"], row["family"], "|", row["original_product"], "→", row["response_product"])
        print("EXACT SOURCE PATCH:", json.dumps(row["exact_patch"], ensure_ascii=False))
        _table([{"input": label, "decoded_product": study.product(row["case_id"], record.get("decoded_product_id")),
                 "exact_explanation": record.get("response", {}).get("parsed_result", {}).get("explanation") if isinstance(record.get("response", {}).get("parsed_result"), dict) else None,
                 "review_status": "NOT_ANNOTATED / UNREVIEWED"} for label, record in (("original", before), ("edited", after))])
        for label, source, record in (("original", baseline, before), ("edited", entry, after)):
            response = record.get("response", {})
            _details(label + " complete facts, exact raw response, citations, prompt and diagnostics", {
                "facts": source.get("observations", {}).get("text"),
                "raw_response": response.get("raw_response"),
                "parsed_result": response.get("parsed_result"),
                "messages": response.get("messages"),
                "diagnostics": response.get("diagnostics"),
                "generation_metadata": response.get("generation_metadata"),
                "reuse_provenance": record.get("reuse_provenance"),
            })
    print("Factual mistakes and incorrect predictions are retained. No claimed-influence, factual-label or faithfulness assessment has been inferred from these text differences.")
