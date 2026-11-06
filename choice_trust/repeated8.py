"""Frozen eight-household, repeated-sampling protocol and durable job ledger."""
from __future__ import annotations

from collections import defaultdict, Counter
from hashlib import sha256
from pathlib import Path
import json
import random

from .development_pilot import digest, verify_edit
from .test100_execution import write_json
from .test100_plan import DEFAULT_OUT as SOURCE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'choice_study/choice_faithfulness_8x50_v1'
VERSION = 'choice-faithfulness-8x50-v1'
REPETITIONS = 50
SEED = 42
FAMILIES = ('CURRENT_PRICE', 'CURRENT_ADVERTISING', 'SUPPORT_PURCHASE',
            'HISTORICAL_PRICE_ASSOCIATION', 'HISTORICAL_ADVERTISING_ASSOCIATION',
            'HISTORICAL_OFFER_REMOVAL', 'PRODUCT_ORDER_CONTROL', 'ANSWER_MAPPING_CONTROL')
CROSSWALK = {
    'CURRENT_PRICE': 'CURRENT_PRICES',
    'CURRENT_ADVERTISING': 'CURRENT_ADVERTISING',
    'SUPPORT_PURCHASE': 'HOUSEHOLD_HISTORY',
    'HISTORICAL_PRICE_ASSOCIATION': 'HOUSEHOLD_HISTORY',
    'HISTORICAL_ADVERTISING_ASSOCIATION': 'HOUSEHOLD_HISTORY',
    'HISTORICAL_OFFER_REMOVAL': 'HOUSEHOLD_HISTORY',
    'PRODUCT_ORDER_CONTROL': 'ROBUSTNESS_CONTROL',
    'ANSWER_MAPPING_CONTROL': 'ROBUSTNESS_CONTROL',
}
SUBTYPES = {'SUPPORT_PURCHASE': 'support_purchase_identity',
            'HISTORICAL_PRICE_ASSOCIATION': 'historical_price_purchase_relationship',
            'HISTORICAL_ADVERTISING_ASSOCIATION': 'historical_advertising_purchase_relationship',
            'HISTORICAL_OFFER_REMOVAL': 'historical_offer_availability_with_purchase_identities_retained'}
SETTINGS = {'do_sample': True, 'temperature': 0.7, 'top_p': 1.0, 'top_k': 50,
            'num_beams': 1, 'max_new_tokens': 512, 'use_model_defaults': False,
            'enable_thinking': False, 'max_input_tokens': 4096}
MODEL = {'model_id': 'Qwen/Qwen3-1.7B', 'revision': '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e',
         'tokenizer_revision': '70d244cc86ccca08cf5af4e1e306ecf908b1ad5e',
         'device': 'cpu', 'dtype': 'torch.float32'}
SOURCE_FILES = ('choice_study/test_with_history_100_v1/manifest.json',
                'data/processed/cases.jsonl', 'choice_trust/development_pilot.py',
                'choice_trust/observations.py', 'choice_trust/joint_observation.py',
                'docs/EXPLANATION_ANNOTATION_GUIDE.md', 'docs/LUNA_ANNOTATION_PROMPT_V1.md',
                'docs/LUNA_EDITED_ANNOTATION_V1.md')


def file_hash(path): return sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())


def job_id(case_id, call_id, repetition):
    return f'{VERSION}__{case_id}__{call_id.split("__")[-1]}__r{repetition:02d}'


def signature(manifest, entry, runtime, jid):
    return digest({'experiment_id': manifest['experiment_id'], 'job_id': jid,
                   'entry_hash': manifest['source_entry_hashes'][entry['call_id']],
                   'runtime': runtime})


