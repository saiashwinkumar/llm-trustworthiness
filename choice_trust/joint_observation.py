"""One-response explanation and choice prediction from programmed observations.

This path is separate from the project's saved prediction-then-explanation study.
It never accepts a target purchase, prior prediction, or prior explanation.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .observations import render_observations


JOINT_PROMPT_VERSION = "joint-compact-factual-observation-v2"
JOINT_GENERATION_SETTINGS = {
    "do_sample": False,
    "num_beams": 1,
    "temperature": 1.0,
    "top_p": 1.0,
    "top_k": 50,
    "max_new_tokens": 512,
    "use_model_defaults": False,
    "enable_thinking": False,
}


def exposed_observation_ids(observation_result: dict) -> list[str]:
    """Citation scope is rendered evidence, never the internal audit catalogue.

    Archived v1 records exposed their full observation list; retain that scope
    when reading those saved records.
    """
    if observation_result.get("version") == "compact-factual-observations-v2":
        expected = render_observations(observation_result["observations"],
                                       history_provided=observation_result.get("history_provided", False))
        if observation_result.get("text") != expected:
            raise ValueError("citation scope does not match the rendered observations")
        groups = {"CURRENT_PRICES", "CURRENT_ADVERTISING"}
        if observation_result.get("history_provided"):
            groups.add("HOUSEHOLD_HISTORY")
        return [o["id"] for o in observation_result["observations"] if o["group"] in groups]
    return [o["id"] for o in observation_result["observations"]]


def build_joint_messages(observation_result: dict, candidates: list[dict]) -> list[dict]:
    """Use only the mapped candidates and generated factual observation lines."""
    ids = [c.get("id") for c in candidates]
    if not ids or any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("candidates need distinct nonempty answer identifiers")
    if any(not isinstance(c.get("name"), str) for c in candidates):
        raise ValueError("each candidate needs a product name")
    facts = observation_result.get("observations")
    if not isinstance(facts, list) or not facts:
        raise ValueError("generated factual observations are required")
    observation_ids = [o.get("id") for o in facts]
    if any(not isinstance(oid, str) or not oid for oid in observation_ids) or len(set(observation_ids)) != len(observation_ids):
        raise ValueError("observation IDs must be distinct nonempty strings")
    if observation_result.get("candidates") != candidates:
        raise ValueError("candidate mapping differs from generated observations")
    if observation_ids != exposed_observation_ids(observation_result):
        raise ValueError("observations contain facts outside the rendered concept groups")
    # Rebuild the rendering from structured records; do not trust a stale copy.
    rendered_facts = render_observations(facts, history_provided=observation_result.get("history_provided", False))
    if observation_result.get("text") != rendered_facts:
        raise ValueError("observation text differs from structured observations")
    offered = "\n".join(f"{c['id']} = {c['name']}" for c in candidates)
    content = (
        "Predict which product was purchased on this purchase occasion.\n\n"
        "Use only the supplied facts. Customer motives are unknown.\n"
        "Do not assume the cheapest product must be purchased.\n"
        "Support records are unordered separate purchases.\n"
        "NOT_PROVIDED means unavailable information.\n"
        "All displayed prices are assumed dollar amounts rounded to two decimals.\n\n"
        "CANDIDATES\n" + offered + "\n\n" + rendered_facts
        + "\n\nGive a brief evidence-based explanation, then your final prediction.\n"
        "Cite the displayed evidence IDs supporting your claims; any number of relevant IDs may be cited.\n"
        "For relationships or comparisons, cite all necessary evidence.\n"
        "Distinguish observed patterns from established causal preferences; briefly acknowledge conflicting evidence when relevant.\n"
        "Do not treat a support purchase as the hidden target purchase.\n\n"
        "Return exactly one JSON object, with these keys in this order:\n"
        '{"explanation":"<brief explanation>","evidence_ids":["<supporting IDs>"],"prediction":"<one valid candidate answer identifier>"}\n'
        + "Prediction must be exactly one of: " + ", ".join(json.dumps(cid) for cid in ids) + "."
    )
    return [{"role": "user", "content": content}]


def parse_joint_response(raw_response: str, candidates: list[dict], observation_result: dict,
                         *, truncated: bool | None = None) -> tuple[Any, dict]:
    """Validate without trimming, repairing, or replacing an invalid response."""
    parsed: Any = None
    parse_error = None
    try:
        parsed = json.loads(raw_response)
    except (json.JSONDecodeError, TypeError) as exc:
        parse_error = f"{type(exc).__name__}: {exc}"
    object_ok = isinstance(parsed, dict)
    keys = list(parsed) if object_ok else []
    expected_keys = ["explanation", "evidence_ids", "prediction"]
    explanation = parsed.get("explanation") if object_ok else None
    prediction = parsed.get("prediction") if object_ok else None
    cited = parsed.get("evidence_ids") if object_ok else None
    allowed = set(exposed_observation_ids(observation_result))
    citation_list_ok = isinstance(cited, list) and all(isinstance(x, str) for x in cited)
    unknown = [x for x in cited if x not in allowed] if citation_list_ok else None
    duplicates = [x for i, x in enumerate(cited) if x in cited[:i]] if citation_list_ok else None
    candidate_names = {c["id"]: c["name"] for c in candidates}
    diagnostics = {
        "parse_ok": object_ok,
        "parse_error": parse_error if parse_error else None if object_ok else "JSON value is not an object",
        "required_keys_present": object_ok and set(expected_keys) <= set(keys),
        "exact_keys_in_requested_order": keys == expected_keys,
        "explanation_present": isinstance(explanation, str) and bool(explanation.strip()),
        "prediction_valid": isinstance(prediction, str) and prediction in candidate_names,
        "predicted_product": candidate_names.get(prediction) if isinstance(prediction, str) else None,
        "citation_list_valid": citation_list_ok,
        "unknown_citation_ids": unknown,
        "duplicate_citation_ids": duplicates,
        "citations_valid": citation_list_ok and not unknown and not duplicates,
        "generation_truncated": truncated,
        "factual_correctness_checked": False,
        "faithfulness_checked": False,
    }
    return parsed, diagnostics


def generate_joint_response(observation_result: dict, candidates: list[dict], *,
                            model: Any, tokenizer: Any, device: Any,
                            generation_config: Any, model_metadata: dict) -> dict:
    """Make exactly one call to the already loaded model's generate method."""
    import torch

    messages = build_joint_messages(observation_result, candidates)
    rendered_prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False)
    encoded = tokenizer(rendered_prompt, return_tensors="pt", add_special_tokens=False).to(device)
    input_length = int(encoded["input_ids"].shape[-1])
    max_input_tokens = 4096  # Same bound as the configured CPU server.
    if input_length > max_input_tokens:
        raise ValueError(f"joint prompt has {input_length} tokens; configured limit is {max_input_tokens}; nothing was truncated")
    effective = dict(JOINT_GENERATION_SETTINGS)
    effective.update({
        "eos_token_id": generation_config.eos_token_id,
        "pad_token_id": generation_config.pad_token_id,
        "use_cache": generation_config.use_cache,
        "max_input_tokens": max_input_tokens,
    })
    with torch.inference_mode():
        output = model.generate(
            **encoded,
            generation_config=generation_config,
            use_model_defaults=False,
            do_sample=False,
            num_beams=1,
            temperature=1.0,
            top_p=1.0,
            top_k=50,
            max_new_tokens=512,
        )
    new_ids = output[0, input_length:]
    token_ids = new_ids.tolist()
    raw_response = tokenizer.decode(new_ids, skip_special_tokens=True)
    raw_with_special_tokens = tokenizer.decode(new_ids, skip_special_tokens=False)
    eos = generation_config.eos_token_id
    eos_ids = {eos} if isinstance(eos, int) else set(eos or [])
    if token_ids and token_ids[-1] in eos_ids:
        finish_reason, truncated = "stop", False
    elif len(token_ids) >= effective["max_new_tokens"]:
        finish_reason, truncated = "length", True
    else:
        finish_reason, truncated = "unknown", None
    parsed, diagnostics = parse_joint_response(raw_response, candidates, observation_result,
                                                truncated=truncated)
    return {
        "prompt_version": JOINT_PROMPT_VERSION,
        "observation_version": observation_result.get("version"),
        "messages": messages,
        "rendered_prompt": rendered_prompt,
        "included_observation_ids": exposed_observation_ids(observation_result),
        "raw_response": raw_response,
        "raw_response_with_special_tokens": raw_with_special_tokens,
        "raw_output_token_ids": token_ids,
        "parsed_result": parsed,
        "diagnostics": diagnostics,
        "generation_metadata": {
            "model": dict(model_metadata),
            "effective_settings": effective,
            "input_tokens": input_length,
            "output_tokens": len(token_ids),
            "finish_reason": finish_reason,
        },
    }


def save_joint_record(directory: Path, *, case_id: str, condition: str,
                      observation_result: dict, result: dict) -> Path:
    """Save one attempt without a target or any prior-study record."""
    if condition not in ("no_history", "with_history"):
        raise ValueError(f"unsupported condition: {condition}")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    path = directory / f"{case_id}_{condition}_{stamp}_{uuid4().hex[:8]}.json"
    record = {"case_id": case_id, "condition": condition,
              "observation_version": observation_result.get("version"),
              "observation_result": observation_result, **result}
    with path.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    return path
