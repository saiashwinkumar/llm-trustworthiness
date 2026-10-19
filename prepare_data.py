#!/usr/bin/env python3
"""Prepare reproducible, household-disjoint yogurt choice research cases.

Each source row is one complete four-brand purchase occasion. The five observed
support occasions are sampled, not ordered in time: the source has no dates.
Only ``query`` and selected ``support`` facts belong in an LLM prompt. ``target``
is an evaluation label and must never be sent to the prediction model.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import random
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCE_URL = "https://vincentarelbundock.github.io/Rdatasets/csv/Ecdat/Yogurt.csv"
DOCUMENTATION_URL = "https://vincentarelbundock.github.io/Rdatasets/doc/Ecdat/Yogurt.html"
BRAND_MAP = {"A": "dannon", "B": "hiland", "C": "weight", "D": "yoplait"}
BRAND_TO_LABEL = {brand: label for label, brand in BRAND_MAP.items()}
SUPPORT_COUNT = 5
SPLIT_NAMES = ("development", "validation", "test")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic_write(path: Path, content: bytes, *, overwrite: bool = False) -> None:
    """Replace a whole file, never leaving a partially written JSON/CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists. Use --overwrite to replace processed files.")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def download_csv() -> tuple[bytes, dict]:
    try:
        request = Request(SOURCE_URL, headers={"User-Agent": "customer-choice-trust/1.0"})
        with urlopen(request, timeout=90) as response:
            content = response.read()
            resolved_url = response.geturl()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(
            f"Could not download {SOURCE_URL}. Download that CSV in your browser and rerun "
            "with --source-csv /path/to/Yogurt.csv. "
            f"Original error: {exc}"
        ) from exc
    return content, {
        "acquisition": "https_download",
        "downloaded_utc": utc_now(),
        "resolved_url": resolved_url,
    }


