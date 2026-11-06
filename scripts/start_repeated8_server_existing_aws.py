#!/usr/bin/env python3
"""Replace only the existing loopback Qwen transport with the sampled wrapper."""
from pathlib import Path
from urllib.request import Request, urlopen
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import secrets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, prepare
from choice_trust.test100_execution import write_json, now

SESSION = 'choice-model-repeated8'
APP = 'choice_trust.repeated8_server:app'
BASE = 'http://127.0.0.1:8000'


def processes():
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = [v.decode(errors='replace') for v in (proc / 'cmdline').read_bytes().split(b'\0') if v]
            exe = (proc / 'exe').resolve().name
            if exe.startswith('python') and 'uvicorn' in args and any(app in args for app in ('server:app', 'choice_trust.test100_server:app', APP)):
                found.append({'pid': int(proc.name), 'args': args, 'cwd': str((proc / 'cwd').resolve())})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return found


def competing_runners():
    found = []
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args = [v.decode(errors='replace') for v in (proc / 'cmdline').read_bytes().split(b'\0') if v]
            exe = (proc / 'exe').resolve().name
            if exe.startswith('python') and 'run' in args and any(Path(a).name in
                ('run_test100.py', 'run_luna100.py', 'run_repeated8.py') for a in args):
                found.append(int(proc.name))
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return found


def environment(pid):
    return {k.decode(): v.decode() for part in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in part
            for k, v in [part.split(b'=', 1)]}


def runtime(secret):
    req = Request(BASE + '/repeated8/runtime', headers={'Authorization': 'Bearer ' + secret})
    with urlopen(req, timeout=180) as response:
        return json.load(response)


def launch():
    if sys.platform != 'linux' or not shutil.which('screen'):
        raise RuntimeError('Existing Linux EC2 host with screen is required')
    manifest = prepare()
    python = Path('/home/ubuntu/customer-choice-trust/.venv/bin/python')
    if not python.is_file():
        raise RuntimeError('Existing EC2 Python environment is missing')
    old = processes()
    if len(old) > 1:
        raise RuntimeError('Multiple Qwen servers detected; no process was changed')
    server = old[0] if old else None
    env = environment(server['pid']) if server else dict(os.environ)
    from dotenv import dotenv_values
    private = ROOT / '.env.repeated8'
    saved = dotenv_values(private).get('MODEL_API_KEY') if private.exists() else None
    secret = env.get('MODEL_API_KEY') or saved or secrets.token_urlsafe(48)
    if saved and env.get('MODEL_API_KEY') and saved != env['MODEL_API_KEY']:
        raise RuntimeError('Existing server token differs from private repeated8 token')
    if not private.exists():
        fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write('MODEL_API_KEY=' + secret + '\n')
            stream.flush(); os.fsync(stream.fileno())
    if server and APP in server['args']:
        current = runtime(secret)
        if current['experiment_id'] != manifest['experiment_id']:
            raise RuntimeError('Existing sampled server serves another experiment')
        return {'status': 'reused', 'server_pid': server['pid'], 'experiment_id': manifest['experiment_id'],
                'effective_settings': current['effective_settings']}
    if competing_runners():
        raise RuntimeError('Competing study runner detected')
    env.update(MODEL_API_KEY=secret, MODEL_ID='Qwen/Qwen3-1.7B',
               MODEL_REVISION='70d244cc86ccca08cf5af4e1e306ecf908b1ad5e',
               MODEL_DEVICE='cpu', ALLOW_CPU='1', MAX_INPUT_TOKENS='4096',
               REPEATED8_OUT=str(OUT), PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1',
               TERM=env.get('TERM') or 'xterm')
    with (OUT / 'server_preflight.log').open('ab') as stream:
        preflight = subprocess.run([str(python), '-B', '-c', 'import choice_trust.repeated8_server'],
                                  cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    if preflight.returncode:
        raise RuntimeError('New server wrapper import failed; existing server left running')
    if server:
        os.kill(server['pid'], signal.SIGINT)
        deadline = time.monotonic() + 120
        while Path(f"/proc/{server['pid']}").exists() and time.monotonic() < deadline:
            time.sleep(1)
        if Path(f"/proc/{server['pid']}").exists() or processes():
            raise RuntimeError('Existing server did not exit cleanly; new server not started')
    log = OUT / 'server.log'
    env['REPEATED8_SERVER_LOG'] = str(log)
    command = 'exec "$@" >> "$REPEATED8_SERVER_LOG" 2>&1'
    args = [str(python), '-B', '-u', '-m', 'uvicorn', APP, '--host', '127.0.0.1', '--port', '8000', '--workers', '1']
    result = subprocess.run(['screen', '-dmS', SESSION, '/bin/bash', '-c', command, 'bash', *args], cwd=ROOT, env=env)
    if result.returncode:
        raise RuntimeError('New server screen session failed')
    deadline = time.monotonic() + 360
    while time.monotonic() < deadline:
        try:
            current = runtime(secret)
            servers = processes()
            if len(servers) == 1 and APP in servers[0]['args'] and current['experiment_id'] == manifest['experiment_id']:
                state = {'status': 'running', 'utc': now(), 'server_pid': servers[0]['pid'],
                         'session': SESSION, 'log': str(log), 'experiment_id': manifest['experiment_id'],
                         'effective_settings': current['effective_settings'], 'ec2_shutdown': False}
                write_json(OUT / 'server_launch_state.json', state)
                return state
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('Sampled server runtime was not verified; inspect server.log')


if __name__ == '__main__':
    try:
        print(json.dumps(launch(), indent=2))
    except (RuntimeError, ValueError) as error:
        print(json.dumps({'status': 'blocked_or_incomplete', 'reason': str(error)}), file=sys.stderr)
        raise SystemExit(1)
