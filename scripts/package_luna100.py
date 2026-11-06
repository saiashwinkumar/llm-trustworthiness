#!/usr/bin/env python3
"""Allowlisted code, frozen sources/jobs, and matching pilot records; no secrets."""
from pathlib import Path
from hashlib import sha256
import json
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.luna_batch import LunaBatch, STUDY

b = LunaBatch()
files = set(b.manifest['code_hashes']) | set(b.manifest['source_hashes'])
files.update(str(p.relative_to(ROOT)) for p in (ROOT / 'choice_trust').glob('*.py'))
files.update(('scripts/set_luna_key.py', 'scripts/launch_luna100_existing_aws.py',
              'scripts/deploy_luna100_bundle.py', 'tests/__init__.py',
              'tests/test_luna_annotations.py', 'tests/test_luna_batch.py'))
for directory in (b.out, STUDY / 'luna_originals_10_v1', STUDY / 'annotations/luna-originals-10-v1'):
    files.update(str(p.relative_to(ROOT)) for p in directory.rglob('*.json')
                 if 'notebook_execution' not in p.parts and not p.name.startswith('.'))
files = {f for f in files if (ROOT / f).is_file()}
for f in files:
    if any(s.startswith('.env') or s in ('.aws', '.ssh') or s.endswith(('.pem', '.key')) for s in Path(f).parts):
        raise ValueError('Credential path is forbidden')
index = {'annotation_manifest_id': b.manifest['annotation_manifest_id'], 'study_plan_id': b.manifest['study_plan_id'],
         'files': {f: sha256((ROOT / f).read_bytes()).hexdigest() for f in sorted(files)}}
p = Path('/private/tmp/luna742_deployment_index.json')
p.write_text(json.dumps(index, indent=2) + '\n')
archive = Path('/private/tmp/luna742_ec2_v1.tar.gz')
with tarfile.open(archive, 'w:gz') as tf:
    for f in sorted(files):
        tf.add(ROOT / f, arcname=f, recursive=False)
    tf.add(p, arcname='luna742_deployment_index.json')
print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size,
                  'sha256': sha256(archive.read_bytes()).hexdigest(), 'files': len(files),
                  'manifest_id': index['annotation_manifest_id']}, indent=2))
