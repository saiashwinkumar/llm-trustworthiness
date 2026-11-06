# Actual development pilot results

Two development households (53 and 99), seed 42; cases `row-1289` and `row-2379`, each with and without history. No customer targets entered predictor or annotation inputs.

Completed **32 joint calls** (4 originals, 4 unchanged reruns, 24 edits) and **6 annotation calls**, with 0 execution failures. All four unchanged reruns matched the exact original raw response.

| Family | Measured edits | Decoded products changed | Skips |
|---|---:|---:|---:|
| CURRENT_PRICE | 4 | 4 | 0 |
| CURRENT_ADVERTISING | 4 | 3 | 0 |
| SUPPORT_PURCHASE | 2 | 1 | 2 |
| HISTORICAL_PRICE_ASSOCIATION | 2 | 1 | 2 |
| HISTORICAL_ADVERTISING_ASSOCIATION | 2 | 1 | 2 |
| HISTORICAL_OFFER_REMOVAL | 2 | 1 | 2 |
| PRODUCT_ORDER_CONTROL | 4 | 2 | 0 |
| ANSWER_MAPPING_CONTROL | 4 | 1 | 0 |

All eight skips were household-history edits under the no-history condition. No historical variation was invented. Product comparisons use decoded brand identity after answer remapping.

## Observed issues

- Current-price edits changed all four predictions. For household 53, moving Dannon from $8.10 to $8.11 preserved Hiland as cheapest, yet both answers changed. For household 99, moving Dannon from $9.80 to $4.89 made it uniquely cheapest; only the with-history edited response selected it.
- Several explanations misstate the displayed prices. The original household-53 no-history response calls Yoplait at $5.30 cheapest despite Hiland at $4.90, and explicitly says its choice is based on lowest price. The household-99 no-history price-edit explanation claims all products are equally priced despite four different displayed prices.
- The original household-53 history explanation calls H5 the most recent purchase even though support records are unordered. These are limited manual factual checks, saved with exact quotes in `manual_review.json`.
- All six annotation attempts are saved unchanged: 6/6 parse as JSON, 2/6 pass structural/traceability checks, and 0/6 report token truncation. These are provisional annotations from the same checkpoint as the predictor; a passing format check does not verify semantic correctness or complete claim coverage. Other edited responses remain not yet annotated.

The first original annotation also incorrectly marks a false cheapest-price claim as supported and omits the explicit lowest-price deciding-rule statement; its nonexact quote is flagged by validation. These limited manual annotation checks are saved in `annotation_review.json`, with no repairs to the model output. The second historical-price annotation passes structural checks but wrongly treats an unknown target paid price as supported; a candidate price does not establish the actual purchase.

## Interpretation

Prediction changes measure sensitivity in these individual responses. An unchanged answer does not establish zero influence, and a changed explanation can be appropriate factual updating. An explicit cheapest-product deciding rule differs from price being one contributing reason; the original household-53 no-history response already misidentifies the minimum, which limits interpretation of its rule consistency. The four matching unchanged reruns are only a basic sanity check. One response per input does not estimate reliable answer distributions. Customer purchases under edited scenarios are unknown; these results do not establish customer counterfactual behavior or conclusive explanation faithfulness.

## Records and resume

This directory contains the pre-inference `manifest.json`, `protocol.json`, `registry.json`, `runtime.json`, `events.jsonl`, original/edited sources and full prompts in the manifest, raw model outputs in `raw_attempts/` and `responses/`, decoded products, six `annotations/` records and diagnostics, manual spot checks, and `results.json`. Existing experiments and notebook cells remain preserved.

Run `.venv/bin/python scripts/run_counterfactual_pilot.py all` to verify and reuse this completed plan without loading the model or repeating any call. Use `status` to inspect counts and `report` to rebuild the saved results. A changed source/protocol/model setting requires a new versioned directory; failed or unfinished attempts are not retried automatically.

## Changed files and checks

Added `choice_trust/development_pilot.py`, `choice_trust/pilot_execution.py`, `choice_trust/pilot_notebook.py`, `scripts/run_counterfactual_pilot.py`, `tests/test_development_pilot.py`, and `docs/DEVELOPMENT_COUNTERFACTUAL_PILOT.md`. Appended 29 cells (14 code, 15 Markdown) to `test.ipynb`; the original 41 cells and outputs are preserved, for 70 total cells.

The targeted 12-test suite passed. All 32 regenerated inputs, canonical-price audit denominators, fixed generation settings, decoded products, target exclusion, six annotation inputs and guide snapshots were verified. The completed-plan resume logged 38 reused records with no model load or added calls. The notebook JSON, executed cell outputs, original-cell checksum, and exact manual spot-check quotations passed verification. `nbformat` is unavailable in the environment; no additional dependency was installed. See `verification.json`.
