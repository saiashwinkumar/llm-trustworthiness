# Compact development counterfactual pilot v1

This is a diagnostic development pilot of prediction sensitivity, factual updating, claimed-reason consistency, and presentation effects. It is not a conclusive faithfulness evaluation. Customer purchases under edited scenarios are unknown, and query targets never enter selection, model prompts, annotation, or pilot comparisons.

## Predeclared design

Two real development cases from distinct households, seed 42, both no_history and with_history. Every original/edited input gets one fresh joint response; each case/condition also gets one unchanged-input rerun. The hard caps include all attempts: 32 joint generation calls and six annotation calls. There are no automatic retries, added repetitions or outcome-based edit choices.

Selection takes the first prepared query by source row for each development household, shuffles households with the recorded seed, and uses a stable sort favoring the number of informative historical price/advertising associations. Eligibility requires complete current prices, at least two candidates and a feasible price reversal. No model output or target is read to select cases. The selected cases and all edits/skips appear in `manifest.json` before inference.

Positive price bounds are the minimum and maximum canonical cent amounts in current and selected support offers belonging only to development households. For the present data this is $0.30–$19.30. Numeric source values are not scaled. All price tests use the existing ROUND_HALF_UP canonical representation. The first selected case has one cent-valued edit preserving its full cheapest set; the second makes a formerly noncheapest product uniquely cheapest. Both conditions of the same case receive the same predefined price edit.

The three parent groups remain CURRENT_PRICES, CURRENT_ADVERTISING and HOUSEHOLD_HISTORY. Counts and historical purchase–offer relationships are dependent summaries within HOUSEHOLD_HISTORY. This organization makes no independence claim.

## Families and integrity

The saved `registry.json` specifies permitted fields, fixed fields, selection rules, checks/skips and dependent audit observations for eight families:

1. CURRENT_PRICE: first eligible candidate, +/- one cent preserving cheapest status, or one cent below the minimum for reversal; skip if outside the development bounds.
2. CURRENT_ADVERTISING: toggle the first candidate with a known flag.
3. SUPPORT_PURCHASE: first support ID, next valid candidate cyclically; historical offers stay fixed, while counts and purchase–offer relations regenerate.
4. HISTORICAL_PRICE_ASSOCIATION: permute complete price vectors among fixed support purchases/advertising. Enumerate all assignments for 2–8 records (at most 40,320); deduplicate equivalent unordered model-visible records. Choose the largest change in purchased-among-cheapest count, with fixed lexicographic assignment tie-breaking and the same eligible denominator.
5. HISTORICAL_ADVERTISING_ASSOCIATION: analogous complete flag-vector permutations, changing purchased-advertised counts. Constant vectors or invariant associations produce explicit skips.
6. HISTORICAL_OFFER_REMOVAL: keep support IDs and purchases, set historical prices and flags to null. Missing values render NOT_PROVIDED and are excluded from offer-relationship denominators, never changed into zero/false.
7. PRODUCT_ORDER_CONTROL: rotate candidate presentation while retaining answer identifiers and product information.
8. ANSWER_MAPPING_CONTROL: cyclically reassign answer identifiers to underlying products, including all current offer keys and historical purchases/offers. Decode responses back to the original product IDs before comparison.

Every prompt is regenerated through `generate_observations` and `build_joint_messages`. The manifest stores target-free sources, exact patches, complete regenerated facts, internal association statistics, prompt messages and integrity results. Before each call the executor rechecks the patch, fixed fields, vector multisets, canonical ties/bounds, regenerated facts, and product semantics. Predictor instructions and the 512-token greedy generation settings are identical across all joint calls. No original response, annotation, edit label or expected answer enters an edited predictor prompt.

## Execution and resume

The notebook appends separate stages for originals, unchanged reruns, price edits, advertising edits, support purchases, each historical association family, historical offer removal, presentation controls, annotations and results. It reuses one loaded pinned Qwen model for the entire pilot, sharing it with the annotation helper. The existing local cache is used without downloading a checkpoint or starting a server.

```bash
.venv/bin/python scripts/run_counterfactual_pilot.py plan
.venv/bin/python scripts/run_counterfactual_pilot.py status
.venv/bin/python scripts/run_counterfactual_pilot.py all
.venv/bin/python scripts/run_counterfactual_pilot.py report
```

`all` resumes the saved bounded plan; notebook users can rerun individual named stage cells. The implementation hashes, source checksum, protocol, full inputs/prompts and model settings must match. Completed records are reused only after their full signature matches. The ledger records reuse provenance and reserves each attempt before calling the model. Originals and unchanged reruns have distinct call IDs even when their inputs match.

When all planned records already exist, `all` verifies their signatures against the saved inputs/runtime and rebuilds the report without loading weights or repeating any call. An incomplete run loads the shared runtime once and requires it to match the saved settings before resuming.

An interrupted or failed attempt is not silently retried: an unresolved started attempt requires inspection because generation might already have occurred. A stale writer lock also requires inspection of the recorded PID. There are no AWS mutations or service restarts. Changing inference code, guide or settings requires a new versioned directory; reports and notebook displays can be rebuilt without inference.

## Annotations and interpretation

The six planned annotation slots prioritize four originals and one informative historical-price edit per case, falling back to a with-history price-reversal edit only if needed. Saved external original annotations require the exact source response/messages/settings and guide snapshot to match. Otherwise one fresh annotation call is used. The same predictor checkpoint is the annotator; this limitation is recorded. All claim annotations remain provisional, with exact raw responses and quote/reference diagnostics. Other responses show their actual explanations and remain not yet annotated.

Compare annotated groups, decisive/contributing roles, direction and factual statuses beside actual before/after facts. Do not infer a deciding rule merely from a factual mention. An unchanged answer does not prove zero influence; a changed explanation is not automatically inconsistent. An explicit cheapest-brand deciding rule differs from price as one contributing reason. Single responses do not estimate reliable answer distributions, edited customer outcomes are unknown, and the pilot supplies no universal trust score, faithfulness correlation or significance claim.

Outputs live in `choice_study/development_counterfactual_v1`: protocol/registry/manifest, runtime settings, call ledger, raw attempts, responses with decoded products, annotation records, failures, and a JSON results table. Any manual factual spot checks are stored separately as `manual_review.json`; they do not replace model annotations or provide full coverage.

## Completed development run

The saved run contains 32 joint calls and six annotation calls with no execution failures. All joint outputs parsed and used valid displayed evidence IDs; none were truncated. Four annotations failed quote or evidence-traceability checks, while the two structural passes still need semantic and coverage review. See the [actual results](../choice_study/development_counterfactual_v1/pilot_summary.md), separate `annotation_review.json`, and `verification.json`. A completed-plan resume was exercised: all 38 records were signature-verified and logged as reused without loading a model or adding attempts.

The notebook appends 29 cells (14 executable stages and 15 Markdown cells) after the original 41 cells. The original cell contents and outputs were checked against their saved checksum. The appended tables were refreshed from the saved records after annotation; this refresh made no inference calls.

Added files: `choice_trust/development_pilot.py`, `choice_trust/pilot_execution.py`, `choice_trust/pilot_notebook.py`, `scripts/run_counterfactual_pilot.py`, `tests/test_development_pilot.py`, and this protocol document. Updated file: `test.ipynb`. The existing observation generator, joint-response function, annotation guide, data, and earlier experiment records are reused.