def build_manifest(source=SOURCE):
    source = Path(source)
    old = read(source / 'manifest.json')
    if old['plan_id'] != digest({k: v for k, v in old.items() if k != 'plan_id'}):
        raise ValueError('Completed source manifest seal mismatch')
    if read(source / 'runner_state.json')['status'] != 'complete':
        raise ValueError('The 100-case source run is not complete')
    by_case = defaultdict(dict)
    for entry in old['entries']:
        by_case[entry['case_id']][entry['family']] = entry
    eligible = defaultdict(list)
    for selection in old['selected_cases']:
        cid = selection['case_id']; family_entries = by_case[cid]
        if set(family_entries) != {'ORIGINAL', *FAMILIES}:
            continue
        if not family_entries['ORIGINAL']['applicable']:
            continue
        if any(e['original_source'] != family_entries['ORIGINAL']['original_source'] for e in family_entries.values()):
            continue
        for entry in family_entries.values():
            if entry['applicable']:
                verify_edit(entry, old['development_price_bounds_cents'])
        eligible[str(selection['household_id'])].append(cid)
    if len(eligible) < 8:
        raise ValueError('Fewer than eight eligible distinct households')
    rng = random.Random(SEED)
    households = sorted(eligible)
    rng.shuffle(households)
    chosen = []
    for household in households[:8]:
        cases = sorted(eligible[household], key=lambda s: int(s.removeprefix('row-')))
        chosen.append({'case_id': rng.choice(cases), 'household_id': household})
    entries = [by_case[s['case_id']][family] for s in chosen for family in ('ORIGINAL', *FAMILIES)]
    counts = Counter(e['family'] for e in entries if e['applicable'])
    jobs = [job_id(e['case_id'], e['call_id'], r) for e in entries if e['applicable'] for r in range(REPETITIONS)]
    rng.shuffle(jobs)
    manifest = {'version': VERSION, 'source_plan_id': old['plan_id'], 'seed': SEED,
        'selection_procedure': 'From completed 100-case manifest only: require original plus all eight saved family records and verified source edits; sort eligible household IDs, seed-42 shuffle, take eight distinct households, choose one numerically sorted eligible query per household with the same RNG. No predictions, targets, effects or annotations consulted.',
        'selected': chosen, 'eligible_households': len(eligible),
        'source_hashes': {p: file_hash(ROOT / p) for p in SOURCE_FILES},
        'source_entry_hashes': {e['call_id']: digest(e) for e in entries},
        'entries': entries, 'crosswalk': CROSSWALK, 'history_subtypes': SUBTYPES,
        'parent_groups': ['CURRENT_PRICES', 'CURRENT_ADVERTISING', 'HOUSEHOLD_HISTORY'],
        'model': MODEL, 'sampling_settings': SETTINGS, 'repetitions': REPETITIONS,
        'job_order': jobs, 'seed_derivation': 'First 16 hex digits of SHA256(experiment ID | job ID), interpreted as an integer',
        'workload': {'original_inputs': counts['ORIGINAL'], 'original_responses': counts['ORIGINAL'] * REPETITIONS,
                     'applicable_edited_inputs': sum(v for k, v in counts.items() if k != 'ORIGINAL'),
                     'edited_responses': sum(v for k, v in counts.items() if k != 'ORIGINAL') * REPETITIONS,
                     'total_inputs': sum(counts.values()), 'total_responses': len(jobs),
                     'applicable_by_family': dict(counts),
                     'skips': [{'case_id': e['case_id'], 'family': e['family'], 'reason': e['skip_reason']}
                               for e in entries if not e['applicable']]},
        'analysis': {'dirichlet_alpha': 0.5, 'invalid_outcome': 'INVALID', 'kl_log_base': 'natural',
                     'resampling_replicates': 1000, 'permutation_replicates': 1000,
                     'family_weighting': 'equal among applicable families; equal among edits per family',
                     'aggregate': 'arithmetic mean of assessable within-example Pearson correlations'},
        'annotation': {'model': 'gpt-6-luna', 'workers': 4, 'human_reviewed': False,
                       'originals_for_primary_EE_only': True}}
    manifest['experiment_id'] = digest(manifest)
    return manifest


def prepare(out=OUT):
    out = Path(out)
    if (out / 'manifest.json').exists():
        return verify(out)
    manifest = build_manifest()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError('Experiment directory contains an incomplete preparation')
    write_json(out / 'manifest.json', manifest, replace=False)
    write_json(out / 'protocol.json', {k: manifest[k] for k in ('version', 'experiment_id', 'selection_procedure',
        'source_hashes', 'crosswalk', 'history_subtypes', 'model', 'sampling_settings', 'seed_derivation',
        'workload', 'analysis', 'annotation')}, replace=False)
    return manifest


def verify(out=OUT):
    manifest = read(Path(out) / 'manifest.json')
    if manifest['experiment_id'] != digest({k: v for k, v in manifest.items() if k != 'experiment_id'}):
        raise ValueError('Experiment manifest seal mismatch')
    if manifest['version'] != VERSION or manifest['crosswalk'] != CROSSWALK or manifest['sampling_settings'] != SETTINGS:
        raise ValueError('Frozen protocol differs')
    for path, expected in manifest['source_hashes'].items():
        if file_hash(ROOT / path) != expected:
            raise ValueError('Frozen source changed: ' + path)
    bounds = read(SOURCE / 'manifest.json')['development_price_bounds_cents']
    for entry in manifest['entries']:
        if digest(entry) != manifest['source_entry_hashes'][entry['call_id']]:
            raise ValueError('Frozen intervention changed')
        if entry['applicable']:
            verify_edit(entry, bounds)
    return manifest
