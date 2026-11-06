"""Second two-case checkpoint using frozen edits that make A uniquely cheapest."""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from .development_pilot import digest
from .repeated8 import OUT, file_hash, read, verify
from .test100_execution import write_json

CHECKPOINT_DIR = 'two_case_price_lowest_checkpoint'


def prepare_scope(out=OUT):
    out = Path(out).resolve()
    manifest = verify(out)
    previous_path = out / 'two_case_checkpoint' / 'scope.json'
    if not previous_path.exists():
        raise ValueError('First two-case checkpoint is missing; cannot prove these are other examples')
    previous = read(previous_path)
    if previous['source_experiment_id'] != manifest['experiment_id']:
        raise ValueError('Prior checkpoint belongs to another frozen experiment')
    excluded = {item['case_id'] for item in previous['selected']}
    path = out / CHECKPOINT_DIR / 'scope.json'
    manifest_sha256 = file_hash(out / 'manifest.json')
    if path.exists():
        scope = read(path)
        if scope.get('scope_id') != digest({k: v for k, v in scope.items() if k != 'scope_id'}):
            raise ValueError('Price-lowest scope seal mismatch')
        if scope['source_experiment_id'] != manifest['experiment_id'] or scope['manifest_sha256'] != manifest_sha256:
            raise ValueError('Price-lowest scope belongs to another manifest')
    else:
        price_entries = {entry['case_id']: entry for entry in manifest['entries'] if entry['family'] == 'CURRENT_PRICE'}
        eligible = []
        for selection in manifest['selected']:
            cid = selection['case_id']
            if cid in excluded:
                continue
            entry = price_entries[cid]
            detail = entry['edit_details']
            if not entry['applicable'] or detail.get('variant') != 'reverse' or detail.get('candidate') != 'A':
                continue
            if 'A' in detail['cheapest_before'] or detail['cheapest_after'] != ['A']:
                continue
            if len(entry['patch']) != 1 or entry['patch'][0]['field'] != 'current.prices.A':
                continue
            eligible.append(selection)
        if len(eligible) < 2:
            raise ValueError('Fewer than two other frozen cases make A uniquely cheapest')
        required = Counter(jid.split('__')[1] for jid in manifest['job_order'])
        saved = Counter(jid.split('__')[1] for jid in manifest['job_order']
                        if (out / 'responses' / f'{jid}.json').exists())
        selected = sorted(eligible, key=lambda item: (required[item['case_id']] - saved[item['case_id']], item['case_id']))[:2]
        ids = {item['case_id'] for item in selected}
        jobs = [jid for jid in manifest['job_order'] if jid.split('__')[1] in ids]
        scope = {'checkpoint_dir': CHECKPOINT_DIR, 'source_experiment_id': manifest['experiment_id'],
                 'manifest_sha256': manifest_sha256, 'previous_scope_id': previous['scope_id'],
                 'selection_rule': 'Among other frozen eight-case households whose existing CURRENT_PRICE edit makes A uniquely cheapest, select the two with the fewest missing Qwen response files; ties by case ID. No outcomes or annotations consulted.',
                 'selected': selected, 'job_order': jobs,
                 'saved_at_selection': {cid: saved[cid] for cid in ids},
                 'required_per_case': {cid: required[cid] for cid in ids},
                 'price_changes': {cid: {'before': price_entries[cid]['patch'][0]['before'],
                                         'after': price_entries[cid]['patch'][0]['after'],
                                         'cheapest_before': price_entries[cid]['edit_details']['cheapest_before'],
                                         'cheapest_after': price_entries[cid]['edit_details']['cheapest_after']}
                                   for cid in ids},
                 'source_manifest_unchanged': True}
        scope['scope_id'] = digest(scope)
        write_json(path, scope, replace=False)
    selected_ids = {item['case_id'] for item in scope['selected']}
    if scope['checkpoint_dir'] != CHECKPOINT_DIR or len(selected_ids) != 2 or selected_ids & excluded:
        raise ValueError('Price-lowest scope does not contain two other cases')
    if len({item['household_id'] for item in scope['selected']}) != 2:
        raise ValueError('Price-lowest scope households are not distinct')
    if scope['job_order'] != [jid for jid in manifest['job_order'] if jid.split('__')[1] in selected_ids]:
        raise ValueError('Price-lowest scope job order differs from frozen manifest')
    for cid in selected_ids:
        entry = next(entry for entry in manifest['entries'] if entry['case_id'] == cid and entry['family'] == 'CURRENT_PRICE')
        if (entry['edit_details']['variant'] != 'reverse' or entry['edit_details']['candidate'] != 'A'
                or entry['edit_details']['cheapest_after'] != ['A']):
            raise ValueError('Price-lowest scope contains an ineligible price edit')
    return scope
