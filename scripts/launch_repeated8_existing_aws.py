#!/usr/bin/env python3
"""Start one detached repeated-sampling supervisor on the existing Linux EC2 host."""
from pathlib import Path
import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, prepare
from choice_trust.repeated8_run import key
from choice_trust.test100_execution import lock, write_json, now

SESSION = 'choice-faithfulness-8x50'
PRICE_SESSION = 'choice-price-lowest-2x50'


def sessions(name=SESSION):
    result = subprocess.run(['screen', '-ls'], capture_output=True, text=True)
    return [line.split()[0] for line in result.stdout.splitlines() if '.' + name in line]


def runners():
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = [v.decode(errors='replace') for v in (proc / 'cmdline').read_bytes().split(b'\0') if v]
            exe = (proc / 'exe').resolve().name
            if exe.startswith('python') and any(Path(a).name == 'run_repeated8.py' for a in args) and any(a in ('run', 'run-two', 'run-price-lowest') for a in args):
                found.append(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return found


def launch(two_case_checkpoint=False, price_lowest_checkpoint=False):
    if sys.platform != 'linux' or not shutil.which('screen'):
        raise RuntimeError('Use this launcher on the existing Linux EC2 host with screen installed')
    manifest = prepare()
    scope = None
    if two_case_checkpoint and price_lowest_checkpoint:
        raise ValueError('Choose only one checkpoint mode')
    if price_lowest_checkpoint:
        from choice_trust.repeated8_price_lowest import prepare_scope
        scope = prepare_scope()
    elif two_case_checkpoint:
        from choice_trust.repeated8_two_case import prepare_scope
        scope = prepare_scope()
    session = PRICE_SESSION if price_lowest_checkpoint else SESSION
    if not key():
        raise RuntimeError('OPENAI_API_KEY is unavailable from the private EC2 configuration')
    python = Path('/home/ubuntu/customer-choice-trust/.venv/bin/python')
    if not python.exists():
        raise RuntimeError('Existing EC2 Python environment missing')
    with lock(OUT / '.launch.lock'):
        if sessions(SESSION) or sessions(PRICE_SESSION) or runners():
            raise RuntimeError('Detached supervisor or runner already exists; inspect status')
        with lock(OUT / '.runner.lock'):
            pass
        state_dir = OUT / scope.get('checkpoint_dir', 'two_case_checkpoint') if scope else OUT
        log = state_dir / 'runner.log'
        env = {**os.environ, 'TERM': os.environ.get('TERM') or 'xterm', 'PYTHONUNBUFFERED': '1',
               'PYTHONDONTWRITEBYTECODE': '1', 'REPEATED8_RUN_LOG': str(log)}
        command = 'exec "$@" >> "$REPEATED8_RUN_LOG" 2>&1'
        mode = 'run-price-lowest' if price_lowest_checkpoint else 'run-two' if scope else 'run'
        args = [str(python), '-B', '-u', str(ROOT / 'scripts/run_repeated8.py'), mode]
        result = subprocess.run(['screen', '-dmS', session, '/bin/bash', '-c', command, 'bash', *args],
                                cwd=ROOT, env=env)
        if result.returncode:
            raise RuntimeError('screen launch failed')
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            pids = runners()
            if len(pids) == 1 and sessions(session) and (state_dir / 'runner_state.json').exists():
                state = json.loads((state_dir / 'runner_state.json').read_text())
                if state.get('pid') == pids[0] and state.get('status') == 'running':
                    with (OUT / '.runner.lock').open('a+') as stream:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            metadata = {'utc': now(), 'status': 'running', 'session': session,
                                        'pid': pids[0], 'out': str(OUT), 'log': str(log),
                                        'experiment_id': manifest['experiment_id'],
                                        'scope_id': scope['scope_id'] if scope else None,
                                        'selected': scope['selected'] if scope else manifest['selected'],
                                        'ec2_shutdown': False}
                            write_json(state_dir / 'launch_state.json', metadata)
                            return metadata
            time.sleep(.5)
        raise RuntimeError('Detached runner was not verified active; inspect runner.log')


if __name__ == '__main__':
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--two-case-checkpoint', action='store_true')
        mode.add_argument('--price-lowest-checkpoint', action='store_true')
        args = parser.parse_args()
        print(json.dumps(launch(args.two_case_checkpoint, args.price_lowest_checkpoint), indent=2))
    except (RuntimeError, ValueError) as error:
        print(json.dumps({'status': 'blocked_or_incomplete', 'reason': str(error)}), file=sys.stderr)
        raise SystemExit(1)
