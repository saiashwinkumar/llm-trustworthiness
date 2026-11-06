# Compact factual input, v2

`generate_observations` exposes only the `observations` and grouped `text` needed for model input. The joint prompt uses these compact records and retains the response keys `explanation`, `evidence_ids`, and `prediction` in that order. The hidden query target is never mapped into the generator.

| Concept group | Prepared dataset fields | Generator source references | Exposed IDs |
| --- | --- | --- | --- |
| CURRENT_PRICES | `query.prices.<candidate>` | `current.prices.<candidate>` | `P_<candidate>` |
| CURRENT_ADVERTISING | `query.ads.<candidate>` | `current.advertised.<candidate>` | `F_<candidate>` |
| HOUSEHOLD_HISTORY | Selected `support[].choice`, `support[].prices.<candidate>`, `support[].ads.<candidate>` | `Hn.purchased`, `Hn.prices.<candidate>`, `Hn.advertised.<candidate>` | Existing `H1`, `H2`, … |

Candidate IDs and names come from `brand_map`; support identities come from `support[].evidence_id`. These identify records and products. Every factual field has exactly one assignment in `source_group_assignment`. `evidence_group_assignment` maps exposed citations to their groups, so a later claim using several groups can retain all those groups. Purchase patterns and historical offer context both belong to HOUSEHOLD_HISTORY. This is a source-field partition, with no assertion of statistical independence.

Each source price is interpreted as a dollar amount with scale factor 1. The canonical representation is `Decimal(str(source_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)`, stored as an exact two-decimal string. Thus 1.005 becomes $1.01. Missing prices remain null and render as NOT_PROVIDED. Equal canonical prices compare equal, even when their raw source values differ. The assumption and policy are recorded under `configuration.price_policy`.

Internal auditing remains available:

- `audit.source_values`: untouched source values keyed by exact field references.
- `audit.source_comparisons`: detailed original-value observations, summaries, denominators, exclusions, and dependencies.
- `audit.model_visible_comparisons`: the same audit calculations using rounded cents for price comparisons, minimums and gaps. Direct source records in this audit still preserve raw values; its comparison results use the canonical representation.

These audit catalogues are absent from the model prompt and are not independent evidence concepts. Citation validation uses only the exposed P/F/H records, with no citation-count limit. A citation to H1 identifies its linked purchase and offers; it does not establish that all its fields influenced an answer.

Without support, the HOUSEHOLD_HISTORY heading is omitted and `Household history: NOT_PROVIDED` appears once. A supplied empty list instead renders HOUSEHOLD_HISTORY with zero records. Separate equal-valued support records remain separate. Missing flags stay null, rather than becoming false.

## Actual prepared-case preview

Run `python3 scripts/preview_observations.py --case-id row-2 --prompt --assignments` to print both conditions for the same prepared query and their exact source assignments. The checked output is saved in [compact_observation_preview.txt](../examples/compact_observation_preview.txt). This command does not load a model or perform inference.

Earlier notebook outputs and saved joint-run JSON records retain their original v1 prompts and results. New generation records identify the compact observation and prompt versions as v2.
