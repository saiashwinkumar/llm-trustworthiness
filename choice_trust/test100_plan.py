"""Freeze the test/with-history stage without reading model outcomes or inferring.

Selection is seeded round-robin sampling of actual queries within test households.
The source target is read only after selection, into a separate evaluation file;
the predictor sources and prompts are constructed through the existing allowlist.
All intervention selection and checks delegate to the frozen development code.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import random

from .development_pilot import (
    FAMILIES, digest, history_statistics, identity_presentation, model_inputs,
    patch_between, plan_edit, registry, verify_edit,
)
from .joint_observation import (
    JOINT_GENERATION_SETTINGS, JOINT_PROMPT_VERSION, build_joint_messages,
)
from .observations import (
    OBSERVATION_VERSION, PRICE_POLICY, generate_observations,
    inputs_from_prepared_yogurt,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_VERSION = "test-with-history-100-v1"
DEFAULT_CASES = ROOT / "data/processed/cases.jsonl"
DEFAULT_OUT = ROOT / "choice_study/test_with_history_100_v1"
DEVELOPMENT_MANIFEST = ROOT / "choice_study/development_counterfactual_v1/manifest.json"
SELECTION_COUNT = 100


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _path_label(path):
    path = Path(path).resolve()
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _resolve_path(label):
    path = Path(label)
    return path if path.is_absolute() else ROOT / path


def implementation_hashes():
    names = (
        "choice_trust/test100_plan.py", "choice_trust/development_pilot.py",
        "choice_trust/observations.py", "choice_trust/joint_observation.py",
    )
    return {name: _file_hash(ROOT / name) for name in names}


def preserved_artifact_hashes():
    """Record preservation provenance; these records are never evaluation labels."""
    pilot = ROOT / "choice_study/development_counterfactual_v1"
    paths = [ROOT / "docs/EXPLANATION_ANNOTATION_GUIDE.md"]
    paths += sorted((pilot / "annotations").glob("*.json"))
    review = pilot / "agent_assisted_annotation_audit_v1/reviewed_layer.json"
    if review.exists():
        paths.append(review)
    return {_path_label(path): _file_hash(path) for path in paths}


def _case_key(case):
    value = case["case_id"]
    suffix = value.removeprefix("row-")
    return (0, int(suffix)) if suffix.isdigit() else (1, value)


def select_cases(rows, seed=42, count=SELECTION_COUNT):
    """Uniformly shuffle per-household queries, then take one per household/round.

    Exhausted households leave the rotation. This balances counts as evenly as
    their record capacities permit, without consulting targets or model outputs.
    Stable sorting before shuffling makes input-file order immaterial.
    """
    test = [row for row in rows if row.get("split") == "test" and not row.get("synthetic")]
    if len(test) < count:
        raise ValueError(f"Need {count} actual test queries; found {len(test)}")
    identifiers = [row["case_id"] for row in test]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Actual test case identifiers must be unique")
    households = defaultdict(list)
    for row in sorted(test, key=_case_key):
        households[str(row["household_id"])].append(row)
    rng = random.Random(seed)
    household_order = sorted(households)
    rng.shuffle(household_order)
    for household in household_order:
        rng.shuffle(households[household])
    selected, round_index = [], 0
    while len(selected) < count:
        for household in household_order:
            if round_index < len(households[household]):
                selected.append((households[household][round_index], round_index + 1))
                if len(selected) == count:
                    break
        round_index += 1
    selected_ids = {row["case_id"] for row, _ in selected}
    remaining = [row["case_id"] for row in sorted(test, key=_case_key)
                 if row["case_id"] not in selected_ids]
    return selected, remaining


def _development_bounds():
    pilot = json.loads(DEVELOPMENT_MANIFEST.read_text())
    if pilot["price_policy"] != PRICE_POLICY:
        raise ValueError("Development price policy differs from the current renderer")
    bounds = pilot["development_price_bounds_cents"]
    if len(bounds) != 2 or not all(isinstance(v, int) for v in bounds) or not 0 < bounds[0] <= bounds[1]:
        raise ValueError("Invalid frozen development price bounds")
    return bounds


def _target_product(row, source):
    """Resolve the actual target against this case's candidate identities."""
    target = row["target"]
    products = {candidate["id"]: candidate["name"] for candidate in source["candidates"]}
    if target in products:
        return target
    matches = [product_id for product_id, name in products.items() if target == name]
    if len(matches) != 1:
        raise ValueError(f"Target is not a unique candidate for {row['case_id']}")
    return matches[0]


