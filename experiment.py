"""Choice prediction and behavioral faithfulness study. No GPU is needed here.

Use --mock only for a synthetic plumbing check. Mock results are not LLM results.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LABELS = ("A", "B", "C", "D")
PROMPT_VERSION = "yogurt-evidence-v2-unlimited-citations"
ROOT = Path(__file__).resolve().parent


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_jsonl(path: Path, repair_tail: bool = False) -> list[dict]:
    """Recover only an incomplete last line; never conceal corruption in the middle."""
    if not path.exists():
        return []
    data = path.read_bytes()
    lines = data.splitlines(keepends=True)
    records, offset = [], 0
    for i, raw in enumerate(lines):
        try:
            if raw.strip():
                records.append(json.loads(raw))
        except (json.JSONDecodeError, UnicodeDecodeError):
            if repair_tail and i == len(lines) - 1 and not raw.endswith(b"\n"):
                with path.open("r+b") as handle:
                    handle.truncate(offset)
                print(f"Recovered incomplete last record in {path}.", file=sys.stderr)
                break
            raise ValueError(f"Invalid JSON in {path} at line {i + 1}; inspect it before continuing.")
        offset += len(raw)
    else:
        if repair_tail and data and not data.endswith(b"\n"):
            with path.open("ab") as handle:
                handle.write(b"\n")
    return records


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_env(path: Path) -> None:
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


class RemoteBackend:
    def __init__(self) -> None:
        load_env(ROOT / ".env")
        self.base = os.environ.get("MODEL_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
        self.key = os.environ.get("MODEL_API_KEY", "")
        self.timeout = float(os.environ.get("MODEL_TIMEOUT_SECONDS", "180"))
        if not self.key or self.key.startswith("replace-"):
            raise ValueError("Set MODEL_API_KEY in .env to the research server key you generated on AWS.")
        self.health = self.request("/health")
        self.metadata = {
            "backend": "real_llm", "model_id": self.health.get("model_id"),
            "revision": self.health.get("revision"), "server_health": self.health,
        }

    def request(self, route: str, payload: dict | None = None) -> dict:
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(self.base + route, data=body, headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
        })
        for attempt in range(3):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except HTTPError as exc:
                message = exc.read().decode(errors="replace")[:1000]
                if exc.code < 500 or attempt == 2:
                    raise RuntimeError(f"Server HTTP {exc.code}: {message}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt == 2:
                    raise RuntimeError("Cannot reach model. Check server, SSH tunnel, .env, and timeout.") from exc
            time.sleep(2 ** attempt)
        raise RuntimeError("Request failed")

    def score(self, prompt: str, **_: Any) -> dict:
        result = self.request("/score", {"prompt": prompt})
        validate_probabilities(result["probabilities"])
        self.check_identity(result)
        return result

    def explain(self, prompt: str, **_: Any) -> dict:
        result = self.request("/explain", {"prompt": prompt})
        self.check_identity(result)
        return result

    def check_identity(self, result: dict) -> None:
        for key in ("model_id", "revision"):
            if result.get(key) != self.metadata.get(key):
                raise RuntimeError(f"Server {key} changed during the run; use a new output folder.")


def validate_probabilities(probs: dict) -> None:
    values = [float(probs[label]) for label in LABELS]
    if any(not math.isfinite(x) or x < 0 or x > 1 for x in values) or abs(sum(values) - 1) > 1e-5:
        raise ValueError("Server returned invalid four-choice probabilities.")


class MockBackend:
    """Deterministic fake decision rule, used only to check the pipeline."""
    metadata = {"backend": "mock_NOT_LLM_RESULTS", "model_id": "mock", "revision": "mock-v1"}

    def score(self, prompt: str, *, case: dict, condition: str, keep: set | None = None,
              omit: set | None = None, **_: Any) -> dict:
        facts = evidence(case, condition)
        visible = set(facts) if keep is None else set(keep)
        visible -= omit or set()
        utilities = {label: 0.0 for label in LABELS}
        for label in LABELS:
            if "P_" + label in visible:
                utilities[label] -= .35 * case["query"]["prices"][label]
            if "F_" + label in visible:
                utilities[label] += .5 * int(case["query"]["ads"][label])
        if condition == "with_history":
            for example in case["support"]:
                if example["evidence_id"] in visible:
                    utilities[example["choice"]] += .7
        maximum = max(utilities.values())
        exp = {label: math.exp(utilities[label] - maximum) for label in LABELS}
        probs = {label: exp[label] / sum(exp.values()) for label in LABELS}
        return {"probabilities": probs, "prediction": max(probs, key=probs.get), **self.metadata}

    def explain(self, prompt: str, *, case: dict, condition: str, prediction: str, **_: Any) -> dict:
        ids = ["P_" + prediction, "F_" + prediction]
        if condition == "with_history":
            matching = [x["evidence_id"] for x in case["support"] if x["choice"] == prediction]
            ids += (matching or ["H1"])[:1]
        answer = {"evidence_ids": ids,
                  "explanation": "SYNTHETIC MOCK: the artificial rule uses visible prices, ads and observed examples.",
                  "counterfactual": {"evidence_id": "P_" + prediction, "change": "increase",
                                     "expected_effect_on_chosen_probability": "decrease"}}
        return {"text": json.dumps(answer), "finish_reason": "stop", **self.metadata}


def evidence(case: dict, condition: str) -> dict[str, dict]:
    facts = {}
    for label in LABELS:
        facts["P_" + label] = {"role": "price", "text": f"Current price of {label}: {case['query']['prices'][label]:g} (dataset units)."}
        facts["F_" + label] = {"role": "ad", "text": f"Newspaper advertisement for {label}: {int(case['query']['ads'][label])} (1=yes, 0=no)."}
    if condition == "with_history":
        for example in case["support"]:
            description = {"prices": example["prices"], "advertised": example["ads"], "purchased": example["choice"]}
            facts[example["evidence_id"]] = {"role": "history", "text": "Other observed purchase example: " + json.dumps(description, sort_keys=True)}
    return facts


def prediction_prompt(case: dict, condition: str, *, keep: set | None = None,
                      omit: set | None = None, order: list | None = None) -> str:
    """Never read case['target'] here. All candidates remain in every intervention."""
    facts = evidence(case, condition)
    visible = set(facts) if keep is None else set(keep)
    visible -= omit or set()
    order = order or list(LABELS)
    lines = [
        "Predict one household's yogurt brand choice on a held-out purchase occasion.",
        "Use only the supplied evidence. All four products are available; select exactly one.",
        "Examples are observed purchases, NOT a verified chronological history.",
        "Price numbers use the original dataset units. Advertisement means recorded newspaper feature status.",
        "Do not assume nutrition, taste, income, budget, demographics, or personal motives.",
        "NOT_PROVIDED means information was withheld, not zero or false.",
        "Product identities (these are labels, not a ranking):",
    ]
    lines += [f"{label}: {case['brand_map'][label]}" for label in order]
    lines.append("Evidence:")
    ids = [prefix + label for label in order for prefix in ("P_", "F_")]
    ids += [i for i in facts if i.startswith("H")]
    for fact_id in ids:
        lines.append(f"[{fact_id}] " + (facts[fact_id]["text"] if fact_id in visible else "NOT_PROVIDED"))
    lines.append("Answer with exactly one uppercase letter: A, B, C, or D. Do not explain.\nAnswer:")
    return "\n".join(lines)


def explanation_prompt(case: dict, condition: str, prediction: str, runner: str) -> str:
    full = prediction_prompt(case, condition)
    return full.rsplit("Answer with exactly", 1)[0] + f"""
