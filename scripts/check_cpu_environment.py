"""Audit the activated server environment; optionally install missing packages only.

Never creates an environment, installs Torch, or upgrades installed distributions.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.metadata as metadata
import os
from pathlib import Path
import re
import subprocess
import sys

try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def plan(requirements, installed):
    missing, incompatible = [], []
    for line in requirements.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        version = installed.get(canonical(requirement.name))
        if version is None:
            missing.append(line)
        elif version not in requirement.specifier:
            incompatible.append(f'{requirement.name}=={version}; required {requirement.specifier}')
    return missing, incompatible


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-missing', action='store_true')
    args = parser.parse_args()
    print('Interpreter:', sys.executable)
    print('Environment:', sys.prefix)
    print('Python:', sys.version.split()[0])
    if sys.prefix == sys.base_prefix:
        raise SystemExit('Activate the existing remote .venv first. No environment was created.')
    installed = {canonical(d.metadata['Name']): d.version for d in metadata.distributions() if d.metadata.get('Name')}
    if 'torch' not in installed:
        raise SystemExit('Torch is missing: confirm that you activated the existing CPU environment. Torch will not be installed automatically.')
    requirements = (ROOT / 'requirements-server.txt').read_text()
    missing, incompatible = plan(requirements, installed)
    if incompatible:
        raise SystemExit('Installed versions outside the declared ranges; refusing to replace them:\n' + '\n'.join(incompatible))
    if missing:
        print('Missing required packages:', ', '.join(missing))
        if not args.install_missing:
            raise SystemExit('Run again with --install-missing to install only absent packages.')
        folder = ROOT / 'deployment_checks'
        folder.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        constraints = folder / f'preserve-installed-{stamp}-{os.getpid()}.txt'
        with constraints.open('x') as handle:
            handle.write(''.join(f'{name}=={version}\n' for name, version in sorted(installed.items())))
        # Pin every installed distribution. New transitive dependencies can be
        # installed; resolver conflicts stop instead of upgrading existing ones.
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--constraint', str(constraints), *missing], check=True)
    else:
        print('All required dependencies are installed; no installation performed.')
    subprocess.run([sys.executable, '-m', 'pip', 'check'], check=True)
    subprocess.run([sys.executable, '-B', '-c',
        'import torch, transformers, accelerate, huggingface_hub, safetensors, fastapi, pydantic, uvicorn; '
        'import server; '
        'print("Server entry point and scoring module imports: OK"); '
        'print("Torch:", torch.__version__); '
        'print("CPU build:", torch.version.cuda is None)'], cwd=ROOT, check=True)
    print('Environment ready. No model was loaded or server started.')


if __name__ == '__main__':
    main()