def _stage_registry():
    result = deepcopy(registry())
    for item in result:
        item["conditions"] = ["with_history"]
        if item["family_id"] == "CURRENT_PRICE":
            item["selection_rule"] = (
                "Zero-based selected-case index even: existing preserve-cheapest rule; "
                "odd: existing reverse-cheapest rule. Preserve: first candidate with "
                "a +1/-1-cent edit preserving the entire cheapest set. Reverse: first "
                "noncheapest candidate set one cent below the minimum. All edits "
                "remain inside the frozen development bounds. No substitution if infeasible."
            )
    return result


def build_plan(cases_path=DEFAULT_CASES, seed=42):
    """Return a complete pre-inference manifest plus isolated evaluation targets."""
    cases_path = Path(cases_path).resolve()
    rows = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    selected, remaining = select_cases(rows, seed)
    bounds = _development_bounds()
    entries, selected_cases, targets = [], [], {}
    for index, (row, selection_round) in enumerate(selected):
        variant = "preserve" if index % 2 == 0 else "reverse"
        metadata = {
            "case_id": row["case_id"], "household_id": str(row["household_id"]),
            "split": "test", "condition": "with_history", "selection_index": index,
            "household_selection_round": selection_round, "price_variant": variant,
        }
        selected_cases.append(metadata)
        source = inputs_from_prepared_yogurt(row, with_history=True)
        # Evaluation is deliberately separate from every predictor entry below.
        targets[row["case_id"]] = _target_product(row, source)
        for family in ("ORIGINAL",) + FAMILIES:
            if family == "ORIGINAL":
                changed, presentation = deepcopy(source), identity_presentation(source)
                details = {"skip_reason": None}
            else:
                changed, presentation, details = plan_edit(source, family, bounds, variant)
            entry = {
                "call_id": f"{row['case_id']}__with_history__{family}",
                "case_id": row["case_id"], "household_id": str(row["household_id"]),
                "condition": "with_history", "family": family,
                "original_source": source, "edit_details": details,
                "skip_reason": details["skip_reason"], "applicable": changed is not None,
                "initial_status": "pending" if changed is not None else "not_applicable",
            }
            if changed is not None:
                inputs = model_inputs(changed, presentation)
                observations = generate_observations(**inputs)
                entry.update(
                    edited_source=changed, presentation=presentation, observations=observations,
                    messages=build_joint_messages(observations, inputs["candidates"]),
                    patch=patch_between(source, changed, identity_presentation(source), presentation),
                    statistics_before=history_statistics(source), statistics_after=history_statistics(changed),
                )
                entry["integrity"] = verify_edit(entry, bounds)
            entries.append(entry)
    stage_registry = _stage_registry()
    counts = Counter(item["household_id"] for item in selected_cases)
    source_digest = _file_hash(cases_path)
    manifest = {
        "protocol_version": PROTOCOL_VERSION, "seed": seed, "condition": "with_history",
        "split": "test", "source_path": _path_label(cases_path), "source_sha256": source_digest,
        "selection_rule": "Seeded round-robin across test households; independently seed-shuffled actual query records within each household; exhausted households omitted from later rounds; no outcome-based filtering",
        "selection_count": SELECTION_COUNT, "selected_cases": selected_cases,
        "selected_household_counts": dict(sorted(counts.items())),
        "remaining_test_case_ids": remaining,
        "eligible_test_case_count": len(selected) + len(remaining),
        "entries": entries, "registry": stage_registry,
        "observation_version": OBSERVATION_VERSION, "prompt_version": JOINT_PROMPT_VERSION,
        "price_policy": PRICE_POLICY, "development_price_bounds_cents": bounds,
        "bounds_source": _path_label(DEVELOPMENT_MANIFEST),
        "bounds_source_sha256": _file_hash(DEVELOPMENT_MANIFEST),
        "joint_settings": JOINT_GENERATION_SETTINGS,
        "implementation_hashes": implementation_hashes(),
        "preserved_artifacts": preserved_artifact_hashes(),
        "evaluation_targets_sha256": sha256(_json_bytes(targets)).hexdigest(),
        "planned_originals": SELECTION_COUNT,
        "planned_interventions": sum(e["family"] != "ORIGINAL" and e["applicable"] for e in entries),
        "not_applicable_interventions": sum(not e["applicable"] for e in entries),
        "planned_total_responses": sum(e["applicable"] for e in entries),
        "annotation_policy": "No bulk annotation; preserved unchecked pilot records are not evaluation labels; reviewed layer is agent-assisted, not human review",
        "sampling_policy": "One joint response per applicable original/edit; no unchanged reruns or repeated sampling; do not automatically continue to remaining test cases",
        "interpretation": "Original accuracy uses separate held-out targets. Edited-scenario customer outcomes are unknown; no counterfactual customer accuracy or conclusive faithfulness score.",
    }
    manifest["plan_id"] = digest(manifest)
    return manifest, targets


