#!/usr/bin/env python3
"""Preview deterministic factual observations for one real prepared yogurt case."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from choice_trust.observations import generate_observations, inputs_from_prepared_yogurt
from choice_trust.joint_observation import build_joint_messages


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("data/processed/cases.jsonl"))
    parser.add_argument("--case-id", help="Prepared case ID; default is the first real case")
    parser.add_argument("--json", action="store_true", help="Print full structured output")
    parser.add_argument("--prompt", action="store_true", help="Print complete model prompt; no inference")
    parser.add_argument("--assignments", action="store_true", help="Also print internal source-to-concept assignments")
    args = parser.parse_args()
    case = None
    with args.cases.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if not row.get("synthetic") and (args.case_id is None or row.get("case_id") == args.case_id):
                case = row
                break
    if case is None:
        parser.error(f"no real prepared case found for {args.case_id or 'first case'} in {args.cases}")
    for condition, with_history in (("no_history", False), ("with_history", True)):
        result = generate_observations(**inputs_from_prepared_yogurt(case, with_history=with_history))
        print(f"\nCASE {case['case_id']} | {condition}\n")
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.prompt:
            print(build_joint_messages(result, result["candidates"])[0]["content"])
        else:
            print(result["text"])
        if args.assignments:
            print("\nINTERNAL SOURCE-FIELD ASSIGNMENT (outside model prompt)")
            print(json.dumps(result["source_group_assignment"], indent=2))


if __name__ == "__main__":
    main()
