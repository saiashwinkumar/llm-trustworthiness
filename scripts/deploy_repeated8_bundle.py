#!/usr/bin/env python3
"""Verify a repeated8 bundle and add only absent or byte-identical files."""
from pathlib import Path
from hashlib import sha256
import argparse
import json
import os
import tarfile
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    with tarfile.open(args.bundle, 'r:gz') as bundle:
        members = bundle.getmembers()
        if any(not m.isfile() for m in members) or len({m.name for m in members}) != len(members):
            raise ValueError('Bundle must contain unique regular files only')
        index = json.loads(bundle.extractfile('repeated8_deployment_index.json').read())
        if {m.name for m in members} != set(index['files']) | {'repeated8_deployment_index.json'}:
            raise ValueError('Bundle contents differ from index')
        source = json.loads((root / 'choice_study/test_with_history_100_v1/manifest.json').read_text())
        if source['plan_id'] != index['source_plan_id']:
            raise ValueError('Existing EC2 source study differs')
        pending = {}
        identical = 0
        for member in members:
            if member.name == 'repeated8_deployment_index.json':
                continue
            rel = Path(member.name)
            if rel.is_absolute() or '..' in rel.parts or any(x.startswith('.env') or x in ('.ssh', '.aws') or x.endswith(('.pem', '.key')) for x in rel.parts):
                raise ValueError('Unsafe credential or traversal path')
            target = root / rel
            if not target.resolve().is_relative_to(root):
                raise ValueError('Destination escapes root')
            body = bundle.extractfile(member).read()
            if sha256(body).hexdigest() != index['files'][member.name]:
                raise ValueError('Bundle hash mismatch: ' + member.name)
            if target.exists():
                if target.read_bytes() != body:
                    raise ValueError('Existing file differs; no overwrite: ' + member.name)
                identical += 1
            else:
                pending[target] = body
        for target, body in pending.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                temp = stream.name
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temp, target)
            finally:
                os.unlink(temp)
        print(json.dumps({'experiment_id': index['experiment_id'], 'new_files': len(pending),
                          'existing_identical_files': identical, 'source_overwrites': 0}, indent=2))


if __name__ == '__main__':
    main()