def _write_new(path, value):
    """Write only new files, flush immediately, and never replace saved artifacts."""
    with Path(path).open("xb") as handle:
        handle.write(_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())


def prepare(out=DEFAULT_OUT, cases_path=DEFAULT_CASES, seed=42):
    """Reuse a valid frozen plan or create this stage once; never infer."""
    out = Path(out)
    if (out / "manifest.json").exists():
        manifest = verify_manifest(out)
        if manifest["seed"] != seed or manifest["source_sha256"] != _file_hash(cases_path):
            raise ValueError("Requested seed/source differs from the frozen selection")
        return manifest
    out.mkdir(parents=True, exist_ok=True)
    lock = out / ".prepare.lock"
    try:
        handle = lock.open("x")
    except FileExistsError as exc:
        raise RuntimeError("Stage preparation is locked; inspect the existing preparer") from exc
    try:
        handle.write(str(os.getpid()))
        handle.flush()
        if any(path != lock for path in out.iterdir()):
            raise RuntimeError("Stage directory contains an incomplete or unknown plan; refusing to overwrite")
        manifest, targets = build_plan(cases_path, seed)
        _write_new(out / "selected_cases.json", manifest["selected_cases"])
        _write_new(out / "remaining_test_case_ids.json", manifest["remaining_test_case_ids"])
        _write_new(out / "evaluation_targets.json", targets)
        _write_new(out / "registry.json", manifest["registry"])
        protocol = {key: value for key, value in manifest.items()
                    if key not in ("entries", "selected_cases", "remaining_test_case_ids")}
        _write_new(out / "protocol.json", protocol)
        # The manifest is the final completion marker for pre-inference planning.
        _write_new(out / "manifest.json", manifest)
        return manifest
    finally:
        handle.close()
        lock.unlink()


