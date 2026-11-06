"""Readable displays for the bounded development pilot; these functions never infer."""
import json
from html import escape

from .development_pilot import generate_observations, model_inputs, identity_presentation
from .explanation_annotation import concept_summary


def product_label(pilot, case_id, product_id):
    source = next(e["original_source"] for e in pilot.manifest["entries"] if e["case_id"] == case_id)
    names = {c["id"]: c["name"] for c in source["candidates"]}
    return f"{names[product_id]} [product {product_id}]" if product_id in names else "INVALID / NOT_PROVIDED"


def details(title, value):
    from IPython.display import display, HTML
    text = value if isinstance(value, str) else json.dumps(value, indent=2, ensure_ascii=False)
    display(HTML("<details><summary>" + escape(title) + "</summary><pre>" + escape(text) + "</pre></details>"))


def table(rows):
    import pandas as pd
    from IPython.display import display
    with pd.option_context("display.max_colwidth", None, "display.max_columns", None):
        display(pd.DataFrame(rows))


def show_cases(pilot):
    print("Selected development cases (seed", pilot.manifest["seed"], ")")
    table(pilot.manifest["selected_cases"])
    for entry in pilot.manifest["entries"]:
        if entry["family"] == "ORIGINAL":
            print("\n", entry["case_id"], entry["condition"])
            print("Candidate mapping:", entry["observations"]["candidates"])
            print(entry["observations"]["text"])


def show_manifest(pilot):
    print("Manifest saved BEFORE inference:", pilot.out / "manifest.json")
    print("Protocol:", pilot.manifest["protocol_version"], "| seed:", pilot.manifest["seed"])
    print("Planned calls and hard caps:", pilot.manifest["budgets"])
    print("Positive development price bounds (cents):", pilot.manifest["development_price_bounds_cents"])
    registry = {r["family_id"]: r for r in pilot.manifest["registry"]}
    table([{"case": e["case_id"], "condition": e["condition"], "family": e["family"],
            "exact planned edit": e.get("patch", []), "skip": e["skip_reason"],
            "fixed": registry.get(e["family"], {}).get("must_remain_fixed", "All source fields and presentation")}
           for e in pilot.manifest["entries"]])
    details("Full family registry, including rules, applicability and regeneration", pilot.manifest["registry"])
    print("Annotation targets:", pilot.manifest["annotation_call_ids"])


def annotation_rows(record):
    result = (record or {}).get("result")
    if not result: return []
    parsed = result["parsed_annotations"]
    return parsed.get("claims", []) if isinstance(parsed, dict) and isinstance(parsed.get("claims"), list) else []


def show_originals(pilot):
    responses, annotations = pilot.responses(), pilot.annotations()
    for entry in pilot.manifest["entries"]:
        if entry["family"] != "ORIGINAL": continue
        record = responses.get(entry["call_id"])
        print("\nORIGINAL", entry["case_id"], entry["condition"])
        if not record:
            print("Not yet generated"); continue
        response = record["response"]
        print("Decoded predicted product:", product_label(pilot, entry["case_id"], record["decoded_product_id"]))
        print("EXACT RAW RESPONSE (repr):", repr(response["raw_response"]))
        print("Diagnostics:", response["diagnostics"])
        details("Exact predictor prompt for this saved response", response["messages"])
        review_path = pilot.out / "manual_review.json"
        if review_path.exists():
            review = json.loads(review_path.read_text()).get(entry["call_id"])
            if review: details("Manual factual spot-check (not complete claim annotation)", review)
        claims = annotation_rows(annotations.get(entry["call_id"]))
        if claims:
            print("Provisional annotation; semantic correctness and coverage require review")
            print("Annotation diagnostics:", annotations[entry["call_id"]]["result"]["diagnostics"])
            table(claims)
        else:
            print("Not yet annotated (or annotation unavailable); no claim-level assessment invented")


