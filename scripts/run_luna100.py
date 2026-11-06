#!/usr/bin/env python3
"""Prepare, run/resume, inspect or summarize only the frozen Luna test100 stage."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.luna_batch import LunaBatch, DEFAULT_OUT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'status', 'summary'))
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    batch = LunaBatch.prepare(args.out) if args.command == 'prepare' else LunaBatch(args.out)
    if args.command == 'run':
        result = batch.run()
    elif args.command == 'summary':
        result = batch.write_summary()
    else:
        result = batch.summary()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError) as error:
        print(json.dumps({'status': 'blocked_or_incomplete', 'error_type': type(error).__name__, 'reason': str(error)}), file=sys.stderr)
        raise SystemExit(1)
