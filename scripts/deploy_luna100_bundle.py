#!/usr/bin/env python3
"""Verify an annotation-only bundle, then add files without replacing differences."""
import argparse
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    out = root / 'choice_study/test_with_history_100_v1/luna_all_742_v1'
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.runner.lock').open('a+') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tarfile.open(args.bundle, 'r:gz') as tf:
            members = tf.getmembers()
            if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
                raise ValueError('Only unique regular files are permitted')
            index_raw = tf.extractfile('luna742_deployment_index.json').read()
            index = json.loads(index_raw)
            if {m.name for m in members} != set(index['files']) | {'luna742_deployment_index.json'}:
                raise ValueError('Archive differs from its allowlist')
            existing = json.loads((root / 'choice_study/test_with_history_100_v1/manifest.json').read_text())
            if existing['plan_id'] != index['study_plan_id']:
                raise ValueError('Existing EC2 study ID differs')
            data = {}
            preserved = 0
            for member in members:
                rel = Path(member.name)
                if rel.is_absolute() or '..' in rel.parts or any(p.startswith('.env') or p in ('.aws', '.ssh') or p.endswith(('.pem', '.key')) for p in rel.parts):
                    raise ValueError('Unsafe or credential path')
                dest = root / rel
                if not dest.resolve().is_relative_to(root):
                    raise ValueError('Destination escapes the existing project')
                body = tf.extractfile(member).read()
                if member.name != 'luna742_deployment_index.json' and sha256(body).hexdigest() != index['files'][member.name]:
                    raise ValueError('Archive hash mismatch: ' + member.name)
                if dest.exists():
                    if dest.read_bytes() != body:
                        raise ValueError('Existing file differs; refusing overwrite: ' + member.name)
                    preserved += 1
                else:
                    data[dest] = body
            for dest, body in data.items():
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as stream:
                    temp = stream.name
                    stream.write(body); stream.flush(); os.fsync(stream.fileno())
                try:
                    os.link(temp, dest)
                finally:
                    os.unlink(temp)
            report = {'annotation_manifest_id': index['annotation_manifest_id'], 'study_plan_id': index['study_plan_id'],
                      'verified_archive_files': len(members), 'existing_identical_files_preserved': preserved,
                      'new_files_added': len(data), 'archive_sha256': sha256(args.bundle.read_bytes()).hexdigest(),
                      'source_overwrites': 0, 'API_calls': 0}
            (out / 'deployment_verified.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
