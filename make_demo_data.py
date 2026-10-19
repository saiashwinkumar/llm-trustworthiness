"""Generate synthetic cases ONLY to check that the code runs without AWS."""
import json
from pathlib import Path
import random

from prepare_data import BRAND_MAP, build_cases


def main():
    rng = random.Random(123)
    rows = []
    for household in range(1, 21):
        favorite = rng.choice(list(BRAND_MAP))
        for occasion in range(12):
            prices = {label: round(rng.uniform(4, 14), 2) for label in BRAND_MAP}
            ads = {label: rng.random() < .25 for label in BRAND_MAP}
            scores = {label: -.35 * prices[label] + .5 * ads[label] + 1.2 * (label == favorite)
                      + rng.uniform(-.3, .3) for label in BRAND_MAP}
            rows.append({"source_row": len(rows) + 1, "household_id": str(household),
                         "prices": prices, "ads": ads, "choice": max(scores, key=scores.get)})
    cases, manifest = build_cases(rows, seed=42)
    for case in cases:
        case["synthetic"] = True
    folder = Path("data_demo")
    folder.mkdir(exist_ok=True)
    (folder / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases), encoding="utf-8")
    manifest["WARNING"] = "SYNTHETIC DATA ONLY. These are not customer observations or real LLM results."
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(cases)} SYNTHETIC cases in data_demo/cases.jsonl. Do not use as research findings.")


if __name__ == "__main__":
    main()
