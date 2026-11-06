#!/usr/bin/env python3
"""Plan, run, inspect or resume only the bounded development counterfactual pilot."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from choice_trust.pilot_execution import Pilot, load_runtime, DEFAULT_OUT
from choice_trust.development_pilot import digest, verify_edit

STAGES = {
    "originals": ["ORIGINAL"], "sanity": ["UNCHANGED_RERUN"],
    "prices": ["CURRENT_PRICE"], "current_ads": ["CURRENT_ADVERTISING"],
    "support_purchase": ["SUPPORT_PURCHASE"], "historical_prices": ["HISTORICAL_PRICE_ASSOCIATION"],
    "historical_ads": ["HISTORICAL_ADVERTISING_ASSOCIATION"], "offer_removal": ["HISTORICAL_OFFER_REMOVAL"],
    "presentation": ["PRODUCT_ORDER_CONTROL", "ANSWER_MAPPING_CONTROL"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["plan", "status", *STAGES, "annotations", "report", "all"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    pilot = Pilot.prepare(args.out, seed=args.seed)
    if args.stage in ("plan", "status"):
        print(json.dumps({"selected_cases": pilot.manifest["selected_cases"], "status": pilot.status()}, indent=2)); return
    if args.stage == "report":
        print(json.dumps(pilot.save_report()["status"], indent=2)); return
    status = pilot.status()
    if (args.stage == "all" and status["completed_generation_records"] == status["planned"]["planned_generations"]
            and status["annotation_records"] == status["planned"]["planned_annotations"]):
        # Verify the completed cache against its saved runtime without loading weights.
        fingerprint = json.loads((pilot.out / "runtime.json").read_text())
        responses = pilot.responses()
        for entry in pilot.manifest["entries"]:
            if entry["skip_reason"]: continue
            verify_edit(entry, pilot.manifest["development_price_bounds_cents"])
            record = responses[entry["call_id"]]
            expected = digest({"entry": entry, "runtime": fingerprint,
                               "rendered_prompt": record["response"]["rendered_prompt"], "plan_id": pilot.manifest["plan_id"]})
            if record["input_signature"] != expected or record["response"]["messages"] != entry["messages"]:
                raise ValueError("Completed response does not match its full planned input/runtime")
        for cid, record in pilot.annotations().items():
            expected = digest({"original_response": responses[cid], "inputs": pilot.annotation_example(responses[cid]),
                               "guide": pilot.manifest["annotation_guide"], "runtime": fingerprint})
            if record["annotation_signature"] != expected: raise ValueError("Completed annotation signature mismatch")
        with pilot.writer():
            for cid, record in responses.items():
                pilot.event(event="reused", kind="generation", call_id=cid,
                            source=str(pilot.out / "responses" / (cid + ".json")),
                            signature=record["input_signature"], mode="completed_plan_verification")
            for cid, record in pilot.annotations().items():
                pilot.event(event="reused", kind="annotation", call_id=cid,
                            source=str(pilot.out / "annotations" / (cid + ".json")),
                            signature=record["annotation_signature"], mode="completed_plan_verification")
        print("All planned records are complete and signature-verified; no model loaded and no calls repeated.")
        print(json.dumps(pilot.save_report()["status"], indent=2)); return
    print("Saved pre-inference manifest:", pilot.out / "manifest.json", flush=True)
    print(json.dumps(pilot.manifest["budgets"]), flush=True)
    pilot.attach(load_runtime())
    stages = [*STAGES, "annotations"] if args.stage == "all" else [args.stage]
    for stage in stages:
        if stage == "annotations": pilot.run_annotations()
        else: pilot.run(STAGES[stage])
        pilot.save_report()
        print(stage, json.dumps(pilot.status()), flush=True)


if __name__ == "__main__": main()
