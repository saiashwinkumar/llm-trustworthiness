"""Versioned edited extension; baseline original schema/validation is unchanged."""
from copy import deepcopy
import json
from .luna_schema import annotation_schema, obj, strings, validate_result

EDITED_VERSION = 'luna-edited-claims-rules-stale-v1'


def edited_schema(candidates, provenance, original_provenance, patch):
    schema = annotation_schema(candidates, provenance)
    fields = sorted({f for p in original_provenance.values() for f in p['source_fields']})
    comparison = obj({
        'temporal_scope': {'type': 'string', 'enum': ['current_edited', 'explicit_original_reference', 'general_or_influence', 'unclear']},
        'stale_status': {'type': 'string', 'enum': ['stale', 'not_stale', 'unassessable', 'not_applicable']},
        'original_evidence_ids': strings(original_provenance),
        'original_source_fields': strings(fields),
        'changed_patch_fields': strings(sorted({p['field'] for p in patch})),
        'reason': {'type': 'string'},
    })
    claim = schema['properties']['claims']['items']
    claim['properties']['comparison_assessment'] = comparison
    claim['required'].append('comparison_assessment')
    return schema


def validate_batch_result(raw_text, job, api):
    if job['family'] == 'ORIGINAL':
        return validate_result(raw_text, job, api)
    from jsonschema import Draft202012Validator
    issues = []
    duplicates = []

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                duplicates.append(key)
            out[key] = value
        return out

    try:
        parsed = json.loads(raw_text, object_pairs_hook=pairs)
    except (ValueError, TypeError):
        return validate_result(raw_text, job, api)
    issues.extend('Edited schema ' + '/'.join(map(str, e.absolute_path)) + ': ' + e.message
                  for e in Draft202012Validator(job['schema']).iter_errors(parsed))
    if duplicates:
        issues.append('Duplicate JSON keys: ' + ', '.join(duplicates))
    # A validation-only projection checks the unchanged baseline fields. The raw
    # annotation and returned parsed object retain the entire extension verbatim.
    projection = deepcopy(parsed)
    if isinstance(projection, dict) and isinstance(projection.get('claims'), list):
        for claim in projection['claims']:
            if isinstance(claim, dict):
                claim.pop('comparison_assessment', None)
    base_job = {**job, 'schema': annotation_schema(job['annotation_input']['candidates'], job['annotation_input']['provenance'])}
    _, diagnostics = validate_result(json.dumps(projection), base_job, api)
    original_prov = job['comparison_context']['observation_provenance']
    patch_fields = {p['field'] for p in job['patch']}
    checks = []
    if isinstance(parsed, dict) and isinstance(parsed.get('claims'), list):
        for claim in parsed['claims']:
            if not isinstance(claim, dict):
                continue
            comparison = claim.get('comparison_assessment')
            if not isinstance(comparison, dict):
                continue  # The strict schema already reports the malformed field.
            problems = []
            ids, fields = comparison.get('original_evidence_ids'), comparison.get('original_source_fields')
            if isinstance(ids, list) and isinstance(fields, list) and all(isinstance(x, str) for x in ids + fields):
                covered = {f for eid in ids if eid in original_prov for f in original_prov[eid]['source_fields']}
                if not set(fields) <= covered:
                    problems.append('Original fields are not covered by original evidence IDs')
            changed = comparison.get('changed_patch_fields')
            if comparison.get('stale_status') == 'stale':
                if comparison.get('temporal_scope') != 'current_edited':
                    problems.append('A stale assertion must treat an old fact as currently applicable')
                if not ids or not fields or not changed:
                    problems.append('A stale assertion requires original evidence, fields and patch linkage')
            if isinstance(changed, list) and all(isinstance(x, str) for x in changed) and not set(changed) <= patch_fields:
                problems.append('Unknown intervention patch field')
            if not isinstance(comparison.get('reason'), str) or not comparison['reason'].strip():
                problems.append('Missing comparison justification')
            checks.append({'claim_id': claim.get('claim_id'), 'issues': problems})
            issues.extend(f"Claim {claim.get('claim_id')}: {p}" for p in problems)
    diagnostics['issues'].extend(issues)
    diagnostics['comparison_checks'] = checks
    diagnostics['schema_and_traceability_ok'] = not diagnostics['issues']
    return parsed, diagnostics
