"""Versioned structural checks; no model calls or factual judgments."""
import json
from collections import Counter

CITATION_POLICY_VERSION = 'available-evidence-unlimited-v1'
REQUIRED_FIELDS = ('evidence_ids', 'explanation', 'counterfactual')


def response_issues(row):
    """Report recorded diagnostics without reinterpreting historical responses."""
    if 'citation_assessment' in row:
        return row['citation_assessment']['issues']
    if row.get('parse_error'):
        return ['Previous assessment: ' + row['parse_error']]
    issues = []
    if not row.get('parse_ok'): issues.append('Previous assessment: JSON/field check did not pass')
    if not row.get('citation_valid'): issues.append('Previous assessment: citation check did not pass')
    if row.get('abstained'): issues.append('No supporting evidence IDs supplied')
    if row.get('truncated'): issues.append('Response reached the generation token limit')
    return issues


def assess_response(text, available_ids, *, required_fields=REQUIRED_FIELDS,
                    citation_fields=('evidence_ids',), truncated=False):
    result = dict(citation_policy_version=CITATION_POLICY_VERSION,
                  json_readable=False, response_is_json=False, json_error=None,
                  required_fields_present=None, missing_fields=[], field_errors=[],
                  cited_ids_exist=None, unknown_ids={}, citations_unique=None,
                  duplicate_ids={}, parsed=None, issues=[], truncated=bool(truncated),
                  usable_for_evidence_interventions=False)
    try:
        if not isinstance(text, str):
            raise ValueError('Response text is not a string')
        def reject_constant(value):
            raise ValueError('Non-JSON numeric constant: ' + value)
        try:
            obj = json.loads(text, parse_constant=reject_constant)
            result['response_is_json'] = True
        except ValueError:
            # Preserve the existing wrapped-object reader; never repair JSON.
            obj = json.loads(text[text.index('{'):text.rindex('}') + 1],
                             parse_constant=reject_constant)
            result['issues'].append('JSON object is surrounded by non-JSON text')
        result.update(json_readable=True, parsed=obj)
    except (ValueError, TypeError) as exc:
        result['json_error'] = str(exc)
        result['issues'].append('JSON could not be read: ' + str(exc))
        return result
    if not isinstance(obj, dict):
        result['field_errors'].append('Top-level JSON must be an object')
        result['required_fields_present'] = False
        result['missing_fields'] = list(required_fields)
    else:
        result['missing_fields'] = [k for k in required_fields if k not in obj]
        result['required_fields_present'] = not result['missing_fields']
        if 'explanation' in obj and (not isinstance(obj['explanation'], str) or not obj['explanation'].strip()):
            result['field_errors'].append('explanation must be a nonempty string')
        if 'counterfactual' in obj and obj['counterfactual'] is not None and not isinstance(obj['counterfactual'], dict):
            result['field_errors'].append('counterfactual must be an object or null')
        checked = []
        for field in citation_fields:
            ids = obj.get(field)
            if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids):
                result['field_errors'].append(field + ' must be an array of strings')
                continue
            checked.append(field)
            result['unknown_ids'][field] = sorted(set(ids) - set(available_ids))
            result['duplicate_ids'][field] = sorted(i for i, n in Counter(ids).items() if n > 1)
        if len(checked) == len(citation_fields):
            result['cited_ids_exist'] = not any(result['unknown_ids'].values())
            result['citations_unique'] = not any(result['duplicate_ids'].values())
    if result['missing_fields']:
        result['issues'].append('Missing required fields: ' + ', '.join(result['missing_fields']))
    result['issues'].extend(result['field_errors'])
    for field, ids in result['unknown_ids'].items():
        if ids: result['issues'].append('Unavailable IDs in ' + field + ': ' + ', '.join(ids))
    for field, ids in result['duplicate_ids'].items():
        if ids: result['issues'].append('Duplicate IDs in ' + field + ': ' + ', '.join(ids))
    if isinstance(obj, dict) and obj.get('evidence_ids') == []:
        result['issues'].append('No supporting evidence IDs supplied')
    if truncated:
        result['issues'].append('Response reached the generation token limit')
    result['usable_for_evidence_interventions'] = bool(
        result['required_fields_present'] and not result['field_errors']
        and result['cited_ids_exist'] and result['citations_unique']
        and obj.get('evidence_ids') and not truncated)
    return result
