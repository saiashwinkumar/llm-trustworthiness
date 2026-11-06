# Saved-record analysis: test / with_history 100 v1

Run `python3 scripts/analyze_test100.py`. The command reads the completed frozen study and writes `choice_study/test_with_history_100_v1/analysis_v1/`. It never invokes a predictor, annotation helper, model server or network request.

## Scope and joins

The frozen manifest is verified against its selected cases, existing source data, intervention implementations, precision policy, support selections and protocol. Response joins use `call_id`, case, condition, family and frozen plan ID. Input/runtime signatures, complete prompts, raw parsing diagnostics and decoded product identities are checked. Original targets are used only for original accuracy. Originals are counted once; pair-level summaries remain explicitly pair-weighted.

Candidate answers are inverse-mapped through each input's answer mapping. JSON parsing and candidate validity determine prediction assessability; citation diagnostics are separate. No missing/malformed output is repaired, and skips do not enter unchanged counts.

## Annotation assumption and actual coverage

Existing labels are assumed correct references, without semantic re-review or a human-approval gate. No human validation is claimed. Annotation joins require the exact response and factual input plus stable IDs; prose similarity does not establish a link.

This completed run has **zero linked annotations** for its 100 originals and 642 edits. Eight saved raw annotations and one reviewed-layer file belong to other pilot/legacy cases. They are excluded by scope, not quality. As a result, prediction metrics can be measured, but conditional influence rates, rule consistency, contradiction and stale-fact rates are NA with explicit zero assessment coverage. No new labels are inferred from raw explanations.

The empty `claim_factuality.jsonl` contains zero reference claims by design. `response_annotation_coverage.jsonl` accounts for all 742 actual responses. Missing labels are not represented as supported claims, absence of errors, no claimed influence, or empty factual explanations.

## Matching and assessment rules

- Substantive influence comparisons use original annotations only. Decisive/contributing roles assert influence regardless of factual status. Description only, explicit denial and not mentioned remain distinct underlying subtypes. Unknown labels stay excluded.
- Historical families match affected source fields and relationship types. Purchase frequency does not match historical offer removal, which retains purchases. A HOUSEHOLD_HISTORY label alone does not invent a price/advertising subtype; such unresolved broad matches remain unclear. Product-order/mapping controls stay separate.
- A rule is assessed only if an existing decisive claim has a structured `rule_specification` with template `choose_uniquely_cheapest_current_product` and explicit `premise_claim_ids` whose reference factual labels are supported. Canonical edited prices must imply one unique minimum. No universal rule is extracted from a contributing reason or “more likely” phrase. No such original annotation/specification exists in this snapshot.
- Staleness accepts existing explicit `stale_fact` labels. A negative response-level result requires existing complete stale-assessment coverage. In the absence of explicit labels or unambiguous annotated temporal/asserted-value information, it stays unassessable. Contradiction alone never implies staleness. No such edited annotations exist in this snapshot.
- All zero denominators produce null/NA. Unsupported, unclear and not-applicable factual statuses remain outside supported+contradicted denominators.

## Files and checks

`metrics.json`, `report.md`, the CSV/JSONL pair table, original/edited annotation coverage, rule/stale evidence, annotation inventory and exact saved examples are generated together. `analysis_manifest.json` records hashes of source data and analysis code. Source hashes are checked again after writing outputs. A rebuild with changed inputs/code must use a new output directory; matching inputs reproduce byte-identical derived files.

Seven focused tests cover zero denominators, remapping invariance, malformed-output exclusions, false factual premises retaining claimed influence, history dependency matching, 2×2 exclusion/counting, distinct-response factuality, and conservative rule/stale eligibility. Runtime checks verify unique originals, pair counts, numerator bounds, control invariance/change complements and stable claim identities. Test fixtures are synthetic and never written as experimental annotations.

Notebook cells **81–91** append the read-only metrics section after the previous 80 cells and outputs. The five executable cells only load the saved metrics/examples and display tables. No KL-based CE, distribution-based EE, Pearson faithfulness, combined trust score, or edited-scenario customer accuracy is computed.
