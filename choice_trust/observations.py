"""Deterministic, target-free factual observations for product-choice cases.

Inputs are candidates, current offers, and optional unordered support purchases.
Model-facing facts use dollars rounded to cents with ROUND_HALF_UP. Raw source
values and both source-based and display-based comparisons remain in audit data.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

OBSERVATION_VERSION = "compact-factual-observations-v2"
PRICE_POLICY = {
    "currency_assumption": "Supplied numeric prices are assumed USD dollar amounts for this experiment",
    "scale_factor": 1,
    "decimal_places": 2,
    "rounding": "Decimal(str(source_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)",
    "comparison_basis": "canonical rounded decimal amounts; displayed equal prices compare equal",
}


def canonical_price(value: Any, field: str = "price") -> str | None:
    parsed = _number(value, field)
    if parsed is None:
        return None
    with localcontext() as ctx:
        ctx.prec = max(28, len(parsed.as_tuple().digits) + abs(parsed.adjusted()) + 4)
        rounded = parsed.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(abs(rounded) if rounded == 0 else rounded, ".2f")



def _number(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field}: expected a number or null")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field}: invalid number") from exc
    if not result.is_finite():
        raise ValueError(f"{field}: nonfinite number")
    return result


def _flag(value: Any, field: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{field}: expected true, false, or null")
    return value


def _shown(value: Any) -> str:
    if value is None:
        return "NOT_PROVIDED"
    if isinstance(value, bool):
        return "advertised" if value else "not advertised"
    return str(value)


def _gap(value: Decimal) -> dict:
    return {"gap": float(value), "gap_decimal": str(value)}


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return "NOT_PROVIDED"
    return "0" if value == 0 else str(value)


def _prices(prices: dict, ids: list[str], prefix: str, *, canonical=False):
    raw = {cid: prices.get(cid) for cid in ids}
    parsed = {cid: _number(raw[cid], f"{prefix}.prices.{cid}") for cid in ids}
    if canonical:
        parsed = {cid: Decimal(canonical_price(raw[cid])) if raw[cid] is not None else None for cid in ids}
    return raw, parsed


def _known_keys(values: dict, ids: list[str], field: str) -> None:
    extra = set(values) - set(ids)
    if extra:
        raise ValueError(f"{field}: unknown candidate IDs {sorted(extra)}")


def _excluded(support: list[dict], reason_for):
    return [{"id": h["id"], "reason": reason_for(h)} for h in support if reason_for(h)]


def _generate_audit_observations(candidates: list[dict], current: dict,
                                 support: list[dict] | None = None, *, canonical=False) -> dict:
    """Return JSON-serializable observations and a text rendering.

    Each support entry has id, prices, advertised, purchased. Missing values
    may be null or absent; omitted support differs from an empty support list.
    No target/outcome argument exists in this API.
    """
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("candidates: expected at least one product")
    ids = [c.get("id") for c in candidates]
    if any(not isinstance(cid, str) or not cid for cid in ids) or len(set(ids)) != len(ids):
        raise ValueError("candidates: IDs must be distinct nonempty strings")
    if any(not isinstance(c.get("name"), str) for c in candidates):
        raise ValueError("candidates: every name must be a string")
    if not isinstance(current, dict) or not isinstance(current.get("prices"), dict) or not isinstance(current.get("advertised"), dict):
        raise ValueError("current: prices and advertised must be objects")
    _known_keys(current["prices"], ids, "current.prices")
    _known_keys(current["advertised"], ids, "current.advertised")
    if support is not None and not isinstance(support, list):
        raise ValueError("support: expected a list or null")
    support = None if support is None else list(support)
    names = {c["id"]: c["name"] for c in candidates}
    label = lambda cid: f"{cid} ({names[cid]})"
    observations: list[dict] = []
    used: set[str] = set()

    def add(oid, group, kind, value, statement, status, sources=(), dependencies=()):
        if oid in used:
            raise ValueError(f"observation ID collision: {oid}")
        used.add(oid)
        observations.append(dict(id=oid, group=group, type=kind, value=value,
                                 statement=statement, status=status,
                                 sources=list(dict.fromkeys(sources)),
                                 dependencies=list(dict.fromkeys(dependencies))))

    price_raw, prices = _prices(current["prices"], ids, "current", canonical=canonical)
    ads = {cid: _flag(current["advertised"].get(cid), f"current.advertised.{cid}") for cid in ids}
    price_refs = [f"current.prices.{cid}" for cid in ids]
    ad_refs = [f"current.advertised.{cid}" for cid in ids]
    for cid in ids:
        ref = f"current.prices.{cid}"
        add(f"P_{cid}", "current_prices", "price", price_raw[cid],
            f"Current price of {label(cid)}: {_shown(price_raw[cid])} (original dataset units).",
            "available" if prices[cid] is not None else "unavailable", [ref])
    known = [cid for cid in ids if prices[cid] is not None]
    tiers: list[list[str]] = []
    for cid in sorted(known, key=lambda c: (prices[c], ids.index(c))):
        if not tiers or prices[cid] != prices[tiers[-1][0]]:
            tiers.append([])
        tiers[-1].append(cid)
    missing = [cid for cid in ids if prices[cid] is None]
    order_text = "; ".join(" = ".join(label(c) for c in tier) for tier in tiers)
    if missing:
        order_text = (order_text or "NOT_PROVIDED") + "; unavailable: " + ", ".join(label(c) for c in missing)
    add("OBS:current:price_order", "current_prices", "price_order",
        {"tiers": tiers, "missing": missing}, f"Current price order, lowest to highest among supplied prices: {order_text}.",
        "available" if not missing else "partial" if known else "unavailable",
        price_refs, [f"P_{cid}" for cid in ids])
    cheapest = tiers[0] if tiers and not missing else None
    add("OBS:current:cheapest", "current_prices", "cheapest", cheapest,
        ("Current tied cheapest candidates: " if cheapest and len(cheapest) > 1 else "Current cheapest candidate: ")
        + (", ".join(label(c) for c in cheapest) if cheapest else "NOT_PROVIDED (one or more prices unavailable)") + ".",
        "available" if cheapest is not None else "unavailable", price_refs,
        ["OBS:current:price_order"])
    minimum = prices[cheapest[0]] if cheapest else None
    for cid in ids:
        gap = prices[cid] - minimum if minimum is not None else None
        add(f"OBS:current:gap:{cid}", "current_prices", "price_gap",
            _gap(gap) if gap is not None else None,
            f"Current price gap of {label(cid)} above the minimum: {_decimal_text(gap)} (original dataset units).",
            "available" if gap is not None else "unavailable", price_refs,
            [f"P_{cid}", "OBS:current:cheapest"])

    for cid in ids:
        add(f"F_{cid}", "current_advertising", "advertising", ads[cid],
            f"Current advertising for {label(cid)}: {_shown(ads[cid])}.",
            "available" if ads[cid] is not None else "unavailable", [f"current.advertised.{cid}"])
    advertised = [cid for cid in ids if ads[cid] is True]
    unknown_ads = [cid for cid in ids if ads[cid] is None]
    ad_statement = ("Advertised candidates: " + ", ".join(label(c) for c in advertised) + ".") if advertised else (
        "None of the candidates is advertised." if not unknown_ads else "Advertised candidates: NOT_PROVIDED (some flags unavailable).")
    if unknown_ads:
        ad_statement += " Unavailable flags: " + ", ".join(label(c) for c in unknown_ads) + "."
    add("OBS:current:advertised", "current_advertising", "advertised_candidates",
        {"known_advertised": advertised, "unknown": unknown_ads,
         "none_advertised": False if advertised else None if unknown_ads else True},
        ad_statement, "available" if not unknown_ads else "unavailable" if len(unknown_ads) == len(ids) else "partial", ad_refs,
        [f"F_{cid}" for cid in ids])

    if support is None:
        add("OBS:support:availability", "support_purchases", "support_availability", None,
            "Support observations: NOT_PROVIDED.", "unavailable")
        add("OBS:history:availability", "historical_offers", "history_availability", None,
            "Historical offers: NOT_PROVIDED.", "unavailable")
        return {"version": OBSERVATION_VERSION, "candidates": candidates, "observations": observations,
                "text": _render_audit_observations(observations)}

    support_ids = []
    for h in support:
        if not isinstance(h, dict) or not isinstance(h.get("id"), str) or not h["id"]:
            raise ValueError("support: every observation needs a nonempty id")
        hid = h["id"]
        if hid in support_ids:
            raise ValueError(f"support: duplicate id {hid}")
        support_ids.append(hid)
        if not isinstance(h.get("prices"), dict) or not isinstance(h.get("advertised"), dict):
            raise ValueError(f"{hid}: prices and advertised must be objects")
        _known_keys(h["prices"], ids, f"{hid}.prices")
        _known_keys(h["advertised"], ids, f"{hid}.advertised")
        if h.get("purchased") is not None and h["purchased"] not in ids:
            raise ValueError(f"{hid}.purchased: unknown candidate {h['purchased']!r}")
    purchase_refs = [f"{hid}.purchased" for hid in support_ids]
    support_id_refs = [f"{hid}.id" for hid in support_ids]
    add("OBS:support:availability", "support_purchases", "support_availability", len(support),
        f"Number of supplied unordered separate support observations: {len(support)}.", "available", support_id_refs)
    add("OBS:history:availability", "historical_offers", "history_availability", len(support),
        f"Historical offer records supplied: {len(support)}.", "available", support_id_refs)

    details = {}
    for h in support:
        hid = h["id"]
        purchased = h.get("purchased")
        refs = [f"{hid}.id", f"{hid}.purchased"] + [f"{hid}.prices.{cid}" for cid in ids] + [f"{hid}.advertised.{cid}" for cid in ids]
        raw, parsed = _prices(h["prices"], ids, hid, canonical=canonical)
        flags = {cid: _flag(h["advertised"].get(cid), f"{hid}.advertised.{cid}") for cid in ids}
        add(f"{hid}:purchase", "support_purchases", "purchase", purchased,
            f"{hid} purchased: {label(purchased) if purchased is not None else 'NOT_PROVIDED'}.",
            "available" if purchased is not None else "unavailable", [f"{hid}.purchased"])
        offer_text = "; ".join(f"{label(cid)} price {_shown(raw[cid])}, {_shown(flags[cid])}" for cid in ids)
        add(hid, "historical_offers", "historical_offer",
            {"prices": raw, "advertised": flags, "purchased": purchased},
            f"{hid}: {offer_text}; purchased {label(purchased) if purchased is not None else 'NOT_PROVIDED'}.",
            "available" if purchased is not None and all(v is not None for v in parsed.values()) and all(v is not None for v in flags.values()) else "partial",
            refs, [f"{hid}:purchase"])
        complete_prices = purchased is not None and all(v is not None for v in parsed.values())
        known_cheaper = (purchased is not None and parsed[purchased] is not None and
                         any(v is not None and v < parsed[purchased] for cid, v in parsed.items() if cid != purchased))
        if complete_prices:
            low = min(parsed.values())
            tied = [cid for cid in ids if parsed[cid] == low]
            among = purchased in tied
            gap = parsed[purchased] - low
            cheaper = not among
        else:
            tied = None
            among = False if known_cheaper else None
            gap = None
            cheaper = True if known_cheaper else None
        ad = flags[purchased] if purchased is not None else None
        price_sources = [f"{hid}.purchased"] + [f"{hid}.prices.{cid}" for cid in ids]
        add(f"{hid}:cheapest", "historical_offers", "purchased_among_cheapest",
            {"among_cheapest": among, "tied_cheapest": tied},
            f"{hid}: purchased candidate was {'among the cheapest' if among else 'not among the cheapest' if among is False else 'NOT_PROVIDED for cheapest comparison'}"
            + ((f"; tied cheapest: {', '.join(label(c) for c in tied)}." if len(tied) > 1 else
                f"; cheapest: {label(tied[0])}.") if tied is not None else
               " (complete cheapest set NOT_PROVIDED)."),
            "available" if among is not None else "unavailable", price_sources, [hid, f"{hid}:purchase"])
        add(f"{hid}:gap", "historical_offers", "purchased_price_gap",
            _gap(gap) if gap is not None else None,
            f"{hid}: purchased candidate's price gap above minimum: {_decimal_text(gap)} (original dataset units).",
            "available" if gap is not None else "unavailable", price_sources, [f"{hid}:cheapest"])
        add(f"{hid}:advertised", "historical_offers", "purchased_advertised", ad,
            f"{hid}: purchased candidate was {_shown(ad)}.",
            "available" if ad is not None else "unavailable",
            [f"{hid}.purchased"] + ([f"{hid}.advertised.{purchased}"] if purchased else [f"{hid}.advertised.{cid}" for cid in ids]),
            [hid, f"{hid}:purchase"])
        details[hid] = dict(purchased=purchased, among=among, gap=gap, advertised=ad,
                            cheaper=cheaper, complete_prices=complete_prices)

    valid_purchase = [h for h in support if details[h["id"]]["purchased"] is not None]
    excluded_purchase = _excluded(support, lambda h: "purchase_not_provided" if details[h["id"]]["purchased"] is None else None)
    denominator = len(valid_purchase)
    for cid in ids:
        n = sum(details[h["id"]]["purchased"] == cid for h in valid_purchase)
        add(f"OBS:support:count:{cid}", "support_purchases", "purchase_count_share",
            {"candidate": cid, "count": n, "numerator": n, "denominator": denominator,
             "share": n / denominator if denominator else None, "excluded": excluded_purchase},
            f"{label(cid)} was purchased in {n} of the {denominator} eligible supplied support observations"
            + (f"; excluded: {', '.join(x['id'] + ' (' + x['reason'] + ')' for x in excluded_purchase)}." if excluded_purchase else "."),
            "available" if denominator else "partial", purchase_refs,
            [f"{hid}:purchase" for hid in support_ids])
    counts = {cid: sum(details[h["id"]]["purchased"] == cid for h in valid_purchase) for cid in ids}
    leaders = [cid for cid in ids if counts[cid] == max(counts.values())] if denominator else None
    add("OBS:support:most_frequent", "support_purchases", "most_frequent_purchase",
        {"candidates": leaders, "eligible_denominator": denominator, "excluded": excluded_purchase},
        (("Most frequently purchased " + ("tied candidates: " if len(leaders) > 1 else "candidate: ") + ", ".join(label(c) for c in leaders)
          if leaders else "Most frequently purchased candidate: NOT_PROVIDED")
         + f"; eligible support observations: {denominator}"
         + (f"; excluded: {', '.join(x['id'] + ' (' + x['reason'] + ')' for x in excluded_purchase)}." if excluded_purchase else ".")),
        "available" if leaders else "unavailable", purchase_refs,
        [f"OBS:support:count:{cid}" for cid in ids])

    def aggregate(oid, kind, predicate, eligible, reason, wording, dependencies):
        included = [h for h in support if eligible(details[h["id"]])]
        excluded = _excluded(support, lambda h: None if eligible(details[h["id"]]) else reason(details[h["id"]]))
        n = sum(bool(predicate(details[h["id"]])) for h in included)
        d = len(included)
        add(oid, "historical_offers", kind,
            {"numerator": n, "eligible_denominator": d, "excluded": excluded},
            f"{wording} in {n} of {d} eligible support observations"
            + (f"; excluded: {', '.join(x['id'] + ' (' + x['reason'] + ')' for x in excluded)}." if excluded else "."),
            "available" if d else "unavailable",
            [ref for hid in support_ids for ref in next(o for o in observations if o["id"] ==
             (f"{hid}:advertised" if kind == "purchased_advertised_count" else f"{hid}:cheapest"))["sources"]],
            dependencies)

    price_reason = lambda d: "purchase_not_provided" if d["purchased"] is None else "one_or_more_prices_not_provided"
    aggregate("OBS:history:cheapest_count", "purchased_among_cheapest_count",
              lambda d: d["among"], lambda d: d["among"] is not None, price_reason,
              "Purchased candidate was among the cheapest",
              [f"{hid}:cheapest" for hid in support_ids])
    aggregate("OBS:history:advertised_count", "purchased_advertised_count",
              lambda d: d["advertised"], lambda d: d["advertised"] is not None,
              lambda d: "purchase_not_provided" if d["purchased"] is None else "purchased_advertising_not_provided",
              "Purchased candidate was advertised", [f"{hid}:advertised" for hid in support_ids])
    for cid in (cid for cid in ids if counts[cid]):
        own = [h for h in support if details[h["id"]]["purchased"] == cid]
        eligible = [h for h in own if details[h["id"]]["cheaper"] is not None]
        excluded = [{"id": h["id"], "reason":
                     "purchase_not_provided" if details[h["id"]]["purchased"] is None else
                     "different_purchased_brand" if details[h["id"]]["purchased"] != cid else
                     "purchased_price_or_comparison_not_provided"}
                    for h in support if h not in eligible]
        n = sum(details[h["id"]]["cheaper"] for h in eligible)
        add(f"OBS:history:cheaper_alternative:{cid}", "historical_offers", "strictly_cheaper_alternative_count",
            {"candidate": cid, "numerator": n, "eligible_denominator": len(eligible), "excluded": excluded},
            (f"When {label(cid)} was purchased, a strictly cheaper alternative existed in {n} of {len(eligible)} eligible observations"
             if eligible else f"When {label(cid)} was purchased, strictly cheaper alternative count: NOT_PROVIDED (0 eligible observations)")
            + (f"; excluded: {', '.join(x['id'] + ' (' + x['reason'] + ')' for x in excluded)}." if excluded else "."),
            "available" if eligible else "unavailable",
            purchase_refs + [f"{h['id']}.prices.{c}" for h in own for c in ids],
            [f"{h['id']}:cheapest" for h in own])
    return {"version": OBSERVATION_VERSION, "candidates": candidates, "observations": observations,
            "text": _render_audit_observations(observations)}


def _render_audit_observations(observations: list[dict]) -> str:
    """Render only the generated statements, preserving IDs and group boundaries."""
    return "\n".join(f"[{o['id']}] {o['statement']}" for o in observations)


def render_observations(observations: list[dict], *, history_provided: bool | None = None) -> str:
    """Render each exposed source record once, under its sole concept group."""
    if history_provided is None:
        history_provided = any(o["group"] == "HOUSEHOLD_HISTORY" for o in observations)
    sections = []
    for group in ("CURRENT_PRICES", "CURRENT_ADVERTISING", "HOUSEHOLD_HISTORY"):
        rows = [o for o in observations if o["group"] == group]
        if group == "HOUSEHOLD_HISTORY" and not history_provided:
            sections.append("Household history: NOT_PROVIDED")
        else:
            sections.append(group + "\n" + ("\n".join(
                f"[{o['id']}] {o['statement']}" for o in rows) or "Supplied support records: 0."))
    return "\n\n".join(sections)


def generate_observations(candidates: list[dict], current: dict,
                          support: list[dict] | None = None) -> dict:
    """Expose compact facts; keep summaries, raw values and provenance in audit.

    The three groups partition source fields, without asserting statistical
    independence. A historical citation identifies a whole linked record; it
    does not establish that every field influenced the answer.
    """
    from copy import deepcopy

    candidates, current, support = deepcopy((candidates, current, support))
    raw_audit = _generate_audit_observations(candidates, current, support)
    visible_audit = _generate_audit_observations(candidates, current, support, canonical=True)
    ids = [c["id"] for c in candidates]
    observations, assignments, source_values = [], {}, {}

    def dollar(value):
        return "NOT_PROVIDED" if value is None else "$" + value

    def flag(value):
        return "NOT_PROVIDED" if value is None else "ADVERTISED" if value else "NOT_ADVERTISED"

    def add(oid, group, kind, value, statement, sources):
        missing = sum(source_values[r] is None for r in sources)
        observations.append(dict(id=oid, group=group, type=kind, value=value,
                                 statement=statement, status="unavailable" if missing == len(sources)
                                 else "partial" if missing else "available",
                                 sources=sources, dependencies=[]))
        for ref in sources:
            if ref in assignments:
                raise ValueError(f"source field assigned more than once: {ref}")
            assignments[ref] = group

    for cid in ids:
        ref = f"current.prices.{cid}"
        raw = current["prices"].get(cid)
        source_values[ref] = raw
        value = canonical_price(raw, ref)
        add(f"P_{cid}", "CURRENT_PRICES", "price", value,
            f"{cid}: {dollar(value)}", [ref])
    for cid in ids:
        ref = f"current.advertised.{cid}"
        value = current["advertised"].get(cid)
        source_values[ref] = value
        add(f"F_{cid}", "CURRENT_ADVERTISING", "advertising", value,
            f"{cid}: {flag(value)}", [ref])
    for h in support or []:
        hid = h["id"]
        value = {"purchased": h.get("purchased"),
                 "prices": {cid: canonical_price(h["prices"].get(cid)) for cid in ids},
                 "advertised": {cid: h["advertised"].get(cid) for cid in ids}}
        refs = [f"{hid}.purchased"]
        source_values[refs[0]] = value["purchased"]
        for field in ("prices", "advertised"):
            for cid in ids:
                ref = f"{hid}.{field}.{cid}"
                refs.append(ref)
                source_values[ref] = h[field].get(cid)
        prices = ", ".join(f"{cid}:{dollar(value['prices'][cid])}" for cid in ids)
        ads = ", ".join(f"{cid}:{flag(value['advertised'][cid])}" for cid in ids)
        add(hid, "HOUSEHOLD_HISTORY", "historical_offer", value,
            f"Purchased={value['purchased'] if value['purchased'] is not None else 'NOT_PROVIDED'}; "
            f"prices={{{prices}}}; advertising={{{ads}}}.", refs)
    old_groups = {"current_prices": "CURRENT_PRICES", "current_advertising": "CURRENT_ADVERTISING",
                  "support_purchases": "HOUSEHOLD_HISTORY", "historical_offers": "HOUSEHOLD_HISTORY"}
    for audit in (raw_audit, visible_audit):
        for o in audit["observations"]:
            o["group"] = old_groups[o["group"]]
            o["concept_groups"] = sorted({assignments[r] for r in o["sources"] if r in assignments} or {o["group"]})
    return {
        "version": OBSERVATION_VERSION, "candidates": candidates,
        "configuration": {"price_policy": dict(PRICE_POLICY),
                          "concept_groups": ["CURRENT_PRICES", "CURRENT_ADVERTISING", "HOUSEHOLD_HISTORY"],
                          "grouping_claim": "Source-field partition; no statistical independence asserted",
                          "historical_citation_scope": "Linked record, not proof every field influenced the answer"},
        "history_provided": support is not None,
        "observations": observations,
        "text": render_observations(observations, history_provided=support is not None),
        "source_group_assignment": assignments,
        "evidence_group_assignment": {o["id"]: o["group"] for o in observations},
        "audit": {"source_values": source_values,
                  "source_comparisons": raw_audit["observations"],
                  "model_visible_comparisons": visible_audit["observations"]},
    }


def inputs_from_prepared_yogurt(case: dict, *, with_history: bool) -> dict:
    """Map the existing prepared-case schema without reading its target."""
    if not isinstance(case.get("brand_map"), dict):
        raise ValueError("prepared case: brand_map is required")
    if not isinstance(case.get("query"), dict):
        raise ValueError("prepared case: query is required")
    for field in ("prices", "ads"):
        if not isinstance(case["query"].get(field), dict):
            raise ValueError(f"prepared case: query.{field} is required")
    if with_history and not isinstance(case.get("support"), list):
        raise ValueError("prepared case: support list is required for with_history")
    candidates = [{"id": cid, "name": name} for cid, name in case["brand_map"].items()]
    current = {"prices": dict(case["query"]["prices"]),
               "advertised": dict(case["query"]["ads"])}
    support = None
    if with_history:
        support = []
        for index, h in enumerate(case["support"]):
            if not isinstance(h, dict):
                raise ValueError(f"prepared case: support[{index}] must be an object")
            for field in ("evidence_id", "prices", "ads", "choice"):
                if field not in h:
                    raise ValueError(f"prepared case: support[{index}].{field} is required")
            support.append({"id": h["evidence_id"], "prices": h["prices"],
                            "advertised": h["ads"], "purchased": h["choice"]})
    return {"candidates": candidates, "current": current, "support": support}