def verify_manifest(out=DEFAULT_OUT):
    """Read-only verification of frozen inputs, versions, patches, and provenance."""
    out = Path(out)
    manifest = json.loads((out / "manifest.json").read_text())
    seal = {key: value for key, value in manifest.items() if key != "plan_id"}
    if manifest.get("plan_id") != digest(seal):
        raise ValueError("Manifest plan_id seal does not match its frozen contents")
    if manifest.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError("Unexpected experimental protocol version")
    if manifest["implementation_hashes"] != implementation_hashes():
        raise ValueError("Frozen planning/intervention/renderer implementation changed")
    if (manifest["price_policy"] != PRICE_POLICY or manifest["joint_settings"] != JOINT_GENERATION_SETTINGS
            or manifest["observation_version"] != OBSERVATION_VERSION
            or manifest["prompt_version"] != JOINT_PROMPT_VERSION):
        raise ValueError("Frozen observation, prompt, price policy, or generation settings changed")
    cases_path = _resolve_path(manifest["source_path"])
    if _file_hash(cases_path) != manifest["source_sha256"]:
        raise ValueError("Frozen prepared source data changed")
    bounds_path = _resolve_path(manifest["bounds_source"])
    if _file_hash(bounds_path) != manifest["bounds_source_sha256"]:
        raise ValueError("Frozen development bounds provenance changed")
    if _development_bounds() != manifest["development_price_bounds_cents"]:
        raise ValueError("Frozen development price bounds changed")
    for label, expected in manifest["preserved_artifacts"].items():
        if _file_hash(_resolve_path(label)) != expected:
            raise ValueError(f"Preserved annotation artifact changed: {label}")
    selected = json.loads((out / "selected_cases.json").read_text())
    remaining = json.loads((out / "remaining_test_case_ids.json").read_text())
    if selected != manifest["selected_cases"] or remaining != manifest["remaining_test_case_ids"]:
        raise ValueError("Saved selection lists differ from the manifest")
    targets_path = out / "evaluation_targets.json"
    if _file_hash(targets_path) != manifest["evaluation_targets_sha256"]:
        raise ValueError("Separate original evaluation targets changed")
    targets = json.loads(targets_path.read_text())
    rows = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
    sampled, expected_remaining = select_cases(rows, manifest["seed"])
    if [row["case_id"] for row, _ in sampled] != [item["case_id"] for item in selected] or remaining != expected_remaining:
        raise ValueError("Frozen case selection differs from the seeded household-balanced rule")
    if len(selected) != SELECTION_COUNT or len({item["case_id"] for item in selected}) != SELECTION_COUNT:
        raise ValueError("Stage must contain exactly 100 unique actual test queries")
    source_by_case = {}
    for row, selection_round in sampled:
        source = inputs_from_prepared_yogurt(row, with_history=True)
        source_by_case[row["case_id"]] = source
        if targets.get(row["case_id"]) != _target_product(row, source):
            raise ValueError("Evaluation target differs from the actual selected query")
    entries = manifest["entries"]
    expected_pairs = {(item["case_id"], family) for item in selected for family in ("ORIGINAL",) + FAMILIES}
    if len(entries) != SELECTION_COUNT * 9 or {(e["case_id"], e["family"]) for e in entries} != expected_pairs:
        raise ValueError("Manifest must contain exactly one original and each of eight families per selected query")
    if len({e["call_id"] for e in entries}) != len(entries):
        raise ValueError("Duplicate planned call identifiers")
    for entry in entries:
        if entry["condition"] != "with_history" or entry["original_source"] != source_by_case[entry["case_id"]]:
            raise ValueError("Entry source is not the untouched selected with-history test query")
        if entry["applicable"] != (entry["skip_reason"] is None):
            raise ValueError("Applicability and skip reason disagree")
        if entry["applicable"]:
            verify_edit(entry, manifest["development_price_bounds_cents"])
        else:
            if not entry["skip_reason"] or entry["family"] == "ORIGINAL":
                raise ValueError("Every unavailable intervention requires a predefined reason")
    if json.loads((out / "registry.json").read_text()) != manifest["registry"]:
        raise ValueError("Registry snapshot differs from the manifest")
    protocol = {key: value for key, value in manifest.items()
                if key not in ("entries", "selected_cases", "remaining_test_case_ids")}
    if json.loads((out / "protocol.json").read_text()) != protocol:
        raise ValueError("Protocol snapshot differs from the manifest")
    return manifest
