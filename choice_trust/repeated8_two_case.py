"""Frozen completion checkpoint for two cases in the eight-case study."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .development_pilot import digest
from .repeated8 import OUT, file_hash, read, verify
from .test100_execution import write_json


def prepare_scope(out=OUT):
    out = Path(out).resolve()
    manifest = verify(out)
    destination = out / 'two_case_checkpoint'
    path = destination / 'scope.json'
    manifest_sha256 = file_hash(out / 'manifest.json')
    if path.exists():
        scope = read(path)
        if scope.get('scope_id') != digest({k: v for k, v in scope.items() if k != 'scope_id'}):
            raise ValueError('Two-case scope seal mismatch')
        if scope['source_experiment_id'] != manifest['experiment_id'] or scope['manifest_sha256'] != manifest_sha256:
            raise ValueError('Two-case scope belongs to another manifest')
    else:
        counts = Counter(jid.split('__')[1] for jid in manifest['job_order'])
        saved = Counter(jid.split('__')[1] for jid in manifest['job_order']
                        if (out / 'responses' / f'{jid}.json').exists())
        selected = sorted(manifest['selected'],
                          key=lambda case: (counts[case['case_id']] - saved[case['case_id']], case['case_id']))[:2]
        case_ids = [case['case_id'] for case in selected]
        jobs = [jid for jid in manifest['job_order'] if jid.split('__')[1] in case_ids]
        scope = {'source_experiment_id': manifest['experiment_id'], 'manifest_sha256': manifest_sha256,
                 'selection_rule': 'Two frozen eligible cases with the fewest missing Qwen jobs at checkpoint creation; ties by case ID. Only response-file existence was consulted, never outcomes or annotations.',
                 'selected': selected, 'job_order': jobs,
                 'saved_at_selection': {cid: saved[cid] for cid in case_ids},
                 'required_per_case': {cid: counts[cid] for cid in case_ids},
                 'source_manifest_unchanged': True}
        scope['scope_id'] = digest(scope)
        write_json(path, scope, replace=False)
    selected_ids = {case['case_id'] for case in scope['selected']}
    if len(selected_ids) != 2 or len({case['household_id'] for case in scope['selected']}) != 2:
        raise ValueError('Two-case scope does not have two distinct households')
    if scope['job_order'] != [jid for jid in manifest['job_order'] if jid.split('__')[1] in selected_ids]:
        raise ValueError('Two-case scope job order differs from the frozen manifest')
    return scope
