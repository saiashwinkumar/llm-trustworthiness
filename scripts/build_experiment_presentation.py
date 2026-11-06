#!/usr/bin/env python3
"""Build the actual experiment's two-tab HTML; saved records only, no inference.

Refresh saved annotations from EC2 and rebuild:
 .venv/bin/python -B scripts/build_experiment_presentation.py --refresh-aws
Offline rebuild of the last immutable snapshots:
 .venv/bin/python -B scripts/build_experiment_presentation.py
"""
from pathlib import Path
from hashlib import sha256
import argparse
import base64
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from experiment_presentation_snapshot import latest_luna, refresh_luna
from presentation_snapshot import latest as latest_legacy, refresh as refresh_legacy
from choice_trust.experiment_presentation import assemble, METHOD_NOTES
from choice_trust.experiment_presentation_html import render
from choice_trust.test100_execution import lock, write_json
from verify_experiment_presentation import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-aws', action='store_true', help='Read-only SSH snapshots; no API/model calls or remote writes')
    args = parser.parse_args()
    out = ROOT / 'presentation'
    out.mkdir(exist_ok=True)
    with lock(out / '.presentation.lock'):
        if args.refresh_aws:
            luna = refresh_luna()
            legacy = refresh_legacy()
        else:
            luna, legacy = latest_luna(), latest_legacy()
        data = assemble(luna, legacy, out / 'report_config.json')
        packet = {'report_configuration': data['config'], 'example': data['example'],
            'development_annotation_example': data['development_annotation_example'],
            'annotation_guide': (ROOT / 'docs/EXPLANATION_ANNOTATION_GUIDE.md').read_text(),
            'original_annotation_supplement': (ROOT / 'docs/LUNA_ANNOTATION_PROMPT_V1.md').read_text(),
            'edited_annotation_extension': (ROOT / 'docs/LUNA_EDITED_ANNOTATION_V1.md').read_text(),
            'model_calls_during_report_generation': 0}
        summary = {k: data[k] for k in ('config', 'metrics', 'legacy_accuracy', 'annotation_label_inventory', 'annotation_snapshot',
            'legacy_snapshot', 'annotation_exclusions', 'all_annotation_records', 'valid_annotation_records', 'method_notes', 'protected_source_hashes', 'model_calls')}
        summary['report_code_sha256'] = {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            'scripts/build_experiment_presentation.py', 'scripts/experiment_presentation_snapshot.py',
            'scripts/verify_experiment_presentation.py', 'choice_trust/experiment_presentation.py',
            'choice_trust/experiment_presentation_html.py', 'presentation_src/experiment.css')}
        css = (ROOT / 'presentation_src/experiment.css').read_text()
        page = render(data, css, packet, summary)
        checks = verify(page, data)
        for name, expected in data['protected_source_hashes'].items():
            if sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Source changed during report generation: ' + name)
        identity = sha256(json.dumps(summary, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        support = out / 'support' / ('actual-experiment-' + identity)
        support.mkdir(parents=True, exist_ok=True)
        write_json(support / 'evaluation.json', summary)
        write_json(support / 'complete-example.json', packet)
        write_json(support / 'verification.json', checks)
        write_json(support / 'source_provenance.json', {'annotation_snapshot': str(luna.relative_to(ROOT)),
            'legacy_snapshot': str(legacy.relative_to(ROOT)), 'source_sha256': data['protected_source_hashes'],
            'annotation_snapshot_provenance': json.loads((luna / 'snapshot_provenance.json').read_text()),
            'earlier_snapshot_provenance': json.loads((legacy / 'snapshot_provenance.json').read_text()),
            'development_source_sha256': {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest()
                for p in (ROOT / 'choice_study/development_counterfactual_v1').rglob('*.json')
                if p.parent.name in ('responses', 'annotations') or p.name in ('manifest.json', 'runtime.json')},
            'method_notes': METHOD_NOTES, 'generator_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
            'report_code_sha256': summary['report_code_sha256'],
            'model_calls': 0, 'remote_writes': 0, 'experimental_protocol_changed': False})
        # Preserve the prior presentation of the earlier protocol before replacing
        # the entry point. Experimental outputs and old snapshots are never edited.
        old = out / 'index.html'
        previous = out / 'earlier-workflow.html'
        if old.exists() and not previous.exists():
            previous.write_bytes(old.read_bytes())
        temp = out / '.index.html.tmp'
        temp.write_text(page)
        temp.replace(old)
        (out / 'support/latest_actual_experiment.txt').write_text(support.name + '\n')
        bundle = out / 'actual-experiment-presentation.zip'
        with zipfile.ZipFile(bundle, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.write(old, 'index.html')
            for f in support.iterdir():
                z.write(f, 'support/' + f.name)
            z.write(out / 'report_config.json', 'support/report_config.json')
        print(json.dumps({'HTML': str(old), 'ZIP': str(bundle), 'source_records': str(support),
            'example_case_id': data['config']['example_case_id'], 'saved_Luna_records': data['all_annotation_records'],
            'eligible_Luna_records': data['valid_annotation_records'], 'model_calls': 0, 'checks': checks}, indent=2))


if __name__ == '__main__':
    main()
