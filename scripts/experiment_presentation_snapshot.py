"""Read-only snapshots of immutable Luna results while its writer is active."""
from hashlib import sha256
from pathlib import Path
import io
import json
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'presentation/support'
HOST = 'ubuntu@54.252.237.68'
KEY = Path.home() / 'Downloads/llm-experiment.pem'

REMOTE_READER = r'''
from pathlib import Path
from hashlib import sha256
import io,json,sys,tarfile
root=Path('/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1')
study=root/'choice_study/test_with_history_100_v1'
batch=study/'luna_all_742_v1'
# Freeze the set of published canonical records first. Canonical records are
# immutable and atomically published; states/attempts and exports are not read.
paths=sorted((batch/'records').glob('*.json'))
payload={};links={}
manifest=(batch/'manifest.json').read_bytes();m=json.loads(manifest)
payload['annotation_manifest.json']=manifest
for path in paths:
 body=path.read_bytes();record=json.loads(body)
 if record.get('reused'):
  canonical=root/record['canonical_record_path']
  body=canonical.read_bytes()
  if sha256(body).hexdigest()!=record['canonical_record_sha256']:raise ValueError('Reused annotation changed')
  record=json.loads(body)
 else:canonical=path
 cid=record['source_response_id']
 name='records/'+cid+'.json'
 if name in payload:raise ValueError('Duplicate annotation response ID')
 payload[name]=body
 links[cid]={'original_path':str(canonical.relative_to(root)),'sha256':sha256(body).hexdigest(),'reused':path!=canonical}
info={'study_plan_id':m['study_plan_id'],'annotation_manifest_id':m['annotation_manifest_id'],
      'method':'Published canonical record set captured first; immutable atomic records read once. No writer locks, remote writes, API requests, states or live exports.',
      'records':links,'files':{n:sha256(b).hexdigest() for n,b in payload.items()}}
payload['snapshot_provenance.json']=json.dumps(info,indent=2).encode()
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz') as tf:
 for name,body in payload.items():
  item=tarfile.TarInfo(name);item.size=len(body);tf.addfile(item,io.BytesIO(body))
'''


def install_payload(payload):
    provenance = json.loads(payload['snapshot_provenance.json'])
    for name, expected in provenance['files'].items():
        if sha256(payload[name]).hexdigest() != expected:
            raise ValueError('Annotation snapshot hash mismatch: ' + name)
    identity = sha256(json.dumps(provenance, sort_keys=True).encode()).hexdigest()[:16]
    dest = SUPPORT / ('luna-snapshot-' + identity)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        with tempfile.TemporaryDirectory(dir=SUPPORT) as temp:
            stage = Path(temp) / 'snapshot'
            stage.mkdir()
            for name, body in payload.items():
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            stage.rename(dest)
    pointer = SUPPORT / 'latest_luna_snapshot.txt'
    tmp = pointer.with_suffix('.tmp')
    tmp.write_text(dest.name + '\n')
    tmp.replace(pointer)
    return dest


def refresh_luna(host=HOST, key=KEY):
    with tempfile.TemporaryFile() as stream:
        subprocess.run(['ssh', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host, 'python3 -'],
                       input=REMOTE_READER.encode(), stdout=stream, check=True)
        stream.seek(0)
        payload = {}
        with tarfile.open(fileobj=stream, mode='r:gz') as tf:
            for member in tf:
                path = Path(member.name)
                allowed = member.name in ('annotation_manifest.json', 'snapshot_provenance.json') or (
                    len(path.parts) == 2 and path.parts[0] == 'records' and path.suffix == '.json')
                if not allowed or not member.isfile() or member.name in payload or '..' in path.parts:
                    raise ValueError('Unexpected annotation snapshot member')
                payload[member.name] = tf.extractfile(member).read()
    return install_payload(payload)


def latest_luna():
    pointer = SUPPORT / 'latest_luna_snapshot.txt'
    if pointer.exists():
        return SUPPORT / pointer.read_text().strip()
    # Credential-free, inference-free local fallback: existing real pilot results.
    study = ROOT / 'choice_study/test_with_history_100_v1'
    batch = study / 'luna_all_742_v1'
    payload = {'annotation_manifest.json': (batch / 'manifest.json').read_bytes()}
    links = {}
    for path in sorted((study / 'luna_originals_10_v1/records').glob('*.json')):
        body = path.read_bytes(); record = json.loads(body); cid = record['source_response_id']
        payload['records/' + cid + '.json'] = body
        links[cid] = {'original_path': str(path.relative_to(ROOT)), 'sha256': sha256(body).hexdigest(), 'reused': True}
    m = json.loads(payload['annotation_manifest.json'])
    info = {'study_plan_id': m['study_plan_id'], 'annotation_manifest_id': m['annotation_manifest_id'],
            'method': 'Immutable local saved pilot records only; no API calls.', 'records': links,
            'files': {n: sha256(b).hexdigest() for n, b in payload.items()}}
    payload['snapshot_provenance.json'] = json.dumps(info, indent=2).encode()
    return install_payload(payload)
