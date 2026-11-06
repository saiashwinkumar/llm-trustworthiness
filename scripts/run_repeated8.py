#!/usr/bin/env python3
"""Prepare, collect, inspect and analyze the frozen eight-example study."""
import argparse
import json
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, prepare, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'run', 'status', 'analyze', 'run-two', 'status-two',
                                            'run-price-lowest', 'status-price-lowest'))
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    if args.command == 'prepare':
        manifest = prepare(args.out)
        result = {'experiment_id': manifest['experiment_id'], 'selected': manifest['selected'],
                  'workload': manifest['workload'], 'out': str(args.out)}
    elif args.command == 'analyze':
        from choice_trust.repeated8_analysis import analyze
        result = analyze(args.out)
        result = {'experiment_id': result['experiment_id'], 'aggregate_faithfulness': result['aggregate_faithfulness'],
                  'aggregate_assessable_cases': result['aggregate_assessable_cases']}
    elif args.command in ('run-two', 'status-two', 'run-price-lowest', 'status-price-lowest'):
        from choice_trust.repeated8_run import Run
        from choice_trust.test100_execution import write_json, now
        if args.command.endswith('price-lowest'):
            from choice_trust.repeated8_price_lowest import prepare_scope
        else:
            from choice_trust.repeated8_two_case import prepare_scope
        scope = prepare_scope(args.out)
        run = Run(args.out)
        if args.command.startswith('status-'):
            result = {'scope_id': scope['scope_id'], 'selected': scope['selected'],
                      'progress': run.status(scope['job_order'])}
        else:
            result = run.run(scope)
            checkpoint = args.out / scope.get('checkpoint_dir', 'two_case_checkpoint')
            if result['generation'].get('completed', 0) == len(scope['job_order']) and (checkpoint / 'analysis.json').exists():
                analysis = json.loads((checkpoint / 'analysis.json').read_text())
                ready = len(analysis['cases']) == 2 and all(
                    all(value is not None for value in case['concept_CE_nats'].values()) and
                    all(value is not None for value in case['concept_EE'].values()) and
                    case['faithfulness'] is not None for case in analysis['cases'])
                from scripts.start_repeated8_server_existing_aws import APP, processes
                servers = [process for process in processes() if APP in process['args']]
                if len(servers) != 1:
                    raise RuntimeError('Checkpoint finished, but expected exactly one sampled Qwen server to stop')
                pid = servers[0]['pid']
                write_json(checkpoint / 'stop_state.json', {'status': 'stopping', 'utc': now(),
                           'server_pid': pid, 'metrics_ready': ready, 'ec2_shutdown': False})
                signal_pid = pid
                import os
                os.kill(signal_pid, signal.SIGINT)
                deadline = time.monotonic() + 120
                while any(p['pid'] == pid for p in processes()) and time.monotonic() < deadline:
                    time.sleep(1)
                stopped = not any(p['pid'] == pid for p in processes())
                write_json(checkpoint / 'stop_state.json', {'status': 'stopped' if stopped else 'stop_unverified',
                           'utc': now(), 'server_pid': pid, 'metrics_ready': ready, 'ec2_shutdown': False})
                if not stopped:
                    raise RuntimeError('Checkpoint report saved; Qwen server did not stop within 120 seconds')
                result = {'scope_id': scope['scope_id'], 'selected': scope['selected'],
                          'progress': result, 'metrics_ready': ready, 'report': str(checkpoint / 'report.md'),
                          'server_stopped': stopped, 'ec2_shutdown': False}
            else:
                result = {'scope_id': scope['scope_id'], 'selected': scope['selected'],
                          'progress': result, 'metrics_ready': False, 'report': None,
                          'server_stopped': False, 'ec2_shutdown': False}
    else:
        from choice_trust.repeated8_run import Run
        run = Run(args.out)
        result = run.run() if args.command == 'run' else run.status()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(json.dumps({'status': 'blocked_or_incomplete', 'error_type': type(error).__name__,
                          'reason': str(error)}), file=sys.stderr)
        raise SystemExit(1)
