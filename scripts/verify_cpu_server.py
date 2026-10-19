"""Verify the pinned CPU server; --inference makes four tiny synthetic API probes.

Does not read datasets, modify run directories, or print credentials/model text.
"""
from __future__ import annotations
import argparse
import getpass
import hashlib
import json
import math
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'Qwen/Qwen3-1.7B'
REVISION = '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e'


def load_local_settings():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                name, value = line.split('=', 1)
                if name.strip() in ('MODEL_API_KEY', 'MODEL_BASE_URL'):
                    os.environ.setdefault(name.strip(), value.strip().strip('\"\''))


def check_identity(response):
    if response.get('model_id') != MODEL or response.get('revision') != REVISION:
        raise ValueError('Server model/revision does not match the saved CPU protocol.')


def validate_health(health):
    check_identity(health)
    expected = {'device': 'cpu', 'dtype': 'torch.float32', 'max_input_tokens': 4096,
                'max_explanation_tokens': 600, 'enable_thinking': False}
    for key, value in expected.items():
        if health.get(key) != value:
            raise ValueError(f'Unexpected server setting {key}: expected {value!r}.')
    for key in ('scores', 'variable_candidates', 'multi_token_labels', 'explanations'):
        if health.get('capabilities', {}).get(key) is not True:
            raise ValueError(f'Missing upgraded capability: {key}')
    for key, path in [('server_code_sha256', ROOT / 'server.py'),
                      ('scoring_helper_sha256', ROOT / 'choice_trust/scoring.py')]:
        if health.get(key) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError(f'{path.name} differs between this checkout and the running server. Upload both modules and restart.')


def validate_scores(response, answers):
    check_identity(response)
    scores = response.get('scores', {})
    if set(scores) != set(answers):
        raise ValueError('Scores do not map to the requested candidate IDs.')
    if any(not isinstance(v, (float, int)) or isinstance(v, bool) or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
        raise ValueError('Invalid numerical scores.')
    if abs(sum(scores.values()) - 1) > 1e-5:
        raise ValueError('Candidate scores are not normalized.')
    chosen = response.get('prediction')
    if chosen not in scores or scores[chosen] < max(scores.values()) - 1e-7:
        raise ValueError('Prediction is inconsistent with candidate scores.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inference', action='store_true', help='Make exactly four small synthetic interface calls, not a research experiment.')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    load_local_settings()
    base = os.environ.get('MODEL_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    key = os.environ.get('MODEL_API_KEY', '')
    if args.inference and not key:
        key = getpass.getpass('Existing MODEL_API_KEY (hidden; not saved): ')
    if args.inference and len(key) < 24:
        raise SystemExit('The existing key must be at least 24 characters. No key was generated.')

    def request(route, payload=None):
        headers = {'Content-Type': 'application/json'}
        if payload is not None:
            headers['Authorization'] = 'Bearer ' + key
        body = json.dumps(payload).encode() if payload is not None else None
        try:
            with urlopen(Request(base + route, data=body, headers=headers), timeout=args.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            # Do not echo response bodies or authorization headers.
            raise ValueError(f'{route}: HTTP {error.code}. Check the server terminal and existing key.') from None
        except (URLError, TimeoutError):
            raise ValueError(f'{route}: connection failed or timed out. Check the server and SSH tunnel.') from None

    health = request('/health')
    validate_health(health)
    print('PASS: pinned Qwen3-1.7B / CPU float32 / saved limits / upgraded capabilities / source hashes.')
    if not args.inference:
        print('Health verified. No inference calls made. Add --inference for the four bounded interface probes.')
        return
    print('SYNTHETIC INTERFACE CHECK ONLY — no empirical experiment results.')
    for count in (2, 7):
        answers = {f'probe-item-{i+1}': chr(65+i) for i in range(count)}
        response = request('/score_candidates', {
            'prompt': 'Synthetic API check. All these answer labels are available: ' + ', '.join(answers.values()) + '. Select A. Return only the label.',
            'answers': answers})
        validate_scores(response, answers)
        print(f'PASS: {count}-candidate scoring with stable IDs and valid normalized scores.')
    answers = {'sequence-one': 'candidate_alpha_end\n', 'sequence-two': 'candidate_beta_end\n'}
    response = request('/score_candidates', {
        'prompt': 'Synthetic API check. Choose exactly candidate_alpha_end or candidate_beta_end, followed by a newline.',
        'answers': answers})
    validate_scores(response, answers)
    if not any(n > 1 for n in response.get('answer_token_counts', {}).values()):
        raise ValueError('Probe did not exercise multi-token scoring.')
    print('PASS: multi-token candidate sequence scoring.')
    raw = request('/explain', {'prompt': 'Synthetic interface check. Evidence [E1]: item A has price 5; [E2]: item B has price 10. The saved prediction was A. Return only JSON with evidence_ids, a short explanation, and counterfactual=null. Do not claim to know customer motives.'})
    check_identity(raw)
    if not isinstance(raw.get('text'), str) or not raw['text'].strip() or raw.get('finish_reason') not in ('stop', 'length'):
        raise ValueError('Explanation endpoint returned an invalid response envelope.')
    print('PASS: authenticated explanation interface returns text and finish metadata.')
    if raw['finish_reason'] == 'length':
        print('NOTE: explanation reached the token limit; interface availability does not establish explanation quality.')
    print('Completed four synthetic interface calls. No datasets or experiment outputs were modified.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