The prediction already made was {prediction}; its strongest alternative was {runner}.
Explain that model prediction, rather than predicting again. Do not claim to know the customer's true motives.
Identify any number of distinct available evidence IDs from the supplied input that support this preference.
There is no citation-count limit. Do not duplicate IDs.
If no evidence can be defended, use an empty evidence_ids array and explain the uncertainty.
For comparisons cite both compared values when needed. Do not invent any information.
If the evidence is weak, explicitly say so. Do not reveal or guess an observed ground-truth outcome.
Return only one JSON object with this schema:
{{"evidence_ids":["P_A","P_D","H1"],"explanation":"short explanation with limitations",
"counterfactual":{{"evidence_id":"P_A","change":"increase","expected_effect_on_chosen_probability":"decrease"}}}}
The evidence_ids above are examples, not instructions to select those IDs.
counterfactual may be null. Otherwise choose ONE cited current-price ID with increase/decrease,
or ONE cited current-advertisement ID with toggle. Price edits are +/-20 percent, ads flip 0/1.
State whether that edit should increase or decrease the probability of the ORIGINAL selected product {prediction}.
"""


def parse_explanation(text: str, valid_ids: set) -> tuple[dict | None, str | None]:
    from choice_trust.citations import assess_response
    assessment = assess_response(text, valid_ids)
    if (not assessment['json_readable'] or not assessment['required_fields_present']
            or assessment['field_errors'] or not assessment['cited_ids_exist']
            or not assessment['citations_unique']):
        return None, '; '.join(assessment['issues'])
    return assessment['parsed'], None


def choose_cases(cases: list[dict], split: str, limit: int) -> list[dict]:
    selected = [c for c in cases if split == "all" or c["split"] == split]
    selected.sort(key=lambda c: digest([42, c["case_id"]]))
    return selected[:limit] if limit else selected


def setup(args: argparse.Namespace) -> tuple[list[dict], Any, Path]:
    case_path = Path(args.cases)
    cases = read_jsonl(case_path)
    if not cases:
        raise ValueError("No cases. Run prepare_data.py, or make_demo_data.py for the synthetic check.")
    synthetic = any(c.get("synthetic", False) for c in cases)
    if args.mock and not synthetic:
        raise ValueError("--mock requires synthetic cases from make_demo_data.py; do not generate fake LLM results on real data.")
    if not args.mock and synthetic:
        raise ValueError("Use real prepared data with the real model; synthetic demo data belong to --mock mode.")
    backend = MockBackend() if args.mock else RemoteBackend()
    out = Path(args.out or ("outputs_demo" if args.mock else "outputs"))
    out.mkdir(parents=True, exist_ok=True)
    identity = {"prompt_version": PROMPT_VERSION, "case_file_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
                "backend": backend.metadata["backend"], "model_id": backend.metadata["model_id"],
                "revision": backend.metadata["revision"], "synthetic_data": synthetic,
                "server_settings": backend.metadata.get("server_health", {}),
                "experiment_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    manifest = out / "run_manifest.json"
    if manifest.exists() and json.loads(manifest.read_text()) != identity:
        raise ValueError("Output folder belongs to different data/code/model. Choose a new --out folder.")
    manifest.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    return cases, backend, out


def predict(args: argparse.Namespace) -> None:
    cases, backend, out = setup(args)
    path = out / "predictions.jsonl"
    previous = {(r["case_id"], r["condition"]) for r in read_jsonl(path, True)}
    selected = choose_cases(cases, args.split, args.limit)
    done = 0
    for case in selected:
        for condition in args.conditions:
            if (case["case_id"], condition) in previous:
                continue
            prompt = prediction_prompt(case, condition)
            result = backend.score(prompt, case=case, condition=condition)
            probs = result["probabilities"]
            record = {"case_id": case["case_id"], "household_id": case["household_id"], "split": case["split"],
                      "condition": condition, "target": case["target"], "probabilities": probs,
                      "prediction": max(probs, key=probs.get), "prompt": prompt, "prompt_sha256": digest(prompt),
                      "raw_label_probability_mass": result.get("raw_label_probability_mass"), "metadata": backend.metadata}
            append_jsonl(path, record)
            done += 1
            print(f"Saved {case['case_id']} / {condition}", flush=True)
    print(f"Finished: {done} new predictions in {path}. Existing records were reused.")


def margin(probs: dict, chosen: str, runner: str) -> float:
    return math.log(max(probs[chosen], 1e-12)) - math.log(max(probs[runner], 1e-12))


def matched_random_sets(facts: dict, selected: list, count: int, seed: int) -> list[set]:
    rng = random.Random(seed)
    roles = {role: sum(facts[i]["role"] == role for i in selected) for role in {v["role"] for v in facts.values()}}
    result = []
    for _ in range(count):
        ids = set()
        for role, needed in sorted(roles.items()):
            pool = [i for i, v in facts.items() if v["role"] == role]
            ids.update(rng.sample(pool, needed))
        result.append(ids)
    return result


def counterfactual(case: dict, obj: dict) -> tuple[dict | None, str | None, str | None]:
    cf = obj.get("counterfactual")
    if not isinstance(cf, dict):
        return None, None, "No counterfactual claim."
    fact_id = cf.get("evidence_id", "")
    expected = cf.get("expected_effect_on_chosen_probability")
    if fact_id not in obj["evidence_ids"] or expected not in ("increase", "decrease"):
        return None, None, "Counterfactual must refer to a cited fact and specify increase/decrease."
    changed = copy.deepcopy(case)
    label = fact_id[2:]
    action = cf.get("change")
    if fact_id.startswith("P_") and label in LABELS and action in ("increase", "decrease"):
        changed["query"]["prices"][label] *= 1.2 if action == "increase" else .8
    elif fact_id.startswith("F_") and label in LABELS and action == "toggle":
        changed["query"]["ads"][label] = not changed["query"]["ads"][label]
    else:
        return None, None, "Only cited price +/-20% or advertisement toggle is supported."
    return changed, expected, None


def faithfulness(args: argparse.Namespace) -> None:
    cases, backend, out = setup(args)
    protocol = {"random_controls": args.random_controls, "citation_policy_version": "available-evidence-unlimited-v1", "max_evidence_ids": None,
                "price_edit_fraction": .2, "random_seed": 42}
    protocol_path = out / "faithfulness_protocol.json"
    if protocol_path.exists() and json.loads(protocol_path.read_text()) != protocol:
        raise ValueError("Faithfulness settings changed. Use a new --out folder and rerun predictions there.")
    protocol_path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    predictions = {(r["case_id"], r["condition"]): r for r in read_jsonl(out / "predictions.jsonl", True)}
    path = out / "faithfulness.jsonl"
    previous = {(r["case_id"], r["condition"]) for r in read_jsonl(path, True)}
    selected_cases = choose_cases(cases, args.split, args.limit)
    # Keep edits within observed dataset price support when testing numerical changes.
    all_prices = [float(p) for c in cases if c["split"] == "development" for p in c["query"]["prices"].values()]
    if not all_prices:
        raise ValueError("Development cases are needed to define the price-edit range.")
    lower, upper = min(all_prices), max(all_prices)
    for case in selected_cases:
        for condition in args.conditions:
            key = case["case_id"], condition
            if key in previous:
                continue
            if key not in predictions:
                raise ValueError(f"Missing prediction for {key}; run predict for this split/limit/condition first.")
            original = predictions[key]
            probs = original["probabilities"]
            chosen = original["prediction"]
            runner = sorted(LABELS, key=lambda label: probs[label], reverse=True)[1]
            p = probs[chosen]
            facts = evidence(case, condition)
            raw = backend.explain(explanation_prompt(case, condition, chosen, runner),
                                  case=case, condition=condition, prediction=chosen)
            obj, error = parse_explanation(raw["text"], set(facts))
            record = {"case_id": case["case_id"], "household_id": case["household_id"], "split": case["split"],
                      "condition": condition, "correct": chosen == case["target"], "target": case["target"],
                      "original_prediction": chosen, "original_probability": p, "runner_up": runner,
                      "parse_ok": obj is not None, "citation_valid": obj is not None, "parse_error": error,
                      "raw_explanation": raw["text"], "explanation_finish_reason": raw.get("finish_reason"),
                      "selected_ids": obj["evidence_ids"] if obj else [], "parsed_explanation": obj,
                      "provided_evidence": facts, "metadata": backend.metadata}
            record["abstained"] = obj is not None and not obj["evidence_ids"]
            from choice_trust.citations import assess_response
            record["citation_assessment"] = assess_response(raw["text"], facts, truncated=raw.get("finish_reason") == "length")
            record["prompt_version"] = PROMPT_VERSION
            if obj and obj["evidence_ids"]:
                ids = set(obj["evidence_ids"])
                removed = backend.score(prediction_prompt(case, condition, omit=ids), case=case, condition=condition, omit=ids)["probabilities"]
                kept = backend.score(prediction_prompt(case, condition, keep=ids), case=case, condition=condition, keep=ids)["probabilities"]
                original_margin = margin(probs, chosen, runner)
                comp = p - removed[chosen]
                suff = p - kept[chosen]
                control_rows = []
                for random_ids in matched_random_sets(facts, obj["evidence_ids"], args.random_controls, int(digest(key)[:8], 16)):
                    r = backend.score(prediction_prompt(case, condition, omit=random_ids), case=case, condition=condition, omit=random_ids)["probabilities"]
                    k = backend.score(prediction_prompt(case, condition, keep=random_ids), case=case, condition=condition, keep=random_ids)["probabilities"]
                    control_rows.append({"ids": sorted(random_ids), "comprehensiveness": p - r[chosen],
                                         "sufficiency_gap": p - k[chosen], "margin_drop": original_margin - margin(r, chosen, runner)})
                mean = lambda name: sum(x[name] for x in control_rows) / len(control_rows)
                order = list(LABELS)
                random.Random(int(digest([key, "order"])[:8], 16)).shuffle(order)
                if order == list(LABELS):
                    order = order[1:] + order[:1]
                reordered = backend.score(prediction_prompt(case, condition, order=order), case=case, condition=condition)["probabilities"]
                record.update({"comprehensiveness": comp, "sufficiency_gap": suff,
                               "keep_only_absolute_change": abs(suff),
                               "random_comprehensiveness_mean": mean("comprehensiveness"),
                               "random_sufficiency_gap_mean": mean("sufficiency_gap"),
                               "removal_advantage": comp - mean("comprehensiveness"),
                               "margin_drop": original_margin - margin(removed, chosen, runner),
                               "random_margin_drop_mean": mean("margin_drop"), "random_controls": control_rows,
                               "order_flip": max(reordered, key=reordered.get) != chosen,
                               "counterfactual_agreement": None, "counterfactual_probability_change": None})
                changed, expected, cf_error = counterfactual(case, obj)
                edit_id = (obj.get("counterfactual") or {}).get("evidence_id", "")
                if changed and edit_id.startswith("P_") and not lower <= float(changed["query"]["prices"][edit_id[2:]]) <= upper:
                    changed, cf_error = None, "Price edit outside the observed dataset range."
                if changed:
                    new = backend.score(prediction_prompt(changed, condition), case=changed, condition=condition)["probabilities"]
                    delta = new[chosen] - p
                    record.update({"counterfactual_probability_change": delta,
                                   "counterfactual_agreement": delta > 1e-6 if expected == "increase" else delta < -1e-6,
                                   "counterfactual_changed_query": changed["query"]})
                record["counterfactual_skip_reason"] = cf_error
            append_jsonl(path, record)
            print(f"Saved explanation tests: {case['case_id']} / {condition}; valid={obj is not None}", flush=True)
    export_audit(out)
    print(f"Finished. Review {out / 'manual_audit.csv'} before claiming explanations are factually grounded.")


def export_audit(out: Path) -> None:
    records = read_jsonl(out / "faithfulness.jsonl")
    path = out / "manual_audit.csv"
    old = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            old = {(r["case_id"], r["condition"]): r for r in csv.DictReader(handle)}
    fields = ["case_id", "condition", "correct", "predicted", "actual", "provided_evidence", "explanation",
              "supported_claims", "total_factual_claims", "reviewer_notes"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for r in records:
            row = {"case_id": r["case_id"], "condition": r["condition"], "correct": r["correct"],
                   "predicted": r["original_prediction"], "actual": r["target"],
                   "provided_evidence": json.dumps(r["provided_evidence"], ensure_ascii=False),
                   "explanation": r["raw_explanation"], "supported_claims": "", "total_factual_claims": "", "reviewer_notes": ""}
            for name in ("supported_claims", "total_factual_claims", "reviewer_notes"):
                row[name] = old.get((r["case_id"], r["condition"]), {}).get(name, "")
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("predict", "faithfulness", "health"))
    parser.add_argument("--cases", default="data/processed/cases.jsonl")
    parser.add_argument("--out", help="Use separate folders for model/data/code revisions.")
    parser.add_argument("--split", choices=("development", "validation", "test", "all"), default="test")
    parser.add_argument("--conditions", nargs="+", choices=("no_history", "with_history"), default=["no_history", "with_history"])
    parser.add_argument("--limit", type=int, default=0, help="Maximum cases, selected reproducibly; 0 means all.")
    parser.add_argument("--random-controls", type=int, default=5)
    parser.add_argument("--mock", action="store_true", help="Synthetic workflow check only; never real LLM results.")
    args = parser.parse_args()
    if args.limit < 0 or args.random_controls < 1:
        parser.error("--limit must be >=0 and --random-controls must be >=1")
    if args.command == "health":
        print(json.dumps(RemoteBackend().metadata, indent=2))
    elif args.command == "predict":
        predict(args)
    else:
        faithfulness(args)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        raise SystemExit(str(exc))
