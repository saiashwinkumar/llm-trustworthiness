"""Predeclared, target-free development pilot on compact joint responses."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
from itertools import permutations
import json
from pathlib import Path
import random

from .observations import generate_observations, inputs_from_prepared_yogurt, canonical_price, OBSERVATION_VERSION, PRICE_POLICY
from .joint_observation import build_joint_messages, JOINT_PROMPT_VERSION, JOINT_GENERATION_SETTINGS

PROTOCOL_VERSION = "compact-development-counterfactual-v1"
CONDITIONS = ("no_history", "with_history")
FAMILIES = ("CURRENT_PRICE", "CURRENT_ADVERTISING", "SUPPORT_PURCHASE", "HISTORICAL_PRICE_ASSOCIATION",
            "HISTORICAL_ADVERTISING_ASSOCIATION", "HISTORICAL_OFFER_REMOVAL", "PRODUCT_ORDER_CONTROL", "ANSWER_MAPPING_CONTROL")
HISTORY_FAMILIES = set(FAMILIES[2:6])


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def cents(value):
    return None if value is None else int(Decimal(canonical_price(value)) * 100)


def registry():
    rules = {
        "CURRENT_PRICE": ("Price sensitivity: preserved or reversed cheapest set", ["current.prices.<one candidate>"],
            "First case: first candidate with a +/-1-cent edit preserving the entire cheapest set. Second case: first noncheapest candidate set one cent below the minimum.",
            "Complete current prices, positive cent-valued alternative inside development bounds; otherwise skip.", ["current order, cheapest set, gaps"]),
        "CURRENT_ADVERTISING": ("Current advertising sensitivity", ["current.advertised.<one candidate>"],
            "Toggle the lexicographically first candidate with a known flag.", "At least one known current flag.", ["current advertising summary"]),
        "SUPPORT_PURCHASE": ("Household-history sensitivity including dependent purchase-offer relations", ["<first support ID>.purchased"],
            "First support ID; replace purchase with next candidate in sorted cyclic candidate order.", "Known support purchase and at least two candidates.", ["counts, shares, most frequent, historical price and advertising relationships"]),
        "HISTORICAL_PRICE_ASSOCIATION": ("Change price-purchase association at fixed purchase counts", ["H*.prices.*"],
            "Enumerate vector permutations; deduplicate unordered visible records; maximize absolute change in purchased-among-cheapest numerator, then lexicographic assignment.",
            "2..8 complete support records; changed association with same eligible denominator; otherwise uninformative.", ["per-record cheapest/gaps and historical price aggregates"]),
        "HISTORICAL_ADVERTISING_ASSOCIATION": ("Change advertisement-purchase association at fixed purchases", ["H*.advertised.*"],
            "Enumerate vector permutations; deduplicate unordered visible records; maximize absolute change in purchased-advertised numerator, then lexicographic assignment.",
            "2..8 known support records with varying flag vectors and changed association; otherwise skip.", ["historical purchased-advertised relations and aggregates"]),
        "HISTORICAL_OFFER_REMOVAL": ("Remove historical offer context while retaining purchases", ["H*.prices.*", "H*.advertised.*"],
            "Set all historical offer values to null; retain support IDs and purchases.", "At least one provided historical offer field.", ["all historical offer relationships and exclusions; counts preserved"]),
        "PRODUCT_ORDER_CONTROL": ("Candidate presentation sensitivity", ["presentation.order"],
            "Rotate candidate presentation one position left; preserve answer mapping.", "At least two candidates.", ["all compact facts rerendered in presentation order"]),
        "ANSWER_MAPPING_CONTROL": ("Answer-label assignment sensitivity, decoded by product", ["presentation.answer_mapping"],
            "Rotate sorted answer identifiers one position left across fixed product identities; remap every current/support candidate field.",
            "At least two candidates; bijection verified.", ["all compact facts regenerated under consistent relabeling"]),
    }
    return [{"family_id": family, "purpose": rules[family][0],
             "conditions": ["with_history"] if family in HISTORY_FAMILIES else list(CONDITIONS),
             "permitted_source_fields": rules[family][1], "must_remain_fixed": "Every source/presentation field outside the permitted set",
             "selection_rule": rules[family][2], "applicability": rules[family][3],
             "regenerate": rules[family][4], "parent_groups": ["HOUSEHOLD_HISTORY"] if family in HISTORY_FAMILIES else
             ["CURRENT_PRICES"] if family == "CURRENT_PRICE" else ["CURRENT_ADVERTISING"] if family == "CURRENT_ADVERTISING" else
             ["CURRENT_PRICES", "CURRENT_ADVERTISING", "HOUSEHOLD_HISTORY"]} for family in FAMILIES]


def cheapest(source):
    prices = {cid: cents(v) for cid, v in source["current"]["prices"].items()}
    if not prices or any(v is None for v in prices.values()):
        return None
    low = min(prices.values())
    return sorted(cid for cid, value in prices.items() if value == low)


def history_statistics(source):
    records = source.get("support")
    counts = Counter(h.get("purchased") for h in records or [])
    price_n = price_d = ad_n = ad_d = 0
    for h in records or []:
        p = h.get("purchased")
        prices = {cid: cents(v) for cid, v in h["prices"].items()}
        if p in prices and prices and all(v is not None for v in prices.values()):
            price_d += 1
            price_n += prices[p] == min(prices.values())
        flag = h["advertised"].get(p)
        if p is not None and flag is not None:
            ad_d += 1
            ad_n += flag is True
    return {"purchase_counts": dict(sorted((k, v) for k, v in counts.items() if k is not None)),
            "among_cheapest": [price_n, price_d], "purchased_advertised": [ad_n, ad_d]}


def semantic_records(source):
    records = []
    for h in source.get("support") or []:
        records.append(json.dumps({"purchased": h["purchased"], "prices": {k: canonical_price(v) for k, v in h["prices"].items()},
                                   "advertised": h["advertised"]}, sort_keys=True))
    return tuple(sorted(records))


def association_edit(source, field):
    support = source.get("support") or []
    if not 2 <= len(support) <= 8:
        return None, {"skip_reason": "Requires 2..8 support records for complete enumeration (max 40320 assignments)"}
    if any(h["purchased"] is None or any(v is None for v in h[field].values()) for h in support):
        return None, {"skip_reason": "Purchase or required historical offer field unavailable"}
    vectors = [h[field] for h in support]
    if len({json.dumps(v, sort_keys=True) for v in vectors}) == 1:
        return None, {"skip_reason": "Historical offer vectors never vary"}
    metric = "among_cheapest" if field == "prices" else "purchased_advertised"
    baseline = history_statistics(source)[metric]
    seen, feasible, choices = set(), 0, []
    for assignment in permutations(range(len(support))):
        changed = deepcopy(source)
        for index, donor in enumerate(assignment):
            changed["support"][index][field] = deepcopy(vectors[donor])
        signature = semantic_records(changed)
        if signature in seen:
            continue
        seen.add(signature)
        feasible += 1
        value = history_statistics(changed)[metric]
        if value[1] == baseline[1] and value[0] != baseline[0]:
            choices.append((-abs(value[0] - baseline[0]), assignment, changed, value))
    detail = {"unique_unordered_assignments": feasible, "association_before": baseline, "metric": metric,
              "skip_reason": None}
    if not choices:
        return None, {**detail, "skip_reason": "Uninformative: every feasible assignment has the same association"}
    _, assignment, changed, value = min(choices, key=lambda item: item[:2])
    return changed, {**detail, "donor_support_ids": [support[i]["id"] for i in assignment], "association_after": value}


def identity_presentation(source):
    ids = [c["id"] for c in source["candidates"]]
    return {"order": ids, "answer_mapping": {cid: cid for cid in ids}}


def model_inputs(source, presentation):
    mapping = presentation["answer_mapping"]
    candidates = {c["id"]: c for c in source["candidates"]}
    if set(presentation["order"]) != set(candidates) or len(presentation["order"]) != len(candidates):
        raise ValueError("Presentation order is not a candidate permutation")
    if set(mapping) != set(candidates) or len(set(mapping.values())) != len(mapping):
        raise ValueError("Answer mapping is not a candidate bijection")
    remap = lambda vector: {mapping[cid]: value for cid, value in vector.items()}
    return {"candidates": [{"id": mapping[cid], "name": candidates[cid]["name"]} for cid in presentation["order"]],
            "current": {field: remap(values) for field, values in source["current"].items()},
            "support": None if source["support"] is None else [
                {"id": h["id"], "purchased": mapping.get(h["purchased"]), "prices": remap(h["prices"]),
                 "advertised": remap(h["advertised"])} for h in source["support"]]}


def flat_fields(source, presentation):
    values = {f"current.{field}.{cid}": value for field, vector in source["current"].items() for cid, value in vector.items()}
    for h in source.get("support") or []:
        values[f"{h['id']}.purchased"] = h["purchased"]
        for field in ("prices", "advertised"):
            values.update({f"{h['id']}.{field}.{cid}": value for cid, value in h[field].items()})
    values["presentation.order"] = presentation["order"]
    values["presentation.answer_mapping"] = presentation["answer_mapping"]
    return values


def patch_between(before, after, before_presentation, after_presentation):
    a, b = flat_fields(before, before_presentation), flat_fields(after, after_presentation)
    if set(a) != set(b):
        raise ValueError("An edit added/removed source fields")
    return [{"field": key, "before": a[key], "after": b[key]} for key in sorted(a) if a[key] != b[key]]


def plan_edit(source, family, bounds, price_variant):
    changed, presentation = deepcopy(source), identity_presentation(source)
    ids = sorted(presentation["answer_mapping"])
    detail = {"skip_reason": None}
    if family in HISTORY_FAMILIES and source["support"] is None:
        return None, presentation, {"skip_reason": "Household history NOT_PROVIDED in this condition"}
    if family == "CURRENT_PRICE":
        old_set = cheapest(source)
        if old_set is None:
            return None, presentation, {"skip_reason": "Current price unavailable"}
        options = []
        for cid in ids:
            value = cents(source["current"]["prices"][cid])
            proposed = [value + 1, value - 1] if price_variant == "preserve" else [min(cents(v) for v in source["current"]["prices"].values()) - 1]
            for new_value in proposed:
                if not bounds[0] <= new_value <= bounds[1] or new_value <= 0:
                    continue
                trial = deepcopy(source)
                trial["current"]["prices"][cid] = new_value / 100
                new_set = cheapest(trial)
                if (price_variant == "preserve" and new_set == old_set) or (
                        price_variant == "reverse" and cid not in old_set and new_set == [cid]):
                    options.append((trial, cid, new_set))
        if not options:
            return None, presentation, {"skip_reason": "No valid cent-valued price edit inside development bounds", "variant": price_variant}
        changed, cid, new_set = options[0]
        detail.update(variant=price_variant, candidate=cid, cheapest_before=old_set, cheapest_after=new_set)
    elif family == "CURRENT_ADVERTISING":
        cid = next((cid for cid in ids if source["current"]["advertised"].get(cid) is not None), None)
        if cid is None:
            return None, presentation, {"skip_reason": "No known current advertising flag"}
        changed["current"]["advertised"][cid] = not source["current"]["advertised"][cid]
    elif family == "SUPPORT_PURCHASE":
        if not source["support"] or len(ids) < 2:
            return None, presentation, {"skip_reason": "No support record or no alternative candidate"}
        index = min(range(len(source["support"])), key=lambda i: source["support"][i]["id"])
        old = source["support"][index]["purchased"]
        if old not in ids:
            return None, presentation, {"skip_reason": "Selected support purchase unavailable"}
        changed["support"][index]["purchased"] = ids[(ids.index(old) + 1) % len(ids)]
    elif family in ("HISTORICAL_PRICE_ASSOCIATION", "HISTORICAL_ADVERTISING_ASSOCIATION"):
        changed, detail = association_edit(source, "prices" if family == "HISTORICAL_PRICE_ASSOCIATION" else "advertised")
        return changed, presentation, detail
    elif family == "HISTORICAL_OFFER_REMOVAL":
        if not any(v is not None for h in source["support"] for field in ("prices", "advertised") for v in h[field].values()):
            return None, presentation, {"skip_reason": "Historical offers already unavailable"}
        for h in changed["support"]:
            for field in ("prices", "advertised"):
                h[field] = {cid: None for cid in h[field]}
    elif family == "PRODUCT_ORDER_CONTROL":
        if len(ids) < 2:
            return None, presentation, {"skip_reason": "Fewer than two candidates"}
        presentation["order"] = presentation["order"][1:] + presentation["order"][:1]
    elif family == "ANSWER_MAPPING_CONTROL":
        if len(ids) < 2:
            return None, presentation, {"skip_reason": "Fewer than two candidates"}
        presentation["answer_mapping"] = dict(zip(ids, ids[1:] + ids[:1]))
    else:
        raise ValueError(f"Unknown family: {family}")
    return changed, presentation, detail


def verify_edit(entry, bounds):
    before, after = entry["original_source"], entry["edited_source"]
    original_presentation = identity_presentation(before)
    presentation = entry["presentation"]
    patch = patch_between(before, after, original_presentation, presentation)
    if patch != entry["patch"]:
        raise ValueError("Recorded patch disagrees with edited sources")
    family = entry["family"]
    def allowed(field):
        if family == "CURRENT_PRICE": return field.startswith("current.prices.")
        if family == "CURRENT_ADVERTISING": return field.startswith("current.advertised.")
        if family == "SUPPORT_PURCHASE": return field.startswith("H") and field.endswith(".purchased")
        if family == "HISTORICAL_PRICE_ASSOCIATION": return field.startswith("H") and ".prices." in field
        if family == "HISTORICAL_ADVERTISING_ASSOCIATION": return field.startswith("H") and ".advertised." in field
        if family == "HISTORICAL_OFFER_REMOVAL": return field.startswith("H") and (".prices." in field or ".advertised." in field)
        if family == "PRODUCT_ORDER_CONTROL": return field == "presentation.order"
        if family == "ANSWER_MAPPING_CONTROL": return field == "presentation.answer_mapping"
        return False
    if any(not allowed(p["field"]) for p in patch):
        raise ValueError("Unrelated source field changed")
    if family in ("CURRENT_PRICE", "CURRENT_ADVERTISING", "SUPPORT_PURCHASE") and len(patch) != 1:
        raise ValueError("Single-field family must edit exactly one field")
    if family in ("ORIGINAL", "UNCHANGED_RERUN") and patch:
        raise ValueError("Baseline/rerun must be unchanged")
    if family == "CURRENT_PRICE":
        v = patch[0]["after"]
        if v <= 0 or Decimal(str(v)) * 100 != cents(v) or not bounds[0] <= cents(v) <= bounds[1]:
            raise ValueError("Price is not positive, cent-valued, and within development bounds")
        expected = entry["edit_details"]
        if cheapest(before) != expected["cheapest_before"] or cheapest(after) != expected["cheapest_after"]:
            raise ValueError("Cheapest/tie integrity failed")
        if expected["variant"] == "preserve" and cheapest(before) != cheapest(after):
            raise ValueError("Price edit did not preserve the complete cheapest set")
        if expected["variant"] == "reverse" and (len(cheapest(after)) != 1 or cheapest(after)[0] in cheapest(before)):
            raise ValueError("Price edit did not make another candidate uniquely cheapest")
    if family in ("HISTORICAL_PRICE_ASSOCIATION", "HISTORICAL_ADVERTISING_ASSOCIATION"):
        field = "prices" if family == "HISTORICAL_PRICE_ASSOCIATION" else "advertised"
        if sorted(json.dumps(h[field], sort_keys=True) for h in before["support"]) != sorted(json.dumps(h[field], sort_keys=True) for h in after["support"]):
            raise ValueError("Historical vectors were not preserved as complete vectors")
        if history_statistics(before)["purchase_counts"] != history_statistics(after)["purchase_counts"]:
            raise ValueError("Historical purchase counts changed during offer reassignment")
        metric = entry["edit_details"]["metric"]
        if (history_statistics(before)[metric] != entry["edit_details"]["association_before"]
                or history_statistics(after)[metric] != entry["edit_details"]["association_after"]
                or history_statistics(before)[metric] == history_statistics(after)[metric]):
            raise ValueError("Historical association contrast disagrees with the predeclared assignment")
    if family == "HISTORICAL_OFFER_REMOVAL" and any(p["after"] is not None for p in patch):
        raise ValueError("Offer removal must use null, never zero or false")
    inputs = model_inputs(after, presentation)
    regenerated = generate_observations(**inputs)
    if regenerated != entry["observations"] or build_joint_messages(regenerated, inputs["candidates"]) != entry["messages"]:
        raise ValueError("Facts/prompt were not regenerated from edited fields")
    # Decode all remapped source fields to the underlying products, before any model call.
    inverse = {answer: cid for cid, answer in presentation["answer_mapping"].items()}
    decoded_current = {field: {inverse[a]: v for a, v in vector.items()} for field, vector in inputs["current"].items()}
    if decoded_current != after["current"]:
        raise ValueError("Answer remapping changed product offers")
    for h, original in zip(inputs["support"] or [], after["support"] or []):
        if inverse.get(h["purchased"]) != original["purchased"] or any({inverse[a]: v for a, v in h[f].items()} != original[f] for f in ("prices", "advertised")):
            raise ValueError("Answer remapping changed support product information")
    if family in ("PRODUCT_ORDER_CONTROL", "ANSWER_MAPPING_CONTROL") and after != before:
        raise ValueError("Presentation control changed underlying source values")
    if set(after) != {"candidates", "current", "support"}:
        raise ValueError("Only allowlisted target-free input fields may enter pilot sources")
    return {"patch_verified": True, "unrelated_fields_fixed": True, "regenerated": True,
            "price_policy": PRICE_POLICY, "product_semantics_preserved": True, "target_excluded": True}


def implementation_hashes():
    root = Path(__file__).resolve().parents[1]
    files = ["choice_trust/development_pilot.py", "choice_trust/pilot_execution.py", "choice_trust/observations.py",
             "choice_trust/joint_observation.py", "choice_trust/explanation_annotation.py", "docs/EXPLANATION_ANNOTATION_GUIDE.md"]
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in files}


def plan_pilot(cases_path: Path, seed=42):
    development = [r for line in cases_path.read_text().splitlines() if (r := json.loads(line))["split"] == "development" and not r.get("synthetic")]
    # No target is accessed below or copied into the pilot inputs.
    prices = [cents(v) for r in development for v in r["query"]["prices"].values() if v is not None]
    prices += [cents(v) for r in development for h in r["support"] for v in h["prices"].values() if v is not None]
    bounds = [max(1, min(prices)), max(prices)]
    households = {}
    for r in sorted(development, key=lambda x: int(x["case_id"].removeprefix("row-"))):
        households.setdefault(r["household_id"], r)
    pool = list(households.values())
    random.Random(seed).shuffle(pool)
    ranked = []
    for r in pool:
        source = inputs_from_prepared_yogurt(r, with_history=True)
        if cheapest(source) is None or len(source["candidates"]) < 2:
            continue
        price, _ = association_edit(source, "prices")
        ads, _ = association_edit(source, "advertised")
        reverse, _, _ = plan_edit(source, "CURRENT_PRICE", bounds, "reverse")
        if reverse is None:
            continue
        ranked.append((int(price is not None) + int(ads is not None), r, source))
    ranked.sort(key=lambda x: -x[0])  # Stable sort retains seeded tie order.
    if len(ranked) < 2:
        raise ValueError("Fewer than two eligible development households")
    selected = ranked[:2]
    entries, selected_cases = [], []
    for index, (score, row, full_source) in enumerate(selected):
        selected_cases.append({"case_id": row["case_id"], "household_id": row["household_id"], "split": "development",
                               "availability_score": score, "price_variant": "preserve" if index == 0 else "reverse"})
        for condition in CONDITIONS:
            source = deepcopy(full_source)
            if condition == "no_history": source["support"] = None
            for family in ("ORIGINAL", "UNCHANGED_RERUN") + FAMILIES:
                if family in ("ORIGINAL", "UNCHANGED_RERUN"):
                    changed, presentation, details = deepcopy(source), identity_presentation(source), {"skip_reason": None}
                else:
                    changed, presentation, details = plan_edit(source, family, bounds, selected_cases[-1]["price_variant"])
                entry = {"call_id": f"{row['case_id']}__{condition}__{family}", "case_id": row["case_id"], "condition": condition,
                         "family": family, "original_source": source, "edit_details": details, "skip_reason": details["skip_reason"]}
                if changed is not None:
                    inputs = model_inputs(changed, presentation)
                    observations = generate_observations(**inputs)
                    entry.update(edited_source=changed, presentation=presentation, observations=observations,
                                 messages=build_joint_messages(observations, inputs["candidates"]),
                                 patch=patch_between(source, changed, identity_presentation(source), presentation),
                                 statistics_before=history_statistics(source), statistics_after=history_statistics(changed))
                    entry["integrity"] = verify_edit(entry, bounds)
                entries.append(entry)
    planned = sum(not e["skip_reason"] for e in entries)
    if planned > 32:
        raise ValueError("Predeclared plan exceeds 32 generation calls")
    annotation_ids = [e["call_id"] for e in entries if e["family"] == "ORIGINAL"]
    for selected_case in selected_cases:
        eligible = [e for e in entries if e["case_id"] == selected_case["case_id"] and not e["skip_reason"]]
        choice = next((e for e in eligible if e["family"] == "HISTORICAL_PRICE_ASSOCIATION"), None)
        if choice is None:
            choice = next((e for e in eligible if e["family"] == "CURRENT_PRICE" and e["condition"] == "with_history" and e["edit_details"].get("variant") == "reverse"), None)
        if choice: annotation_ids.append(choice["call_id"])
    return {"protocol_version": PROTOCOL_VERSION, "seed": seed, "development_source_sha256": sha256(cases_path.read_bytes()).hexdigest(),
            "observation_version": OBSERVATION_VERSION, "prompt_version": JOINT_PROMPT_VERSION, "registry": registry(),
            "price_policy": PRICE_POLICY, "development_price_bounds_cents": bounds,
            "bounds_source": "Canonical current and selected support prices belonging only to development households",
            "selection_rule": "First query by source row per development household; seed-shuffle households; prefer number of informative price/ad historical associations; require feasible price reversal; take first two",
            "selected_cases": selected_cases, "entries": entries, "annotation_call_ids": annotation_ids,
            "budgets": {"generation_cap": 32, "annotation_cap": 6, "planned_generations": planned, "planned_annotations": len(annotation_ids)},
            "joint_settings": JOINT_GENERATION_SETTINGS, "implementation_hashes": implementation_hashes(),
            "interpretation": "Development diagnostic only. Edited customer outcomes unknown; no accuracy or faithfulness score."}
