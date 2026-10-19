"""Read-only, dependency-ordered snapshots of append-only EC2 results."""
import hashlib
import json
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/home/ubuntu/customer-choice-trust/continuations/resumed_v1'
HOST = 'ubuntu@54.252.237.68'
KEY = Path.home() / 'Downloads/llm-experiment.pem'

REMOTE_READER = r'''
import io, json, hashlib, tarfile, sys, os
from pathlib import Path
root = Path('/home/ubuntu/customer-choice-trust/continuations/resumed_v1')
out = root / 'outputs_resumed_v1'
# Children first, parents last: a complete child was saved after its parent.
names = ['interventions.jsonl', 'explanations.jsonl', 'predictions.jsonl',
         'cases.jsonl', 'run_manifest.json']
payload = {}; provenance = {}
for name in names:
    with (out/name).open('rb') as stream:
        bound = os.fstat(stream.fileno()).st_size
        raw = stream.read(bound)
    data = raw
    if name.endswith('.jsonl'):
        end = raw.rfind(b'\n') + 1
        data = raw[:end]
        # A malformed complete record is an error, never silently discarded.
        rows = [json.loads(line) for line in data.splitlines()]
        count = len(rows)
    else:
        json.loads(data); count = None
    payload[name] = data
    provenance[name] = dict(source=str(out/name), bounded_bytes=bound,
        captured_bytes=len(data), incomplete_tail_bytes=len(raw)-len(data),
        records=count, sha256=hashlib.sha256(data).hexdigest())
plan = (root/'execution_resumed_v1/study_plan.json').read_bytes()
json.loads(plan); payload['study_plan.json'] = plan
audit = out/'manual_audit.csv'
if audit.exists(): payload['manual_audit.csv'] = audit.read_bytes()
for name in ('study_plan.json', 'manual_audit.csv'):
    if name in payload:
        provenance[name] = dict(source=str(root/'execution_resumed_v1/study_plan.json' if name=='study_plan.json' else out/name),
            captured_bytes=len(payload[name]), sha256=hashlib.sha256(payload[name]).hexdigest(),
            records=None, role='Supporting file; not used as evidence of human review')
payload['snapshot_provenance.json'] = json.dumps(dict(host='54.252.237.68',
    remote_root=str(root), read_order=names, files=provenance,
    method='Read-only bounded reads; newline-complete JSONL records; children before parents. No writer locks or remote mutations.'), indent=2).encode()
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
    for name, data in payload.items():
        item = tarfile.TarInfo(name); item.size=len(data); item.mode=0o644
        archive.addfile(item, io.BytesIO(data))
'''


def refresh():
    support = ROOT / 'presentation/support'
    support.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=support) as temp:
        temp = Path(temp)
        archive = temp/'snapshot.tar.gz'
        with archive.open('wb') as stream:
            subprocess.run(['ssh', '-i', str(KEY), '-o', 'BatchMode=yes',
                            '-o', 'ConnectTimeout=15', HOST, 'python3 -'],
                           input=REMOTE_READER.encode(), stdout=stream, check=True)
        allowed = {'interventions.jsonl', 'explanations.jsonl', 'predictions.jsonl',
                   'cases.jsonl', 'run_manifest.json', 'study_plan.json',
                   'manual_audit.csv', 'snapshot_provenance.json'}
        extracted = temp/'records'; extracted.mkdir()
        with tarfile.open(archive) as tar:
            for member in tar:
                if member.name not in allowed or not member.isfile():
                    raise ValueError('Unexpected snapshot archive member')
                (extracted/member.name).write_bytes(tar.extractfile(member).read())
        provenance = json.loads((extracted/'snapshot_provenance.json').read_text())
        for name, info in provenance['files'].items():
            if hashlib.sha256((extracted/name).read_bytes()).hexdigest() != info['sha256']:
                raise ValueError('Snapshot transfer hash mismatch')
        identity = hashlib.sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:16]
        dest = support / ('snapshot-' + identity)
        if not dest.exists(): extracted.rename(dest)
        # This pointer is local convenience only; HTML links an immutable snapshot.
        pointer = support/'latest_snapshot.txt'
        pointer.with_suffix('.tmp').write_text(dest.name+'\n')
        pointer.with_suffix('.tmp').replace(pointer)
    return dest


def latest():
    support = ROOT/'presentation/support'
    return support/(support/'latest_snapshot.txt').read_text().strip()


if __name__ == '__main__':
    print(refresh())