def show_edits(pilot, families):
    if isinstance(families, str): families = [families]
    responses, annotations = pilot.responses(), pilot.annotations()
    for entry in pilot.manifest["entries"]:
        if entry["family"] not in families: continue
        print("\n", entry["case_id"], entry["condition"], entry["family"])
        if entry["skip_reason"]:
            print("SKIPPED:", entry["skip_reason"]); continue
        print("EXACT SOURCE PATCH:", json.dumps(entry["patch"], ensure_ascii=False))
        print("Edit details:", entry["edit_details"])
        print("Internal relationships before/after:", entry["statistics_before"], entry["statistics_after"])
        before_obs = generate_observations(**model_inputs(entry["original_source"], identity_presentation(entry["original_source"])))
        details("Facts BEFORE edit", before_obs["text"])
        details("Regenerated facts AFTER edit", entry["observations"]["text"])
        original_id = f"{entry['case_id']}__{entry['condition']}__ORIGINAL"
        baseline, after = responses.get(original_id), responses.get(entry["call_id"])
        rows = []
        for name, record in (("original", baseline), ("edited", after)):
            response = record["response"] if record else {}
            parsed = response.get("parsed_result")
            rows.append({"input": name, "decoded product": product_label(pilot, entry["case_id"], record["decoded_product_id"]) if record else None,
                         "exact explanation": parsed.get("explanation") if isinstance(parsed, dict) else None,
                         "generation status": "measured" if record else "not yet measured"})
            if record:
                details(name + " exact raw response and diagnostics", {"raw_response": response["raw_response"], "diagnostics": response["diagnostics"]})
        table(rows)
        review_path = pilot.out / "manual_review.json"
        if review_path.exists():
            review = json.loads(review_path.read_text()).get(entry["call_id"])
            if review: details("Manual factual spot-check (not complete claim annotation)", review)
        if entry["call_id"] in annotations and original_id in annotations:
            print("Provisional annotation comparison (not a faithfulness verdict)")
            for label, cid in (("original", original_id), ("edited", entry["call_id"])):
                print(label)
                result = annotations[cid].get("result")
                if result:
                    print("Annotation diagnostics:", result["diagnostics"])
                    table(concept_summary(result))
                table(annotation_rows(annotations[cid]))
        else:
            print("Edited response not yet annotated; exact explanations are shown without invented claim labels")


def show_annotations(pilot):
    annotations = pilot.annotations()
    for cid in pilot.manifest["annotation_call_ids"]:
        print("\nANNOTATION", cid)
        record = annotations.get(cid)
        if not record:
            print("Not yet annotated"); continue
        if record.get("skip_reason"):
            print("SKIPPED:", record["skip_reason"]); continue
        result = record["result"]
        print("Provisional LLM-assisted annotations requiring review; same predictor/annotator model:", result["predictor_and_annotator_same_model"])
        table(annotation_rows(record))
        table(concept_summary(result))
        details("Exact annotation response and mapping diagnostics", {"raw": result["raw_annotation_response"], "diagnostics": result["diagnostics"]})
        review_path = pilot.out / "annotation_review.json"
        if review_path.exists():
            review = json.loads(review_path.read_text()).get(cid)
            if review: details("Limited manual review of this annotation", review)


def show_results(pilot):
    report = pilot.save_report()
    annotations = pilot.annotations()
    print("Actual execution counts:", report["status"])
    display_rows = []
    for row in report["results"]:
        values = {key: row[key] for key in ("case", "condition", "family", "exact_edit", "skip_reason", "original_product", "edited_product",
                                           "product_changed", "observed_factual_contradiction", "annotation_status", "manual_factual_review", "reason_change")}
        values["original_product"] = product_label(pilot, row["case"], row["original_product"])
        values["edited_product"] = product_label(pilot, row["case"], row["edited_product"]) if row["measured"] else "SKIPPED / NOT_MEASURED"
        cid = f"{row['case']}__{row['condition']}__{row['family']}"
        annotation = annotations.get(cid, {}).get("result")
        if annotation:
            passed = annotation["diagnostics"]["structure_and_traceability_ok"]
            values["annotation_status"] = "Provisional; structure/traceability " + ("passed" if passed else "FAILED") + "; semantic/coverage review required"
        manual = row["manual_factual_review"]
        if isinstance(manual, dict):
            flags = [c for c in manual.get("checks", []) if c.get("factual_status") in
                     ("contradicted", "unsupported_by_supplied_information")]
            values["observed_factual_contradiction"] = {"limited_manual_flags": flags,
                "provisional_annotation_flags": row["observed_factual_contradiction"] if isinstance(row["observed_factual_contradiction"], list) else []}
            if manual.get("claimed_rule_spot_check"):
                values["reason_change"] = manual["claimed_rule_spot_check"]
        if row["original_explanation"] is not None and row["edited_explanation"] is not None:
            values["explanation text changed"] = row["original_explanation"] != row["edited_explanation"]
        display_rows.append(values)
    table(display_rows)
    measured = [r for r in report["results"] if r["measured"] and r["product_changed"] is not None]
    from collections import Counter
    counts = Counter((r["family"], r["product_changed"]) for r in measured)
    print("Measured product changes by family (counts only):", dict(counts))
    print("Interpretation limits:")
    for limit in report["interpretation_limits"]: print("-", limit)
    print("For a claimed cheapest-brand rule, inspect the original exact claim and edited cheapest set before interpreting a changed/unchanged answer.")
    print("For a contributing reason, no single answer change is logically required. Inspect provisional roles, direction and factual labels side by side.")
    print("Remaining responses are not yet annotated; factual and rule-consistency review remains incomplete.")