def parse_csv(content: bytes) -> tuple[list[dict], list[str]]:
    """Strictly validate the public Ecdat wide-format schema and every value."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("The source CSV must be UTF-8 text.") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("The source CSV must have a header with unique column names.")
    required = {"id", "choice"}
    required.update(f"{prefix}.{brand}" for prefix in ("feat", "price") for brand in BRAND_TO_LABEL)
    missing = sorted(required - set(reader.fieldnames))
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Check that this is Ecdat/Yogurt.csv.")

    parsed: list[dict] = []
    for source_row, row in enumerate(reader, start=1):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"CSV data row {source_row} has an incorrect number of fields.")
        household = row["id"].strip()
        if not household or household.lower() in {"na", "nan", "null"}:
            raise ValueError(f"CSV data row {source_row}: missing household id.")
        choice = row["choice"].strip().lower()
        if choice not in BRAND_TO_LABEL:
            raise ValueError(f"CSV data row {source_row}: unknown choice {choice!r}.")
        prices: dict[str, float] = {}
        ads: dict[str, bool] = {}
        for label, brand in BRAND_MAP.items():
            try:
                price = float(row[f"price.{brand}"])
            except ValueError as exc:
                raise ValueError(f"CSV data row {source_row}: invalid price for {brand}.") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"CSV data row {source_row}: price for {brand} must be finite and positive.")
            prices[label] = price
            value = row[f"feat.{brand}"].strip().lower()
            if value in {"1", "1.0", "true"}:
                ads[label] = True
            elif value in {"0", "0.0", "false"}:
                ads[label] = False
            else:
                raise ValueError(f"CSV data row {source_row}: feat.{brand} must be 0 or 1, got {value!r}.")
        parsed.append({
            "source_row": source_row,
            "household_id": household,
            "prices": prices,
            "ads": ads,
            "choice": BRAND_TO_LABEL[choice],
        })
    if not parsed:
        raise ValueError("The source CSV contains no purchase occasions.")
    return parsed, list(reader.fieldnames)


def household_sort_key(household: str) -> tuple[int, int | str]:
    return (0, int(household)) if household.isdigit() else (1, household)


def build_cases(rows: list[dict], seed: int) -> tuple[list[dict], dict]:
    by_household: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_household[row["household_id"]].append(row)
    eligible = sorted(
        (household for household, occasions in by_household.items() if len(occasions) > SUPPORT_COUNT),
        key=household_sort_key,
    )
    if len(eligible) < 5:
        raise ValueError("At least five households with more than five occasions are needed for nonempty 60/20/20 splits.")
    shuffled = eligible.copy()
    random.Random(seed).shuffle(shuffled)
    development_end = int(0.6 * len(shuffled))
    validation_end = development_end + int(0.2 * len(shuffled))
    split_ids = {
        "development": sorted(shuffled[:development_end], key=household_sort_key),
        "validation": sorted(shuffled[development_end:validation_end], key=household_sort_key),
        "test": sorted(shuffled[validation_end:], key=household_sort_key),
    }
    household_split = {household: split for split, ids in split_ids.items() for household in ids}
    cases: list[dict] = []
    allocation: dict[str, dict] = {}
    for household in eligible:
        occasions = by_household[household]
        # Separate per-household RNG: support selection does not consume split RNG state.
        support_seed = int.from_bytes(hashlib.sha256(f"{seed}:{household}:support".encode()).digest(), "big")
        support_indices = sorted(random.Random(support_seed).sample(range(len(occasions)), SUPPORT_COUNT))
        selected = set(support_indices)
        support = [
            {"evidence_id": f"H{number}", "prices": occasions[index]["prices"],
             "ads": occasions[index]["ads"], "choice": occasions[index]["choice"]}
            for number, index in enumerate(support_indices, start=1)
        ]
        query_rows = [row for index, row in enumerate(occasions) if index not in selected]
        allocation[household] = {
            "split": household_split[household],
            "support_source_rows": [occasions[index]["source_row"] for index in support_indices],
            "query_source_rows": [row["source_row"] for row in query_rows],
        }
        for row in query_rows:
            cases.append({
                "case_id": f"row-{row['source_row']}",
                "household_id": household,
                "split": household_split[household],
                "query": {"prices": row["prices"], "ads": row["ads"]},
                "support": support,
                "target": row["choice"],
                "brand_map": BRAND_MAP,
            })
    cases.sort(key=lambda case: int(case["case_id"].split("-")[1]))
    exclusions = [
        {"household_id": household, "source_rows": len(by_household[household]),
         "reason": "five support occasions would leave no held-out query"}
        for household in sorted(by_household, key=household_sort_key)
        if len(by_household[household]) <= SUPPORT_COUNT
    ]
    split_stats = {}
    for split in SPLIT_NAMES:
        subset = [case for case in cases if case["split"] == split]
        split_stats[split] = {
            "households": len(split_ids[split]),
            "support_occasions": SUPPORT_COUNT * len(split_ids[split]),
            "query_occasions": len(subset),
            "target_counts": dict(sorted(Counter(case["target"] for case in subset).items())),
        }
    return cases, {
        "seed": seed,
        "support_count_per_household": SUPPORT_COUNT,
        "split_fractions": {"development": 0.6, "validation": 0.2, "test": 0.2},
        "rounding": "floor(0.6*n), floor(0.2*n), remainder; after exclusions",
        "split_household_ids": split_ids,
        "source_row_count": len(rows),
        "source_household_count": len(by_household),
        "eligible_household_count": len(eligible),
        "excluded_households": exclusions,
        "query_case_count": len(cases),
        "split_stats": split_stats,
        "household_allocation": allocation,
        "design": "Household-disjoint held-out choice prediction with five randomly observed support occasions.",
        "temporal_limit": "No dates are provided. Support examples are not claimed to precede query purchases.",
        "price_units": "Original numeric values retained. No currency or unit conversion is assumed.",
        "target_policy": "The query target is evaluation-only and must never enter LLM prompts.",
        "brand_map": BRAND_MAP,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-csv", type=Path, help="Use an already downloaded Ecdat/Yogurt.csv (offline mode).")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--overwrite", action="store_true", help="Replace processed files; content-addressed raw snapshots remain intact.")
    args = parser.parse_args()
    data_dir = args.data_dir.resolve()
    cases_path = data_dir / "processed" / "cases.jsonl"
    manifest_path = data_dir / "processed" / "manifest.json"
    for path in (cases_path, manifest_path):
        if path.exists() and not args.overwrite:
            parser.error(f"{path} already exists. Inspect it or rerun with --overwrite.")
    try:
        if args.source_csv:
            source_path = args.source_csv.expanduser().resolve()
            content = source_path.read_bytes()
            acquisition = {"acquisition": "local_csv", "local_path": str(source_path), "downloaded_utc": None}
        else:
            content, acquisition = download_csv()
        rows, columns = parse_csv(content)
        cases, manifest = build_cases(rows, args.seed)
        checksum = hashlib.sha256(content).hexdigest()
        snapshot_path = data_dir / "raw" / f"Yogurt.{checksum}.csv"
        if snapshot_path.exists():
            if hashlib.sha256(snapshot_path.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Raw snapshot checksum mismatch: {snapshot_path}")
        else:
            atomic_write(snapshot_path, content)
        manifest.update({
            "schema_version": 1,
            "prepared_utc": utc_now(),
            "source": {
                "url": SOURCE_URL,
                "documentation_url": DOCUMENTATION_URL,
                **acquisition,
                "snapshot_relative_path": str(snapshot_path.relative_to(data_dir)),
                "sha256": checksum,
                "bytes": len(content),
                "columns": columns,
                "original_reference": "Jain, Vilcassim and Chintagunta (1994), A random-coefficients logit brand-choice model applied to panel data, JBES 12(3).",
                "package_license": "Ecdat package: GPL (>= 2); see https://cran.r-project.org/package=Ecdat",
                "license_note": "Package metadata is recorded as provenance; it is not a separate assertion of ownership or licensing for the original scanner study.",
            },
        })
        cases_bytes = "".join(json.dumps(case, allow_nan=False, separators=(",", ":")) + "\n" for case in cases).encode()
        manifest["cases_sha256"] = hashlib.sha256(cases_bytes).hexdigest()
        atomic_write(cases_path, cases_bytes, overwrite=args.overwrite)
        atomic_write(manifest_path, (json.dumps(manifest, indent=2, allow_nan=False) + "\n").encode(), overwrite=args.overwrite)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Data preparation failed: {exc}\n")
    print(f"Validated {len(rows)} occasions from {manifest['source_household_count']} households.")
    for split, stats in manifest["split_stats"].items():
        print(f"{split}: {stats['households']} households, {stats['query_occasions']} query cases")
    print(f"Excluded households: {len(manifest['excluded_households'])}")
    print(f"Cases: {cases_path}")
    print(f"Manifest: {manifest_path}")
    print("These are held-out choices, not a chronological forecast. Never put query targets in prompts.")


if __name__ == "__main__":
    main()
