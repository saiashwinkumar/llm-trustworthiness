#!/usr/bin/env python3
"""Analyze recorded customer-choice predictions; never invent experimental results.

Run from the project directory::

    python analyze.py --predictions outputs/predictions.jsonl \
        --cases data/processed/cases.jsonl --faithfulness outputs/faithfulness.jsonl

The last complete record wins for each (case_id, condition), supporting resumed
runs. Confidence intervals resample whole households, not individual occasions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import logsumexp, softmax


BRANDS = ("A", "B", "C", "D")
EPS = 1e-12
DEMO_NOTICE = "SYNTHETIC DEMO — NOT LLM RESULTS"
FAITH_METRICS = (
    "comprehensiveness", "sufficiency_gap", "keep_only_absolute_change", "random_comprehensiveness_mean",
    "random_sufficiency_gap_mean", "removal_advantage", "margin_drop",
    "random_margin_drop_mean", "margin_advantage", "counterfactual_agreement",
    "order_flip",
)


def read_jsonl(path: Path, warnings: list[str], optional: bool = False) -> list[dict]:
    if not path.exists():
        if optional:
            warnings.append(f"Optional input absent: {path}.")
            return []
        raise ValueError(f"Input does not exist: {path}")
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    records = []
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            if index == len(lines) - 1 and not content.endswith("\n"):
                warnings.append(f"Ignored incomplete final JSONL record in {path}.")
                continue
            raise ValueError(f"Invalid JSON at {path}:{index + 1}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Expected an object at {path}:{index + 1}.")
        records.append(row)
    return records


def deduplicate(rows: list[dict], fields: tuple[str, ...], warnings: list[str], name: str) -> list[dict]:
    latest = {}
    for row in rows:
        if any(field not in row for field in fields):
            raise ValueError(f"{name} record missing key(s) {fields}: {row.get('case_id', '?')}")
        key = tuple(str(row[field]) for field in fields)
        latest[key] = row
    repeated = len(rows) - len(latest)
    if repeated:
        warnings.append(f"{name}: retained last records for {repeated} repeated key(s).")
    return list(latest.values())


def finite_number(value: Any) -> bool:
    return isinstance(value, (int, float, np.number)) and math.isfinite(float(value))


def mean_ci(values: list[float], households: list[str], repetitions: int, seed: int) -> dict:
    """Occasion-weighted mean, with a household cluster bootstrap interval."""
    if not values:
        return {"mean": None, "n": 0, "households": 0, "ci95": None}
    values_array = np.asarray(values, dtype=float)
    unique, inverse = np.unique(np.asarray(households, dtype=str), return_inverse=True)
    result = {"mean": float(values_array.mean()), "n": len(values),
              "households": len(unique), "ci95": None}
    if len(unique) < 2 or repetitions < 1:
        return result
    sums = np.bincount(inverse, weights=values_array)
    counts = np.bincount(inverse)
    rng = np.random.default_rng(seed)
    estimates = []
    # Bound temporary memory for large household counts.
    batch_size = max(1, min(100, 1_000_000 // len(unique)))
    for start in range(0, repetitions, batch_size):
        sampled = rng.integers(0, len(unique), size=(min(batch_size, repetitions - start), len(unique)))
        estimates.extend((sums[sampled].sum(axis=1) / counts[sampled].sum(axis=1)).tolist())
    result["ci95"] = [float(x) for x in np.quantile(estimates, [0.025, 0.975])]
    return result


def canonical_prediction(row: dict, cases: dict[str, dict]) -> dict:
    case_id = str(row["case_id"])
    case = cases.get(case_id, {})
    target = row.get("target", case.get("target"))
    if target not in BRANDS:
        raise ValueError(f"Unknown target for {case_id}: {target!r}.")
    if case and target != case.get("target"):
        raise ValueError(f"Prediction/case target mismatch for {case_id}.")
    raw = row.get("probabilities")
    if not isinstance(raw, dict) or set(raw) != set(BRANDS):
        raise ValueError(f"{case_id}: probabilities must contain exactly A, B, C, D.")
    if not all(finite_number(raw[key]) and float(raw[key]) >= 0 for key in BRANDS):
        raise ValueError(f"{case_id}: probabilities must be finite nonnegative numbers.")
    p = np.asarray([raw[key] for key in BRANDS], dtype=float)
    if p.sum() <= 0:
        raise ValueError(f"{case_id}: probabilities sum to zero.")
    p /= p.sum()
    prediction = row.get("prediction", BRANDS[int(p.argmax())])
    if prediction not in BRANDS or p[BRANDS.index(prediction)] < p.max() - 1e-7:
        raise ValueError(f"{case_id}: prediction is not a maximum-probability label.")
    split = str(row.get("split", case.get("split", "unknown")))
    if case and split != case.get("split"):
        raise ValueError(f"Prediction/case split mismatch for {case_id}.")
    household = str(row.get("household_id", case.get("household_id", "")))
    if not household:
        raise ValueError(f"Missing household_id for {case_id}.")
    if case and household != str(case.get("household_id")):
        raise ValueError(f"Prediction/case household mismatch for {case_id}.")
    return {**row, "case_id": case_id, "household_id": household, "split": split,
            "target": target, "prediction": prediction,
            "probabilities": dict(zip(BRANDS, p.tolist()))}


def arrays(rows: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    p = np.asarray([[row["probabilities"][key] for key in BRANDS] for row in rows])
    y = np.asarray([BRANDS.index(row["target"]) for row in rows])
    pred = np.asarray([BRANDS.index(row["prediction"]) for row in rows])
    return p, y, pred


def prediction_metrics(rows: list[dict], repetitions: int, seed: int) -> dict:
    if not rows:
        return {"n": 0, "households": 0, "accuracy": None, "accuracy_ci95": None,
                "mrr": None, "log_loss": None, "brier_sum": None,
                "ece_5": None, "reliability": [], "error_vs_coverage": []}
    p, y, pred = arrays(rows)
    correct = pred == y
    confidence = p[np.arange(len(rows)), pred]
    # Ties receive their average rank, avoiding arbitrary label-order credit.
    target_p = p[np.arange(len(rows)), y]
    ranks = 1 + (p > target_p[:, None] + 1e-12).sum(axis=1)
    ranks = ranks + ((np.abs(p - target_p[:, None]) <= 1e-12).sum(axis=1) - 1) / 2
    one_hot = np.eye(len(BRANDS))[y]
    bins = []
    ece = 0.0
    for index in range(5):
        lo, hi = index / 5, (index + 1) / 5
        mask = (confidence >= lo) & ((confidence < hi) if index < 4 else (confidence <= hi))
        n = int(mask.sum())
        avg_conf = float(confidence[mask].mean()) if n else None
        avg_acc = float(correct[mask].mean()) if n else None
        bins.append({"lower": lo, "upper": hi, "n": n,
                     "confidence": avg_conf, "accuracy": avg_acc})
        if n:
            ece += n / len(rows) * abs(avg_acc - avg_conf)
    curve = []
    for desired in np.linspace(0.1, 1.0, 19):
        cutoff = np.sort(confidence)[::-1][max(0, math.ceil(desired * len(rows)) - 1)]
        kept = confidence >= cutoff  # Retain entire ties at the cutoff.
        point = {"coverage": float(kept.mean()), "error": float(1 - correct[kept].mean()),
                 "threshold": float(cutoff), "n": int(kept.sum())}
        if not curve or point["n"] != curve[-1]["n"]:
            curve.append(point)
    ci = mean_ci(correct.astype(float).tolist(), [r["household_id"] for r in rows], repetitions, seed)
    return {"n": len(rows), "households": ci["households"], "accuracy": float(correct.mean()),
            "accuracy_ci95": ci["ci95"], "mrr": float((1 / ranks).mean()),
            "log_loss": float(-np.log(np.clip(target_p, EPS, 1)).mean()),
            "brier_sum": float(((p - one_hot) ** 2).sum(axis=1).mean()),
            "ece_5": float(ece), "reliability": bins, "error_vs_coverage": curve}


def fit_temperature(validation: list[dict]) -> dict:
    if not validation:
        return {"temperature": None, "n": 0, "status": "No validation predictions; calibration skipped."}
    p, y, _ = arrays(validation)
    log_p = np.log(np.clip(p, EPS, 1))

    def objective(log_temperature: float) -> float:
        scores = log_p / math.exp(log_temperature)
        return float((logsumexp(scores, axis=1) - scores[np.arange(len(y)), y]).mean())

    result = minimize_scalar(objective, bounds=(-4.0, 4.0), method="bounded")
    if not result.success or not finite_number(result.fun):
        return {"temperature": None, "n": len(validation), "status": "Calibration optimizer failed."}
    return {"temperature": float(math.exp(result.x)), "n": len(validation),
            "status": "Fitted on validation only.", "validation_log_loss": float(result.fun),
            "boundary_fit": bool(abs(result.x) > 3.95)}


def apply_temperature(rows: list[dict], temperature: float) -> list[dict]:
    calibrated = []
    for row in rows:
        p = np.asarray([row["probabilities"][key] for key in BRANDS])
        transformed = softmax(np.log(np.clip(p, EPS, 1)) / temperature)
        calibrated.append({**row, "probabilities": dict(zip(BRANDS, transformed.tolist()))})
    return calibrated


def valid_prices(case: dict) -> bool:
    prices = case.get("query", {}).get("prices", {})
    return all(finite_number(prices.get(key)) for key in BRANDS)


def support_counts(case: dict) -> Counter:
    return Counter(item.get("choice") for item in case.get("support", []) if item.get("choice") in BRANDS)


def probability_row(case: dict, condition: str, probabilities: np.ndarray) -> dict:
    return {"case_id": str(case["case_id"]), "household_id": str(case["household_id"]),
            "split": case["split"], "condition": condition, "target": case["target"],
            "prediction": BRANDS[int(probabilities.argmax())],
            "probabilities": dict(zip(BRANDS, probabilities.tolist()))}


def baselines(test_rows: list[dict], cases: dict[str, dict], development: list[dict],
              condition: str, repetitions: int, seed: int) -> dict:
    matched = [cases[r["case_id"]] for r in test_rows if r["case_id"] in cases]
    result = {"matched_test_cases": len(matched)}
    eligible = [case for case in matched if valid_prices(case)]
    cheapest_values = [float(BRANDS[int(np.argmin([case["query"]["prices"][k] for k in BRANDS]))]
                             == case["target"]) for case in eligible]
    result["cheapest"] = {"accuracy": mean_ci(cheapest_values,
        [str(c["household_id"]) for c in eligible], repetitions, seed),
        "tie_rule": "Alphabetically first label among equal lowest prices; hard-choice accuracy only."}
    if condition == "with_history":
        eligible_support = [case for case in matched if sum(support_counts(case).values())]
        support_rows = []
        for case in eligible_support:
            counts = support_counts(case)
            p = np.asarray([counts[key] + 1 for key in BRANDS], dtype=float)
            support_rows.append(probability_row(case, condition, p / p.sum()))
        result["support_most_common"] = prediction_metrics(support_rows, repetitions, seed)
        result["support_most_common"]["probability_rule"] = "Support counts plus 1 Laplace smoothing; alphabetical tie break."
    if development:
        counts = Counter(case["target"] for case in development)
        p = np.asarray([counts[key] + 1 for key in BRANDS], dtype=float)
        p /= p.sum()
        population_rows = [probability_row(case, condition, p) for case in matched]
        result["development_population"] = prediction_metrics(population_rows, repetitions, seed)
        result["development_population"]["probability_rule"] = "Development target counts plus 1 Laplace smoothing."
        result["development_population"]["development_n"] = len(development)
    else:
        result["development_population"] = {"n": 0, "status": "No development cases; baseline not fitted."}
    return result


def fit_conditional_logit(development: list[dict], condition: str) -> tuple[dict, Any]:
    eligible = [case for case in development if valid_prices(case) and case.get("target") in BRANDS]
    if not eligible:
        return {"status": "No development cases with all prices; baseline not fitted.", "n": 0}, None
    all_prices = np.asarray([[case["query"]["prices"][key] for key in BRANDS] for case in eligible])
    price_mean, price_sd = float(all_prices.mean()), float(all_prices.std())
    if price_sd < EPS:
        price_sd = 1.0

    def features(case: dict) -> np.ndarray:
        prices = np.asarray([case["query"]["prices"][key] for key in BRANDS], dtype=float)
        ads = np.asarray([float(bool(case.get("query", {}).get("ads", {}).get(key, False))) for key in BRANDS])
        counts = support_counts(case)
        total = sum(counts.values())
        history = np.asarray([counts[key] / total if total else 0.0 for key in BRANDS])
        if condition != "with_history":
            history[:] = 0
        return np.column_stack(((prices - price_mean) / price_sd, ads, history, np.eye(4)))

    x = np.asarray([features(case) for case in eligible])
    y = np.asarray([BRANDS.index(case["target"]) for case in eligible])
    l2 = 0.1

    def objective(beta: np.ndarray) -> tuple[float, np.ndarray]:
        scores = np.einsum("nkf,f->nk", x, beta)
        p = softmax(scores, axis=1)
        loss = float((logsumexp(scores, axis=1) - scores[np.arange(len(y)), y]).mean()
                     + 0.5 * l2 * np.dot(beta, beta))
        residual = p.copy()
        residual[np.arange(len(y)), y] -= 1
        gradient = np.einsum("nk,nkf->f", residual, x) / len(y) + l2 * beta
        return loss, gradient

    optimized = minimize(objective, np.zeros(x.shape[-1]), jac=True, method="L-BFGS-B")
    if not optimized.success or not np.isfinite(optimized.x).all():
        return {"status": f"Optimization failed: {optimized.message}", "n": len(eligible)}, None
    fit = {"status": "Fitted on development only.", "n": len(eligible), "l2": l2,
           "loss_convention": "Mean negative log likelihood plus 0.5 * L2 * squared coefficient norm.",
           "price_mean": price_mean, "price_sd": price_sd,
           "coefficients": dict(zip(["price_standardized", "ad", "support_brand_fraction", *[f"brand_{k}" for k in BRANDS]], optimized.x.tolist()))}

    def predict(case: dict) -> np.ndarray:
        return softmax(features(case) @ optimized.x)

    return fit, predict


def faithfulness_metrics(rows: list[dict], predictions: list[dict], cases: dict[str, dict],
                         repetitions: int, seed: int, warnings: list[str]) -> dict:
    pred_by_key = {(r["case_id"], r["condition"]): r for r in predictions}
    matched = []
    excluded_split = 0
    for original in rows:
        row = dict(original)
        case_id, condition = str(row["case_id"]), row["condition"]
        prediction = pred_by_key.get((case_id, condition), {})
        case = cases.get(case_id, {})
        split = row.get("split", prediction.get("split", case.get("split")))
        if split != "test":
            excluded_split += 1
            continue
        row["household_id"] = str(row.get("household_id", prediction.get("household_id", case.get("household_id", ""))))
        if not row["household_id"]:
            raise ValueError(f"Faithfulness record {case_id} lacks household_id.")
        if not isinstance(row.get("correct"), bool):
            label = row.get("original_prediction", prediction.get("prediction"))
            target = prediction.get("target", case.get("target"))
            row["correct"] = (label == target) if label in BRANDS and target in BRANDS else None
        if finite_number(row.get("margin_drop")) and finite_number(row.get("random_margin_drop_mean")):
            row["margin_advantage"] = row["margin_drop"] - row["random_margin_drop_mean"]
        if not finite_number(row.get("keep_only_absolute_change")) and finite_number(row.get("sufficiency_gap")):
            row["keep_only_absolute_change"] = abs(row["sufficiency_gap"])
        matched.append(row)
    if excluded_split:
        warnings.append(f"Faithfulness: excluded {excluded_split} non-test or unidentified-split record(s).")
    by_condition = {}
    for condition in sorted({r["condition"] for r in matched}):
        selected = [r for r in matched if r["condition"] == condition]
        groups = {}
        for name, subset in (("all", selected), ("correct", [r for r in selected if r["correct"] is True]),
                             ("incorrect", [r for r in selected if r["correct"] is False])):
            result = {"n": len(subset), "households": len({r["household_id"] for r in subset}),
                      "valid_explanations": 0, "coverage": {}, "metrics": {}}
            for flag in ("parse_ok", "citation_valid", "abstained"):
                available = [r for r in subset if isinstance(r.get(flag), bool)]
                result["coverage"][flag] = mean_ci([float(r[flag]) for r in available],
                    [r["household_id"] for r in available], repetitions, seed)
            valid = [r for r in subset if r.get("parse_ok") is True
                     and r.get("citation_valid") is True and r.get("abstained") is not True]
            result["valid_explanations"] = len(valid)
            for metric in FAITH_METRICS:
                # Only records with an actually recorded order test enter that mean.
                eligible = [r for r in (subset if metric == "order_flip" else valid) if finite_number(r.get(metric))]
                result["metrics"][metric] = mean_ci([float(r[metric]) for r in eligible],
                    [r["household_id"] for r in eligible], repetitions, seed)
            groups[name] = result
        by_condition[condition] = groups
    return {"test_records": len(matched), "conditions": by_condition,
            "interpretation": "Behavioral sensitivity of cited input evidence, not proof of internal causal reasoning. Missing metrics are not imputed; denominators are metric-specific."}


def manual_audit_metrics(path: Path, predictions: list[dict], cases: dict[str, dict],
                         warnings: list[str]) -> dict:
    """Summarize human claim counts; blank cells are unreviewed, never zero."""
    result = {"path": str(path), "test_audit_rows": 0, "unreviewed_explanations": 0,
              "invalid_review_rows": 0, "reviewed_explanations": 0, "conditions": {}}
    if not path.exists():
        warnings.append(f"Optional manual audit absent: {path}; claim grounding was not measured.")
        return result
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        required = {"case_id", "condition", "supported_claims", "total_factual_claims"}
        if not required.issubset(reader.fieldnames or []):
            warnings.append(f"Manual audit {path} lacks required columns {sorted(required)}; skipped.")
            return result
        rows = deduplicate(list(reader), ("case_id", "condition"), warnings, "Manual audit")
    prediction_map = {(r["case_id"], r["condition"]): r for r in predictions}
    reviewed = []
    for row in rows:
        case_id, condition = str(row["case_id"]).strip(), str(row["condition"]).strip()
        prediction = prediction_map.get((case_id, condition), {})
        case = cases.get(case_id, {})
        if prediction.get("split", case.get("split")) != "test":
            continue
        result["test_audit_rows"] += 1
        raw_supported = str(row.get("supported_claims") or "").strip()
        raw_total = str(row.get("total_factual_claims") or "").strip()
        if not raw_supported and not raw_total:
            result["unreviewed_explanations"] += 1
            continue
        try:
            supported, total = float(raw_supported), float(raw_total)
            if not (math.isfinite(supported) and math.isfinite(total)
                    and supported.is_integer() and total.is_integer()
                    and 0 <= supported <= total):
                raise ValueError("Counts must be whole numbers with 0 <= supported <= total.")
        except (TypeError, ValueError):
            result["invalid_review_rows"] += 1
            warnings.append(f"Invalid manual claim counts for {case_id}/{condition}; skipped rather than treated as zero.")
            continue
        target = prediction.get("target", case.get("target"))
        chosen = prediction.get("prediction", row.get("predicted"))
        correct = chosen == target if chosen in BRANDS and target in BRANDS else None
        if correct is None:
            supplied = str(row.get("correct") or "").strip().lower()
            correct = True if supplied in ("true", "1") else False if supplied in ("false", "0") else None
        reviewed.append({"condition": condition, "correct": correct,
                         "supported": int(supported), "total": int(total)})
    result["reviewed_explanations"] = len(reviewed)
    for condition in sorted({row["condition"] for row in rows}):
        selected = [row for row in reviewed if row["condition"] == condition]
        groups = {}
        for name, subset in (("all", selected), ("correct", [r for r in selected if r["correct"] is True]),
                             ("incorrect", [r for r in selected if r["correct"] is False])):
            supported = sum(row["supported"] for row in subset)
            total = sum(row["total"] for row in subset)
            groups[name] = {"reviewed_explanations": len(subset), "supported_claims": supported,
                            "total_factual_claims": total,
                            "grounded_claim_rate": supported / total if total else None,
                            "unsupported_claim_rate": (total - supported) / total if total else None}
        result["conditions"][condition] = groups
    result["interpretation"] = "Micro-average over manually counted factual claims. A review with zero factual claims counts as reviewed but adds no claims to the rate denominator; blank cells are unreviewed."
    return result


def make_figures(metrics: dict, output: Path) -> list[str]:
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    paths = []
    synthetic_demo = metrics["configuration"].get("synthetic_demo", False)

    def mark_demo(fig: Any) -> None:
        if synthetic_demo:
            fig.text(0.5, 0.015, DEMO_NOTICE, ha="center", va="bottom",
                     color="#a32121", weight="bold", fontsize=10)

    conditions = metrics["predictions"]
    available = [(name, data) for name, data in conditions.items() if data["test_uncalibrated"]["n"]]
    if not available:
        return paths
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, len(available), figsize=(5 * len(available), 4), squeeze=False)
    for ax, (condition, data) in zip(axes[0], available):
        ax.plot([0, 1], [0, 1], color="0.6", linestyle="--", label="Ideal")
        for key, label, marker in (("test_uncalibrated", "Raw", "o"), ("test_calibrated", "Calibrated", "s")):
            group = data.get(key)
            if not group:
                continue
            bins = [item for item in group["reliability"] if item["n"]]
            ax.plot([item["confidence"] for item in bins], [item["accuracy"] for item in bins], marker=marker, label=label)
        ax.set(xlim=(0, 1), ylim=(0, 1), xlabel="Mean top-label confidence", ylabel="Observed accuracy", title=condition.replace("_", " "))
        ax.legend()
    fig.suptitle("Held-out test calibration · 5 fixed bins")
    mark_demo(fig)
    fig.tight_layout(rect=(0, 0.07 if synthetic_demo else 0, 1, 1))
    path = figures / "calibration.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))
    fig, ax = plt.subplots(figsize=(6, 4))
    names, values, errors = [], [], []
    for condition, data in available:
        group = data["test_uncalibrated"]
        names.append(condition.replace("_", " "))
        values.append(group["accuracy"])
        ci = group["accuracy_ci95"] or [group["accuracy"], group["accuracy"]]
        errors.append([max(0, group["accuracy"] - ci[0]), max(0, ci[1] - group["accuracy"])])
    ax.bar(names, values, yerr=np.asarray(errors).T, capsize=5, color=["#3b82a0", "#e39a3e"][:len(names)])
    ax.set(ylim=(0, 1), ylabel="Top-1 accuracy", title="Held-out test accuracy · household bootstrap 95% CI")
    mark_demo(fig)
    fig.tight_layout(rect=(0, 0.07 if synthetic_demo else 0, 1, 1))
    path = figures / "accuracy_conditions.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))
    fig, ax = plt.subplots(figsize=(6, 4))
    for condition, data in available:
        for key, style in (("test_uncalibrated", "-"), ("test_calibrated", "--")):
            group = data.get(key)
            if not group:
                continue
            curve = group["error_vs_coverage"]
            ax.plot([point["coverage"] for point in curve], [point["error"] for point in curve],
                    style, marker=".", label=f"{condition.replace('_', ' ')} ({'raw' if style == '-' else 'calibrated'})")
    ax.set(xlim=(0, 1.02), ylim=(0, 1), xlabel="Fraction of predictions retained", ylabel="Error among retained predictions", title="Selective prediction on held-out test cases")
    ax.legend(fontsize=8)
    mark_demo(fig)
    fig.tight_layout(rect=(0, 0.07 if synthetic_demo else 0, 1, 1))
    path = figures / "error_vs_coverage.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path))
    return paths


def number(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def interval(value: Any) -> str:
    return "—" if value is None else f"[{value[0]:.3f}, {value[1]:.3f}]"


def write_report(metrics: dict, output: Path) -> None:
    synthetic_demo = metrics["configuration"].get("synthetic_demo", False)
    title = f"# {DEMO_NOTICE}" if synthetic_demo else "# Customer choice trust: experimental results"
    introduction = ("These are synthetic data and/or mock-backend scores used only to verify the workflow. They are not empirical LLM results and support no research conclusions."
                    if synthetic_demo else "This report summarizes recorded model outputs. Scores describe held-out yogurt brand choices; they are not evidence about the customer's true psychological reasons.")
    lines = [title, "", introduction, "",
             "## Prediction and confidence", "",
             "| Condition | Confidence | Test cases | Accuracy | 95% CI | MRR | Log loss | Brier (sum) | ECE (5 bins) |",
             "|---|---|---:|---:|---|---:|---:|---:|---:|"]
    for condition, data in metrics["predictions"].items():
        for key, label in (("test_uncalibrated", "Raw"), ("test_calibrated", "Calibrated")):
            group = data.get(key)
            if group:
                lines.append(f"| {condition} | {label} | {group['n']} | {number(group['accuracy'])} | {interval(group['accuracy_ci95'])} | {number(group['mrr'])} | {number(group['log_loss'])} | {number(group['brier_sum'])} | {number(group['ece_5'])} |")
    for condition, data in metrics["predictions"].items():
        fit = data["temperature_fit"]
        lines.extend(["", f"{condition}: temperature = {number(fit['temperature'])}; validation n = {fit['n']}. {fit['status']}", ""])
    paired = metrics["paired_history_effect"]
    if paired["n"]:
        lines.extend([f"On {paired['n']} shared test cases, the paired accuracy difference (with history minus no history) is {number(paired['mean'])}, household-bootstrap 95% CI {interval(paired['ci95'])}.", ""])
    lines.extend(["## Baselines", "", "Baselines below use the same available test cases as each model condition. Support counts and population counts use +1 Laplace smoothing for probability metrics; the cheapest heuristic has only a hard-choice accuracy score.", "",
                  "| Condition | Baseline | Test cases | Accuracy | 95% CI | MRR | Log loss |",
                  "|---|---|---:|---:|---|---:|---:|"])
    for condition, data in metrics["baselines"].items():
        cheap = data["cheapest"]["accuracy"]
        lines.append(f"| {condition} | Cheapest | {cheap['n']} | {number(cheap['mean'])} | {interval(cheap['ci95'])} | — | — |")
        for key in ("support_most_common", "development_population"):
            group = data.get(key)
            if group:
                lines.append(f"| {condition} | {key} | {group['n']} | {number(group.get('accuracy'))} | {interval(group.get('accuracy_ci95'))} | {number(group.get('mrr'))} | {number(group.get('log_loss'))} |")
        logit = metrics["conditional_logit"].get(condition, {})
        group = logit.get("test")
        if group:
            lines.append(f"| {condition} | Conditional multinomial logit | {group['n']} | {number(group['accuracy'])} | {interval(group['accuracy_ci95'])} | {number(group['mrr'])} | {number(group['log_loss'])} |")
    lines.extend(["", "Conditional logit is fitted only on development cases. Its features are development-standardized price, advertisement, brand constants, and (with-history condition only) the support brand frequency. L2 = 0.1 is fixed, without test tuning.", "",
                  "## Explanation faithfulness", "",
                  "Comprehensiveness and removal advantage are larger when removing cited evidence changes the original prediction more. Keep-only absolute change near zero means cited evidence preserves the original score; the signed sufficiency gap can also be negative, so a smaller signed value is not always better. Margin drop compares the original predicted brand against its fixed original runner-up. Margin advantage subtracts the matched-random margin drop. These are behavioral checks, not access to internal reasoning. Incorrect predictions remain evaluated against their original predicted label.", ""])
    faith = metrics["faithfulness"]
    if not faith["test_records"]:
        lines.extend(["No eligible test faithfulness records were available; no explanation results are inferred.", ""])
    else:
        lines.extend(["| Condition | Prediction group | Cases | Valid non-abstaining explanations | Parse success | Citation validity | Abstention |",
                      "|---|---|---:|---:|---:|---:|---:|"])
        for condition, groups in faith["conditions"].items():
            for name, group in groups.items():
                parse, cite = group["coverage"]["parse_ok"], group["coverage"]["citation_valid"]
                abstention = group["coverage"]["abstained"]
                lines.append(f"| {condition} | {name} | {group['n']} | {group['valid_explanations']} | {number(parse['mean'])} (n={parse['n']}) | {number(cite['mean'])} (n={cite['n']}) | {number(abstention['mean'])} (n={abstention['n']}) |")
        lines.extend(["", "| Condition | Prediction group | Metric | Mean | 95% CI | Eligible cases | Households |",
                      "|---|---|---|---:|---|---:|---:|"])
        for condition, groups in faith["conditions"].items():
            for name, group in groups.items():
                for metric, estimate in group["metrics"].items():
                    if estimate["n"]:
                        lines.append(f"| {condition} | {name} | {metric} | {number(estimate['mean'])} | {interval(estimate['ci95'])} | {estimate['n']} | {estimate['households']} |")
        lines.extend(["", "Invalid parses/citations and explicit abstentions are excluded from evidence-intervention means and retained in coverage denominators. Missing metrics are not treated as zero. Order-flip means include only cases where that test was actually run. Reported means apply to the sampled faithfulness cases; they do not automatically generalize to all test cases if selection was stratified or selective.", ""])
    lines.extend(["## Manually audited factual grounding", ""])
    audit = metrics["manual_audit"]
    if not audit["reviewed_explanations"]:
        lines.extend(["No eligible test explanations have completed claim-count reviews. Grounded and unsupported claim rates are unavailable; blank audit cells are not scored as zero.", ""])
    else:
        lines.extend(["Claim rates below are micro-averages over reviewed test factual claims. Validation reviews are excluded. Zero-claim reviews count as reviewed explanations but contribute no claims to the rate denominator.", "",
                      "| Condition | Prediction group | Reviewed explanations | Supported claims | Total factual claims | Grounded claim rate | Unsupported claim rate |",
                      "|---|---|---:|---:|---:|---:|---:|"])
        for condition, groups in audit["conditions"].items():
            for name, group in groups.items():
                lines.append(f"| {condition} | {name} | {group['reviewed_explanations']} | {group['supported_claims']} | {group['total_factual_claims']} | {number(group['grounded_claim_rate'])} | {number(group['unsupported_claim_rate'])} |")
        lines.extend(["", "Factual grounding is human-reviewed agreement with the provided evidence; it does not establish explanation faithfulness or the customer's true reasons.", ""])
    lines.extend(["## Verification and interpretation", "",
                  f"- Confidence intervals use {metrics['configuration']['bootstrap_repetitions']} household-cluster bootstrap draws with seed {metrics['configuration']['seed']}; an interval is omitted when fewer than two households are available.",
                  "- Calibration temperature is fitted separately by condition on validation predictions, then frozen before test scoring. Raw and calibrated test results are both retained.",
                  "- Raw probabilities are normalized model label scores conditional on the fixed four-brand prompt; calibration measures their agreement with observed choices.",
                  "- The multiclass Brier score sums squared errors across all four labels (range 0–2); log loss uses natural logarithms and probability floor 1e-12.",
                  "- Reliability uses five fixed bins; ECE can be unstable on small samples. Error-versus-coverage curves include all tied confidence scores at each cutoff.",
                  "- MRR uses the average rank for tied scores. Choice ties use alphabetical label order unless the recorded model prediction supplies another maximum-probability label.",
                  "- Support occasions are unordered. Whole-household splits prevent household overlap; these scores do not establish chronological forecasting performance.",
                  "- Altering prices, ads, or support facts tests model sensitivity. It does not reveal the real customer's counterfactual choice or supply a new observed label.", ""])
    for path in metrics["figures"]:
        relative = Path(path).relative_to(output)
        lines.extend([f"![{relative.stem.replace('_', ' ')}]({relative.as_posix()})", ""])
    if metrics["warnings"]:
        lines.extend(["## Input notes", ""])
        lines.extend(f"- {warning}" for warning in metrics["warnings"])
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=Path("outputs/predictions.jsonl"))
    parser.add_argument("--cases", type=Path, default=Path("data/processed/cases.jsonl"))
    parser.add_argument("--faithfulness", type=Path, default=Path("outputs/faithfulness.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--audit", type=Path, default=None,
                        help="Manual claim-count CSV (default: OUTPUT_DIR/manual_audit.csv).")
    parser.add_argument("--bootstrap", type=int, default=500, help="Household bootstrap draws (default: 500).")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.bootstrap < 1:
        parser.error("--bootstrap must be positive.")
    audit_path = args.audit if args.audit is not None else args.output_dir / "manual_audit.csv"
    warnings: list[str] = []
    case_rows = deduplicate(read_jsonl(args.cases, warnings), ("case_id",), warnings, "Cases")
    cases = {str(row["case_id"]): row for row in case_rows}
    household_splits = defaultdict(set)
    for case in case_rows:
        for key in ("household_id", "split", "target"):
            if key not in case:
                raise ValueError(f"Case {case['case_id']} lacks {key}.")
        household_splits[str(case["household_id"])].add(case["split"])
    if any(len(splits) > 1 for splits in household_splits.values()):
        raise ValueError("Household overlap across splits detected in cases.jsonl.")
    raw_predictions = deduplicate(read_jsonl(args.predictions, warnings),
                                  ("case_id", "condition"), warnings, "Predictions")
    predictions = [canonical_prediction(row, cases) for row in raw_predictions]
    if not predictions:
        raise ValueError("No complete prediction records were available; run inference before analysis.")
    synthetic_demo = any(case.get("synthetic") is True for case in case_rows)
    for row in predictions:
        metadata = row.get("metadata") or {}
        synthetic_demo |= ("mock" in str(metadata.get("backend", "")).lower()
                           or metadata.get("synthetic_data") is True or row.get("synthetic") is True)
    if synthetic_demo:
        warnings.append(DEMO_NOTICE + ": all reported scores are workflow checks, not empirical LLM findings.")
    absent_cases = sum(row["case_id"] not in cases for row in predictions)
    if absent_cases:
        warnings.append(f"{absent_cases} prediction records have no matching processed case; their case-based baselines are unavailable.")
    revisions = set()
    for row in predictions:
        metadata = row.get("metadata") or {}
        revision = metadata.get("model_revision", metadata.get("revision"))
        if revision is not None:
            revisions.add(str(revision))
    if len(revisions) > 1:
        raise ValueError("Multiple model revisions found in retained predictions; analyze each revision separately.")
    development = [case for case in case_rows if case["split"] == "development" and case["target"] in BRANDS]
    metrics = {"configuration": {"predictions": str(args.predictions), "cases": str(args.cases),
               "faithfulness": str(args.faithfulness), "audit": str(audit_path),
               "synthetic_demo": bool(synthetic_demo), "bootstrap_repetitions": args.bootstrap,
               "seed": args.seed, "labels": list(BRANDS), "retained_prediction_records": len(predictions)},
               "predictions": {}, "baselines": {}, "conditional_logit": {}, "warnings": warnings}
    for condition in sorted({row["condition"] for row in predictions}):
        grouped = {split: [r for r in predictions if r["condition"] == condition and r["split"] == split]
                   for split in ("development", "validation", "test")}
        fit = fit_temperature(grouped["validation"])
        result = {"temperature_fit": fit,
                  "validation_uncalibrated": prediction_metrics(grouped["validation"], args.bootstrap, args.seed),
                  "test_uncalibrated": prediction_metrics(grouped["test"], args.bootstrap, args.seed)}
        if fit["temperature"] is not None:
            result["test_calibrated"] = prediction_metrics(apply_temperature(grouped["test"], fit["temperature"]), args.bootstrap, args.seed)
        if not grouped["test"]:
            warnings.append(f"{condition}: no test predictions; test metrics are empty.")
        metrics["predictions"][condition] = result
        metrics["baselines"][condition] = baselines(grouped["test"], cases, development, condition, args.bootstrap, args.seed)
        logit_fit, logit_predict = fit_conditional_logit(development, condition)
        logit = {"fit": logit_fit}
        if logit_predict is not None:
            for split in ("validation", "test"):
                eligible = [cases[r["case_id"]] for r in grouped[split] if r["case_id"] in cases and valid_prices(cases[r["case_id"]])]
                rows = [probability_row(case, condition, logit_predict(case)) for case in eligible]
                logit[split] = prediction_metrics(rows, args.bootstrap, args.seed)
        metrics["conditional_logit"][condition] = logit
    paired = defaultdict(dict)
    for row in predictions:
        if row["split"] == "test" and row["condition"] in ("no_history", "with_history"):
            paired[row["case_id"]][row["condition"]] = row
    complete_pairs = [pair for pair in paired.values() if len(pair) == 2]
    metrics["paired_history_effect"] = mean_ci([
        float(pair["with_history"]["prediction"] == pair["with_history"]["target"])
        - float(pair["no_history"]["prediction"] == pair["no_history"]["target"])
        for pair in complete_pairs], [pair["with_history"]["household_id"] for pair in complete_pairs],
        args.bootstrap, args.seed)
    faith_rows = deduplicate(read_jsonl(args.faithfulness, warnings, optional=True),
                             ("case_id", "condition"), warnings, "Faithfulness")
    metrics["faithfulness"] = faithfulness_metrics(faith_rows, predictions, cases, args.bootstrap, args.seed, warnings)
    metrics["manual_audit"] = manual_audit_metrics(audit_path, predictions, cases, warnings)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics["figures"] = make_figures(metrics, args.output_dir)
    write_report(metrics, args.output_dir)
    (args.output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote {args.output_dir / 'report.md'} and {args.output_dir / 'metrics.json'}")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        print(f"Analysis failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
