#!/usr/bin/env python3
"""Detach only the frozen Luna API annotator on the existing EC2 environment."""
from pathlib import Path
import argparse
import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.luna_batch import LunaBatch, DEFAULT_OUT, now
from choice_trust.test100_execution import lock, write_json

SESSION = 'choice-luna-annotations-100'


def sessions():
    result = subprocess.run(['screen', '-ls'], capture_output=True, text=True)
    return [line.split()[0] for line in result.stdout.splitlines() if '.' + SESSION in line]


def runners():
    found = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            exe = (proc / 'exe').resolve().name
            args = [v.decode() for v in (proc / 'cmdline').read_bytes().split(b'\0') if v]
            if exe.startswith('python') and any(Path(a).name == 'run_luna100.py' for a in args) and 'run' in args:
                found.append(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return found


def launch():
    if sys.platform != 'linux' or not shutil.which('screen'):
        raise RuntimeError('Run this launcher on the existing Linux EC2 host with screen installed')
    os.chdir(ROOT)
    batch = LunaBatch()
    with lock(batch.out / '.launch.lock'):
        if sessions() or runners():
            raise RuntimeError('An annotation session or runner already exists; use status instead of starting another')
        if not batch.key():
            raise RuntimeError('Missing OPENAI_API_KEY. Run scripts/set_luna_key.py here before launching')
        # Check the runner lock before launching. The child acquires it for its
        # complete lifetime; the separate launch lock serializes launchers.
        with lock(batch.out / '.runner.lock'):
            pass
        python = Path('/home/ubuntu/customer-choice-trust/.venv/bin/python')
        if not python.is_file():
            raise RuntimeError('The existing project Python environment is unavailable')
        log = batch.out / 'runner.log'
        args = [str(python), '-B', '-u', str(ROOT / 'scripts/run_luna100.py'), 'run']
        # Keep screen's PTY open on stdin. Redirecting all three descriptors away
        # closes the window and can deliver SIGHUP before the child starts.
        # The runner itself has no interactive prompts.
        command = 'exec "$@" >> "$LUNA_RUN_LOG" 2>&1'
        env = {**os.environ, 'TERM': os.environ.get('TERM') or 'xterm', 'PYTHONUNBUFFERED': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'LUNA_RUN_LOG': str(log)}
        result = subprocess.run(['screen', '-dmS', SESSION, '/bin/bash', '-c', command, 'bash', *args], cwd=ROOT, env=env)
        if result.returncode:
            raise RuntimeError('screen launch failed; inspect the annotation log')
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            pids = runners()
            if len(pids) == 1 and sessions() and (batch.out / 'runner_state.json').exists():
                state = json.loads((batch.out / 'runner_state.json').read_text())
                if state.get('pid') == pids[0] and state.get('status') == 'running':
                    with (batch.out / '.runner.lock').open('a+') as stream:
                        try:
                            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        except BlockingIOError:
                            metadata = {'utc': now(), 'status': 'running', 'session': SESSION, 'pid': pids[0],
                                'root': str(ROOT), 'out': str(batch.out), 'log': str(log), 'workers': 4,
                                'annotation_manifest_id': batch.manifest['annotation_manifest_id'],
                                'study_plan_id': batch.manifest['study_plan_id'], 'model': 'gpt-6-luna',
                                'credential': 'private environment/configuration; never printed',
                                'ec2_shutdown': False, 'existing_model_server_untouched': True}
                            write_json(batch.out / 'launch_state.json', metadata)
                            return metadata
            time.sleep(.5)
        raise RuntimeError('Detached runner was not verified active; inspect runner.log before retrying')


if __name__ == '__main__':
    try:
        print(json.dumps(launch(), indent=2))
    except RuntimeError as error:
        print(json.dumps({'status': 'blocked_or_incomplete', 'reason': str(error)}), file=sys.stderr)
        raise SystemExit(1)
