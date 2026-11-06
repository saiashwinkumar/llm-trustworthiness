#!/usr/bin/env python3
"""Package an allowlisted frozen continuation; never include credentials/.env."""
from pathlib import Path
from hashlib import sha256
import json,sys,tarfile
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from choice_trust.test100_plan import verify_manifest,DEFAULT_OUT
m=verify_manifest(DEFAULT_OUT)
files=set()
files.update(str(p.relative_to(ROOT)) for p in (ROOT/'choice_trust').glob('*.py'))
files.update(['server.py','experiment.py','scripts/run_test100.py','scripts/launch_test100_existing_aws.py','scripts/package_test100.py',
              'docs/TEST_WITH_HISTORY_100.md','data/processed/cases.jsonl','choice_study/development_counterfactual_v1/manifest.json'])
files.update(m['preserved_artifacts'])
files.update(str(p.relative_to(ROOT)) for p in (ROOT/'tests').glob('test_test100*.py'))
files.update(str(p.relative_to(ROOT)) for p in DEFAULT_OUT.rglob('*') if p.is_file() and not p.name.startswith('.')
             and not any(part in ('responses','server_responses','received') for part in p.relative_to(DEFAULT_OUT).parts))
files={name for name in files if (ROOT/name).is_file()}
for name in files:
 if '.env' in Path(name).parts or '.aws' in Path(name).parts or Path(name).suffix in ('.pem','.key'):raise ValueError('Disallowed credential path')
index={'plan_id':m['plan_id'],'files':{name:sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(files)}}
index_path=DEFAULT_OUT/'deployment_files.json';index_path.write_text(json.dumps(index,indent=2)+'\n')
files.add(str(index_path.relative_to(ROOT)))
out=Path('/private/tmp/test100_stage_v1.tar.gz')
with tarfile.open(out,'w:gz') as tf:
 for name in sorted(files):tf.add(ROOT/name,arcname=name,recursive=False)
print(json.dumps({'archive':str(out),'sha256':sha256(out.read_bytes()).hexdigest(),'bytes':out.stat().st_size,'files':len(files),'plan_id':m['plan_id']},indent=2))
