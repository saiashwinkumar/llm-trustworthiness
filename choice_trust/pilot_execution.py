"""Bounded/resumable execution of the predeclared compact development pilot."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from .development_pilot import (PROTOCOL_VERSION, plan_pilot, verify_edit, digest,
                                implementation_hashes, model_inputs, identity_presentation)
from .joint_observation import generate_joint_response
from .explanation_annotation import (load_guide, cached_local_annotator, annotate_explanation,
                                     GROUPS, concept_summary)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "choice_study/development_counterfactual_v1"
MODEL_ID = "Qwen/Qwen3-1.7B"
REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False, encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
        temporary = handle.name
    os.replace(temporary, path)


def load_runtime(*, model=None, tokenizer=None):
    """One existing or cached pinned model, shared by predictor and annotator."""
    import torch
    import transformers
    from transformers import AutoTokenizer, AutoModelForCausalLM, GenerationConfig
    snapshot = Path.home() / ".cache/huggingface/hub/models--Qwen--Qwen3-1.7B/snapshots" / REVISION
    if tokenizer is None:
        tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
    if model is None:
        model = AutoModelForCausalLM.from_pretrained(str(snapshot), local_files_only=True,
                                                    dtype=torch.float32, low_cpu_mem_usage=True).to("cpu")
    model.eval()
    device = next(model.parameters()).device
    metadata = {"model_id": MODEL_ID, "revision": REVISION, "tokenizer": tokenizer.name_or_path,
                "device": str(device), "dtype": str(next(model.parameters()).dtype),
                "torch": torch.__version__, "transformers": transformers.__version__}
    if metadata["device"] != "cpu" or metadata["dtype"] != "torch.float32":
        raise ValueError("Pilot requires the configured CPU float32 protocol")
    annotation_generate, annotation_model = cached_local_annotator(metadata, model=model, tokenizer=tokenizer)
    generation_config = GenerationConfig(do_sample=False, max_new_tokens=512, num_beams=1,
                                         eos_token_id=model.generation_config.eos_token_id,
                                         pad_token_id=tokenizer.eos_token_id)
    return {"model": model, "tokenizer": tokenizer, "device": device, "generation_config": generation_config,
            "model_metadata": metadata, "annotation_generate": annotation_generate, "annotation_model": annotation_model}


class Pilot:
    def __init__(self, out=DEFAULT_OUT):
        self.out = Path(out)
        self.manifest = json.loads((self.out / "manifest.json").read_text())
        check = {k: v for k, v in self.manifest.items() if k != "plan_id"}
        if digest(check) != self.manifest["plan_id"] or self.manifest["protocol_version"] != PROTOCOL_VERSION:
            raise ValueError("Manifest/protocol mismatch")
        if self.manifest["implementation_hashes"] != implementation_hashes():
            raise ValueError("Pilot implementation or guide changed; use a new versioned output directory")
        self.runtime = None

    @classmethod
    def prepare(cls, out=DEFAULT_OUT, cases_path=ROOT / "data/processed/cases.jsonl", seed=42):
        out, cases_path = Path(out), Path(cases_path)
        if not (out / "manifest.json").exists():
            if out.exists() and any(out.iterdir()):
                raise ValueError("Pilot directory is nonempty without a manifest")
            manifest = plan_pilot(cases_path, seed)
            manifest["expected_model"] = {"model_id": MODEL_ID, "revision": REVISION, "device": "cpu", "dtype": "torch.float32"}
            manifest["annotation_guide"] = load_guide(ROOT / "docs/EXPLANATION_ANNOTATION_GUIDE.md")
            manifest["annotation_selection"] = "Four originals; one informative historical-price edit per case, otherwise that case's with-history price reversal; no substitutes based on outputs"
            manifest["plan_id"] = digest(manifest)
            atomic_json(out / "manifest.json", manifest)
            atomic_json(out / "registry.json", manifest["registry"])
            atomic_json(out / "protocol.json", {k: v for k, v in manifest.items() if k != "entries"})
        pilot = cls(out)
        if pilot.manifest["seed"] != seed or pilot.manifest["development_source_sha256"] != __import__("hashlib").sha256(cases_path.read_bytes()).hexdigest():
            raise ValueError("Source data or seed differs from saved plan")
        return pilot

    def attach(self, runtime):
        fingerprint = {"model": runtime["model_metadata"], "generation_config": runtime["generation_config"].to_dict(),
                       "annotation_model": runtime["annotation_model"], "annotation_max_tokens": 2048,
                       "guide_sha256": self.manifest["annotation_guide"]["sha256"]}
        for key, value in self.manifest["expected_model"].items():
            if fingerprint["model"].get(key) != value:
                raise ValueError(f"Unexpected runtime model setting: {key}")
        path = self.out / "runtime.json"
        if path.exists() and json.loads(path.read_text()) != fingerprint:
            raise ValueError("Runtime differs from completed records; use a new versioned pilot")
        if not path.exists(): atomic_json(path, fingerprint)
        self.runtime, self.fingerprint = runtime, fingerprint
        return self

    @contextmanager
    def writer(self):
        path = self.out / ".writer.lock"
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, str(os.getpid()).encode())
            yield
        finally:
            os.close(fd)
            path.unlink()

    def events(self):
        path = self.out / "events.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def event(self, **fields):
        record = {"utc": datetime.now(timezone.utc).isoformat(), **fields}
        with (self.out / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def reserve(self, kind, call_id):
        events = self.events()
        started = [e for e in events if e["event"] == "started" and e["kind"] == kind]
        cap = self.manifest["budgets"]["generation_cap" if kind == "generation" else "annotation_cap"]
        if any(e["call_id"] == call_id for e in started):
            raise RuntimeError("Prior attempt is failed or unfinished; no automatic retry is allowed")
        if len(started) >= cap:
            raise RuntimeError(f"Hard {kind} budget exhausted")
        self.event(event="started", kind=kind, call_id=call_id)

    def entry(self, call_id):
        return next(e for e in self.manifest["entries"] if e["call_id"] == call_id)

    def responses(self):
        return {p.stem: json.loads(p.read_text()) for p in (self.out / "responses").glob("*.json")}

    def annotations(self):
        return {p.stem: json.loads(p.read_text()) for p in (self.out / "annotations").glob("*.json")}

    def run(self, families):
        if self.runtime is None:
            raise ValueError("Attach the shared model runtime before inference")
        if isinstance(families, str): families = [families]
        with self.writer():
            for entry in self.manifest["entries"]:
                if entry["family"] not in families or entry["skip_reason"]:
                    continue
                checks = verify_edit(entry, self.manifest["development_price_bounds_cents"])
                runtime = self.runtime
                rendered = runtime["tokenizer"].apply_chat_template(entry["messages"], tokenize=False, add_generation_prompt=True, enable_thinking=False)
                signature = digest({"entry": entry, "runtime": self.fingerprint, "rendered_prompt": rendered, "plan_id": self.manifest["plan_id"]})
                path = self.out / "responses" / (entry["call_id"] + ".json")
                if path.exists():
                    record = json.loads(path.read_text())
                    if record["input_signature"] != signature:
                        raise ValueError("Saved response input/model/protocol signature differs")
                    self.event(event="reused", kind="generation", call_id=entry["call_id"], source=str(path), signature=signature)
                    continue
                self.reserve("generation", entry["call_id"])
                print("Generating", entry["call_id"], flush=True)
                try:
                    result = generate_joint_response(entry["observations"], entry["observations"]["candidates"],
                        **{key: runtime[key] for key in ("model", "tokenizer", "device", "generation_config", "model_metadata")})
                    atomic_json(self.out / "raw_attempts" / (entry["call_id"] + ".json"), result)
                    if result["messages"] != entry["messages"] or result["rendered_prompt"] != rendered:
                        raise ValueError("Generated prompt differs from the verified planned prompt")
                    answer = result["parsed_result"].get("prediction") if isinstance(result["parsed_result"], dict) else None
                    inverse = {a: cid for cid, a in entry["presentation"]["answer_mapping"].items()}
                    decoded = inverse.get(answer) if isinstance(answer, str) else None
                    record = {"call_id": entry["call_id"], "case_id": entry["case_id"], "condition": entry["condition"],
                              "family": entry["family"], "input_signature": signature, "plan_id": self.manifest["plan_id"],
                              "verified_integrity": checks, "decoded_product_id": decoded, "response": result}
                    atomic_json(path, record)
                    self.event(event="completed", kind="generation", call_id=entry["call_id"], signature=signature)
                except Exception as error:
                    failure = {"call_id": entry["call_id"], "kind": "generation", "error_type": type(error).__name__, "error": str(error), "input_signature": signature}
                    atomic_json(self.out / "failures" / (entry["call_id"] + ".json"), failure)
                    self.event(event="failed", **failure)
                    raise
        return self.status()

    def annotation_example(self, record):
        entry = self.entry(record["call_id"])
        response = record["response"]
        parsed = response["parsed_result"]
        if not isinstance(parsed, dict) or not isinstance(parsed.get("explanation"), str) or not parsed["explanation"].strip():
            return None
        obs = entry["observations"]
        return {"explanation": parsed["explanation"], "predicted_candidate": parsed.get("prediction"), "model_citations": parsed.get("evidence_ids"),
                "candidates": obs["candidates"], "observations": {"version": obs["version"], "text": obs["text"], "observations": obs["observations"]},
                "provenance": {o["id"]: {"concept_groups": [o["group"]], "source_fields": o["sources"], "dependencies": o["dependencies"]} for o in obs["observations"]}}

    def run_annotations(self):
        if self.runtime is None: raise ValueError("Attach shared runtime first")
        responses = self.responses()
        with self.writer():
            for call_id in self.manifest["annotation_call_ids"]:
                if call_id not in responses: raise ValueError("Planned generation is not complete: " + call_id)
                source = responses[call_id]
                inputs = self.annotation_example(source)
                path = self.out / "annotations" / (call_id + ".json")
                signature = digest({"original_response": source, "inputs": inputs, "guide": self.manifest["annotation_guide"], "runtime": self.fingerprint})
                if path.exists():
                    if json.loads(path.read_text())["annotation_signature"] != signature: raise ValueError("Annotation signature mismatch")
                    self.event(event="reused", kind="annotation", call_id=call_id, source=str(path), signature=signature)
                    continue
                if inputs is None:
                    atomic_json(path, {"annotation_signature": signature, "skip_reason": "No parsed explanation text available", "call_id": call_id})
                    continue
                reused = None
                # An external annotation may be reused only with its exact source response/settings and guide.
                if source["family"] == "ORIGINAL":
                    for external in sorted((ROOT / "choice_study/explanation_annotation_runs").glob("*.json")):
                        old = json.loads(external.read_text())
                        source_path = Path(old.get("source_response_path", "__missing__"))
                        if not source_path.is_absolute(): source_path = ROOT / source_path
                        if not source_path.is_file() or old.get("annotation_guide") != self.manifest["annotation_guide"]: continue
                        old_source = json.loads(source_path.read_text())
                        compare = ("raw_response", "messages", "generation_metadata")
                        if all(old_source.get(k) == source["response"].get(k) for k in compare) and all(old.get("annotation_input", {}).get(k) == v for k, v in inputs.items()):
                            reused = {"result": old, "reuse_provenance": {"path": str(external), "sha256": __import__("hashlib").sha256(external.read_bytes()).hexdigest()}}
                            break
                if reused:
                    atomic_json(path, {"call_id": call_id, "annotation_signature": signature, **reused})
                    self.event(event="reused", kind="annotation", call_id=call_id, source=reused["reuse_provenance"]["path"], signature=signature)
                    continue
                self.reserve("annotation", call_id)
                print("Annotating", call_id, flush=True)
                try:
                    result = annotate_explanation(**inputs, guide=self.manifest["annotation_guide"],
                        generate=self.runtime["annotation_generate"], annotator_model=self.runtime["annotation_model"],
                        predictor_model=self.runtime["model_metadata"])
                    atomic_json(path, {"call_id": call_id, "annotation_signature": signature, "source_response_hash": digest(source), "result": result})
                    self.event(event="completed", kind="annotation", call_id=call_id, signature=signature)
                except Exception as error:
                    failure = {"call_id": call_id, "kind": "annotation", "error_type": type(error).__name__, "error": str(error)}
                    atomic_json(self.out / "failures" / (call_id + "__annotation.json"), failure)
                    self.event(event="failed", **failure)
                    raise
        return self.status()

    def status(self):
        events = self.events()
        return {"output": str(self.out), "planned": self.manifest["budgets"],
                "actual_generation_attempts": sum(e["event"] == "started" and e["kind"] == "generation" for e in events),
                "actual_annotation_attempts": sum(e["event"] == "started" and e["kind"] == "annotation" for e in events),
                "completed_generation_records": len(self.responses()), "annotation_records": len(self.annotations()),
                "failures": [e for e in events if e["event"] == "failed"]}

    def result_rows(self):
        responses, annotations = self.responses(), self.annotations()
        reviews_path = self.out / "manual_review.json"
        reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
        rows = []
        for entry in self.manifest["entries"]:
            if entry["family"] == "ORIGINAL": continue
            baseline = responses.get(f"{entry['case_id']}__{entry['condition']}__ORIGINAL")
            after = responses.get(entry["call_id"])
            a = baseline["decoded_product_id"] if baseline else None
            b = after["decoded_product_id"] if after else None
            annotation = annotations.get(entry["call_id"], {}).get("result")
            claims = annotation.get("parsed_annotations") if annotation else None
            claims = claims.get("claims", []) if isinstance(claims, dict) else []
            contradicted = [c.get("exact_quote") for c in claims if isinstance(c, dict) and c.get("factual_status") == "contradicted"] if isinstance(claims, list) else []
            rows.append({"case": entry["case_id"], "condition": entry["condition"], "family": entry["family"],
                         "exact_edit": entry.get("patch", []), "skip_reason": entry["skip_reason"],
                         "original_product": a, "edited_product": b, "product_changed": a != b if a is not None and b is not None else None,
                         "original_explanation": (baseline["response"]["parsed_result"].get("explanation") if baseline and isinstance(baseline["response"]["parsed_result"], dict) else None),
                         "edited_explanation": (after["response"]["parsed_result"].get("explanation") if after and isinstance(after["response"]["parsed_result"], dict) else None),
                         "observed_factual_contradiction": contradicted or "Not yet manually reviewed; no factual verdict inferred",
                         "annotation_status": "Provisional; review required" if annotation else "Not yet annotated",
                         "manual_factual_review": reviews.get(entry["call_id"], "Not manually reviewed"),
                         "reason_change": "Compare provisional claim tables" if annotation else "Not assessed without annotation/review",
                         "measured": after is not None})
        return rows

    def save_report(self):
        value = {"status": self.status(), "results": self.result_rows(),
                 "interpretation_limits": ["Unchanged answers do not establish zero influence", "Changed explanations are not automatically inconsistent",
                    "Explicit cheapest-brand deciding rules differ from contributing price reasons", "One response per input is not an answer distribution estimate",
                    "Edited customer purchases are unknown", "Development pilot is not a conclusive faithfulness evaluation"]}
        atomic_json(self.out / "results.json", value)
        return value
