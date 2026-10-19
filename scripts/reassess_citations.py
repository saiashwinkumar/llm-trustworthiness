"""Offline, append-free reassessment of canonical saved real-model responses."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from choice_trust.citations import assess_response, CITATION_POLICY_VERSION
from choice_trust.schema import visible_evidence


def sha(data):
    return hashlib.sha256(data).hexdigest()


def collect(root):
    """Exclude mock fixtures, backup copies and imported report duplicates."""
    records, sources = [], {}
    for directory in sorted(root.glob('outputs*')):
        manifest_path = directory / 'run_manifest.json'
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text())
        backend = manifest.get('backend', {})
        if backend != 'real_llm' and (not isinstance(backend, dict) or backend.get('backend') != 'real_llm'):
            continue
        case_path = directory / 'cases.jsonl'
        cases = {c['case_id']: c for c in map(json.loads, case_path.read_text().splitlines())} if case_path.exists() else {}
        sources[str(manifest_path.relative_to(root))] = sha(manifest_path.read_bytes())
        if case_path.exists(): sources[str(case_path.relative_to(root))] = sha(case_path.read_bytes())
        for filename in ('explanations.jsonl', 'faithfulness.jsonl'):
            path = directory / filename
            if not path.exists(): continue
            relative = str(path.relative_to(root))
            sources[relative] = sha(path.read_bytes())
            for number, line in enumerate(path.read_bytes().splitlines(), 1):
                row = json.loads(line)
                legacy = filename == 'faithfulness.jsonl'
                facts = row['provided_evidence'] if legacy else visible_evidence(cases[row['case_id']], row['condition'])
                text = row['raw_explanation'] if legacy else row['raw']['text']
                truncated = row.get('explanation_finish_reason') == 'length' if legacy else row.get('truncated', False)
                previous = bool(row.get('parse_ok') and row.get('citation_valid') and not row.get('abstained') and not truncated)
                assessment = assess_response(text, facts, truncated=truncated)
                records.append(dict(source_file=relative, source_line=number, source_line_sha256=sha(line),
                    source_prompt_version=manifest.get('prompt_version', manifest.get('identity', {}).get('prompt_version')),
                    source_prompt_sha256=sha(row['prompt'].encode()) if 'prompt' in row else None,
                    original_record=row, previous_usable_for_evidence_interventions=previous,
                    case_id=row['case_id'], split=row['split'], condition=row['condition'],
                    assessment=assessment))
    assignments = root / 'choice_study/data/row_assignments.csv'
    if assignments.exists():
        sources[str(assignments.relative_to(root))] = sha(assignments.read_bytes())
        with assignments.open() as handle:
            splits = {int(r['row_id']): r['split'] for r in csv.DictReader(handle)}
        for path in sorted(root.glob('choice_study/runs/*/original_responses.jsonl')):
            relative = str(path.relative_to(root))
            sources[relative] = sha(path.read_bytes())
            settings = path.with_name('settings.json')
            sources[str(settings.relative_to(root))] = sha(settings.read_bytes())
            for number, line in enumerate(path.read_bytes().splitlines(), 1):
                row = json.loads(line)
                revised = 'counter_evidence_ids' in row['explanation_prompt']
                required = ('assessment', 'explanation', 'evidence_ids', 'counter_evidence_ids', 'counterfactual_choice') if revised else ('explanation', 'evidence_ids', 'counterfactual_choice')
                fields = ('evidence_ids', 'counter_evidence_ids') if revised else ('evidence_ids',)
                assessment = assess_response(row['raw_explanation'], [f['id'] for f in row['facts']],
                                             required_fields=required, citation_fields=fields)
                # The notebook did not save finish metadata; do not claim it did.
                assessment['finish_metadata_available'] = False
                previous = not row.get('explanation_error') and bool((row.get('explanation') or {}).get('evidence_ids'))
                records.append(dict(source_file=relative, source_line=number, source_line_sha256=sha(line),
                    source_prompt_version='notebook-neutral-assessment' if revised else 'notebook-original-price-claim',
                    source_prompt_sha256=sha(row['explanation_prompt'].encode()), original_record=row,
                    previous_usable_for_evidence_interventions=previous,
                    case_id='row-' + str(row['row_id']), split=splits[row['row_id']], condition=row['condition'],
                    assessment=assessment))
    return records, sources


def reassess(root, out):
    if out.exists():
        raise ValueError('Destination exists; preserve it and choose a fresh --out')
    records, sources = collect(root)
    groups = defaultdict(list)
    for row in records:
        groups[(str(Path(row['source_file']).parent), row['split'], row['condition'])].append(row)
    summary = []
    for (run, split, condition), rows in sorted(groups.items()):
        usable = sum(r['assessment']['usable_for_evidence_interventions'] for r in rows)
        previous = sum(r['previous_usable_for_evidence_interventions'] for r in rows)
        summary.append(dict(run=run, split=split, condition=condition, responses=len(rows),
            previously_usable=previous, now_usable=usable,
            newly_usable=sum(r['assessment']['usable_for_evidence_interventions'] and not r['previous_usable_for_evidence_interventions'] for r in rows),
            issues=dict(Counter(issue for r in rows for issue in r['assessment']['issues']))))
    # Verify inputs again before publishing the separate assessment.
    for path, expected in sources.items():
        if sha((root / path).read_bytes()) != expected:
            raise ValueError('Source changed during assessment: ' + path)
    out.mkdir(parents=True)
    policy = dict(citation_policy_version=CITATION_POLICY_VERSION, max_citations=None,
        required_fields=['evidence_ids', 'explanation', 'counterfactual'],
        notebook_schema='Preserve the schema requested by each saved notebook prompt',
        json_reading='Read JSON directly; legacy wrapped-object extraction is reported separately; no JSON repair',
        eligibility='Required fields and field types pass, IDs available and unique, nonempty supporting citations, no recorded truncation',
        interpretation='Eligibility for evidence removal/retention only. Not factual correctness, faithfulness, or a completed counterfactual measurement.',
        source_policy='Canonical real-model outputs only; exclude synthetic fixtures and imported/backup duplicates')
    (out / 'policy.json').write_text(json.dumps(policy, indent=2) + '\n')
    (out / 'assessments.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n' for r in records))
    result = dict(citation_policy_version=CITATION_POLICY_VERSION, responses=len(records),
                  now_usable=sum(g['now_usable'] for g in summary), newly_usable=sum(g['newly_usable'] for g in summary), groups=summary)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    from choice_trust.model import PROMPT_VERSION
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
                    citation_policy_version=CITATION_POLICY_VERSION, future_prompt_version=PROMPT_VERSION,
                    prompt_change=dict(previous_framework_prompt='common-evidence-v3',
                        future_framework_prompt=PROMPT_VERSION, previous_max_citations=3,
                        future_max_citations=None, response_schema_changed=False,
                        model_source_sha256=sha((ROOT/'choice_trust/model.py').read_bytes()),
                        legacy_source_sha256=sha((ROOT/'experiment.py').read_bytes())),
                    assessor_sha256=sha(Path(__file__).read_bytes()), policy_code_sha256=sha((ROOT/'choice_trust/citations.py').read_bytes()),
                    new_model_calls=0, new_intervention_measurements=0)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    lines = ['# Saved-response citation reassessment', '',
        f'Policy: `{CITATION_POLICY_VERSION}`. Future prompt: `{PROMPT_VERSION}`.', '',
        'Original records, text, prompts and previous assessments are preserved in the source files and copied into assessments.jsonl. Source hashes and line numbers bind each assessment to its original attempt.', '',
        '| Source | Split | Condition | Responses | Previously usable | Now usable | Newly usable |',
        '|---|---|---|---:|---:|---:|---:|']
    for g in summary:
        lines.append('| ' + ' | '.join(str(g[k]) for k in ('run','split','condition','responses','previously_usable','now_usable','newly_usable')) + ' |')
    lines += ['', f"Total: {result['now_usable']}/{len(records)} responses usable; {result['newly_usable']} newly usable.", '',
        'Usable means eligible for cited-evidence removal/retention. It does not certify factual statements or faithfulness. No predictions, explanations, or intervention measurements were generated. Existing skipped measurements remain skipped.', '',
        'Notebook rows are attempts, not unique cases. Its four existing with-history edits belong to the earlier prompt; the revised explanation has no supporting citations. Finish metadata was not saved by the notebook.', '',
        'Checks are separate: JSON readability; required fields; field types; unavailable IDs; duplicate IDs; empty supporting citations; recorded truncation. Wrapped JSON is identified explicitly.']
    for g in summary:
        if g['issues']:
            lines += ['', f"{g['run']} / {g['condition']}: " + '; '.join(f'{issue} ({n})' for issue,n in g['issues'].items())]
    (out / 'report.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(reassess(args.root.resolve(), args.out.resolve()), indent=2))
