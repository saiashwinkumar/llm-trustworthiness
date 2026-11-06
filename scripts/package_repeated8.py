#!/usr/bin/env python3
"""Create a source-hashed, credential-free bundle for the existing EC2 root."""
from pathlib import Path
from hashlib import sha256
import io
import json
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.repeated8 import OUT, verify, SOURCE_FILES

manifest = verify()
files = set(SOURCE_FILES) | {
    'choice_study/choice_faithfulness_8x50_v1/manifest.json',
    'choice_study/choice_faithfulness_8x50_v1/protocol.json',
    'choice_study/choice_faithfulness_8x50_v1/HANDOFF.md',
    'choice_study/choice_faithfulness_8x50_v1/implementation_amendments.json',
    'choice_trust/repeated8.py', 'choice_trust/repeated8_generation.py',
    'choice_trust/repeated8_server.py', 'choice_trust/repeated8_run.py',
    'choice_trust/repeated8_analysis.py', 'choice_trust/test100_execution.py',
    'choice_trust/test100_plan.py', 'choice_trust/luna_annotations.py',
    'choice_trust/luna_batch.py', 'choice_trust/luna_batch_schema.py',
    'choice_trust/luna_schema.py', 'choice_trust/explanation_annotation.py',
    'choice_trust/scoring.py', 'server.py',
    'scripts/run_repeated8.py', 'scripts/launch_repeated8_existing_aws.py',
    'scripts/start_repeated8_server_existing_aws.py', 'scripts/deploy_repeated8_bundle.py',
    'requirements-annotation.txt'}
index = {'experiment_id': manifest['experiment_id'],
         'source_plan_id': manifest['source_plan_id'],
         'files': {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in sorted(files)}}
path = Path('/private/tmp/choice-faithfulness-8x50-v1-bundle.tar.gz')
with tarfile.open(path, 'w:gz') as bundle:
    for name in sorted(files):
        bundle.add(ROOT / name, arcname=name, recursive=False)
    body = (json.dumps(index, sort_keys=True, indent=2) + '\n').encode()
    info = tarfile.TarInfo('repeated8_deployment_index.json'); info.size = len(body)
    bundle.addfile(info, io.BytesIO(body))
print(json.dumps({'archive': str(path), 'sha256': sha256(path.read_bytes()).hexdigest(),
                  'files': len(files), 'bytes': path.stat().st_size,
                  'experiment_id': manifest['experiment_id']}, indent=2))
