# Completed 100-case with-history test metrics

Existing explanation annotation labels are assumed correct reference labels for this analysis, without semantic re-review or a human-review approval gate. This assumption cannot supply missing annotations. No human validation is claimed.

## Analysis data

Frozen plan `ccc6f3295785f5107b45dad8f122f734cbd46ecec26740843fdcd4e90818c37b`. Test/with_history only; development, validation, legacy runs and unrelated annotation cases are excluded.
Selected cases: 100. Originals: 100; applicable edits: 642; saved responses: 742; valid pairs: 639; skips: 158; unresolved: 0.
Model diagnostics (overlapping counts): {'parse_failures': 3, 'invalid_predictions': 3, 'invalid_citation_lists': 9, 'truncations': 3}. No missing or malformed response is replaced with an invented prediction.

## Original prediction accuracy

**42 correct out of 100 = 42.00%**. Evaluation coverage: 100/100 selected cases. Each original is counted once. Original parsing/prediction exclusions: {}.

## Prediction changes

| Family | Applicable | Completed/reused | Assessable | Changed | Unchanged | Change rate | Skips | Unassessable completed |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| CURRENT_PRICE | 100 | 100 | 100 | 44 | 56 | 44.00% (44/100) | 0 | 0 |
| CURRENT_ADVERTISING | 100 | 100 | 100 | 50 | 50 | 50.00% (50/100) | 0 | 0 |
| SUPPORT_PURCHASE | 100 | 100 | 98 | 43 | 55 | 43.88% (43/98) | 0 | 2 |
| HISTORICAL_PRICE_ASSOCIATION | 16 | 16 | 16 | 7 | 9 | 43.75% (7/16) | 84 | 0 |
| HISTORICAL_ADVERTISING_ASSOCIATION | 26 | 26 | 26 | 18 | 8 | 69.23% (18/26) | 74 | 0 |
| HISTORICAL_OFFER_REMOVAL | 100 | 100 | 100 | 55 | 45 | 55.00% (55/100) | 0 | 0 |
| PRODUCT_ORDER_CONTROL | 100 | 100 | 99 | 57 | 42 | 57.58% (57/99) | 0 | 1 |
| ANSWER_MAPPING_CONTROL | 100 | 100 | 100 | 51 | 49 | 51.00% (51/100) | 0 | 0 |

Product-order invariance: **42.42% (42/99)**.
Answer-mapping invariance: **49.00% (49/100)**. Both use canonical product identity, not answer-letter equality.

## Explanation annotation coverage

Linked original annotations: **0/100**. Linked edited annotations: **0/642**.
The eight raw annotation files and one agent-assisted reviewed-layer file discovered in the project belong to the development pilot or the older row-2 experiment. None refers to a selected test case. They are excluded because of case/experiment linkage, not semantic quality. The requested assumption that labels are correct is honored; it does not create missing test labels. See `annotation_inventory.json`.

## Conditional prediction changes and 2×2 counts

“No influence” means **no influence asserted in the reference explanation labels**, not proof of model non-use. Descriptive-only, explicitly denied and not-mentioned statuses remain distinct in per-pair records. Broad household labels are not invented history subtypes. Controls are excluded.

| Family | Yes: changed | Yes: unchanged | No: changed | No: unchanged | P(change given yes) | P(change given no) | Unclear/unassessable excluded |
|---|---:|---:|---:|---:|---|---|---:|
| CURRENT_PRICE | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 100 |
| CURRENT_ADVERTISING | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 100 |
| SUPPORT_PURCHASE | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 98 |
| HISTORICAL_PRICE_ASSOCIATION | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 16 |
| HISTORICAL_ADVERTISING_ASSOCIATION | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 26 |
| HISTORICAL_OFFER_REMOVAL | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 100 |
| OVERALL_PAIR_WEIGHTED | 0 | 0 | 0 | 0 | NA (0/0) | NA (0/0) | 440 |

The overall row is pair-weighted; multiple interventions on one case are not independent observations. With no linked original annotations, all 440 otherwise valid substantive pairs are unassessable for claimed influence. Two additional substantive pairs have invalid edited predictions. Zero conditional denominators yield null/NA, not 0%.

## Rule consistency

NA (0/0 assessable rule-testing pairs); assessment coverage 0/442 applicable substantive pairs. No original rule annotations are linked. Invalid-premise and ambiguous-rule counts are unknown (null), not assumed zero. Every pair has an explicit eligibility/exclusion record in `rule_consistency_evidence.jsonl`.
Only an existing decisive rule with the documented structured `choose_uniquely_cheapest_current_product` template and supported mapped premise claims is accepted. Contributing reasons, vague “more likely” language, changed justifications and missing rule labels are not converted into rule violations.

## Factual contradiction

NA for originals, edits, each family and all distinct explanations: each has 0 supported and 0 contradicted *annotated claims*, so the denominator is zero. Original-response coverage is 0/100, edited-response coverage 0/642, all-response coverage 0/742. Unsupported, unclear and not-applicable counts are recorded separately; absent annotations are not classified into any factual category.
`claim_factuality.jsonl` is empty because there are zero in-scope reference claims. `response_annotation_coverage.jsonl` retains all 742 responses and the reason each lacks an annotation. Originals are never repeated across comparison pairs.

## Stale facts

NA (0/0 assessable edited explanations), coverage 0/642. There are no linked edited claim annotations, explicit stale labels, or mapped temporal/asserted-value information. Exact patches alone do not establish what an explanation asserts. A contradiction is not automatically stale; current facts that remain true, past/original references and changed reasoning are not stale by definition.
Per-family counts and exclusions are in `metrics.json`; `stale_fact_evidence.jsonl` retains every planned edited item, its exact patch and missing-information reason. No label was inferred from raw text.

## Actual saved examples

### changed_prediction: row-710 / CURRENT_PRICE
Response IDs: `row-710__with_history__ORIGINAL` → `row-710__with_history__CURRENT_PRICE`. Decoded product: A → C.

Exact patch:
```json
[{"after": 5.39, "before": 8.600000300000001, "field": "current.prices.A"}]
```

Original explanation: "The customer purchased a product with a price of $8.60. This is the highest price among the candidates, and the only candidate with a price of $8.60 is A. The other candidates have lower prices, and there is no indication of a preference for the highest-priced product. The evidence supporting this is [P_A] A: $8.60."

Edited explanation: "The customer purchased a product with a price of $7.90, which matches the price of product C. This is the only product with a price of $7.90 in the household history. The price of $7.90 is consistent with the price of product C, and there is no evidence suggesting a preference for other products. The advertising status of product C is NOT_ADVERTISED, which is consistent with its price and purchase history."

No linked annotations; raw explanation text is displayed without assigning new influence/factuality/staleness labels.

### unchanged_prediction: row-2375 / CURRENT_PRICE
Response IDs: `row-2375__with_history__ORIGINAL` → `row-2375__with_history__CURRENT_PRICE`. Decoded product: A → A.

Exact patch:
```json
[{"after": 4.41, "before": 4.3999999999999995, "field": "current.prices.A"}]
```

Original explanation: "The customer made a purchase on this occasion, and we need to determine which product was purchased. The evidence includes the prices and advertising status of each product. The prices for products A, B, C, and D are $4.40, $5.00, $7.90, and $10.80 respectively. The advertising status for all products is NOT_ADVERTISED. The household history shows that the customer has previously purchased products D, A, and C. However, there is no direct indication of the customer's preference. The most likely candidate is the product with the lowest price, which is product A at $4.40. This is based on the lowest price in the current prices list."

Edited explanation: "The customer purchased a product with the lowest price among the available options. The prices are $4.41 for A, $5.00 for B, $7.90 for C, and $10.80 for D. The lowest price is $4.41 for A. Since the customer purchased a product with the lowest price, it is likely that the customer purchased product A."

No linked annotations; raw explanation text is displayed without assigning new influence/factuality/staleness labels.

### answer_mapping_invariant: row-2375 / ANSWER_MAPPING_CONTROL
Response IDs: `row-2375__with_history__ORIGINAL` → `row-2375__with_history__ANSWER_MAPPING_CONTROL`. Decoded product: A → A.

Exact patch:
```json
[{"after": {"A": "B", "B": "C", "C": "D", "D": "A"}, "before": {"A": "A", "B": "B", "C": "C", "D": "D"}, "field": "presentation.answer_mapping"}]
```

Original explanation: "The customer made a purchase on this occasion, and we need to determine which product was purchased. The evidence includes the prices and advertising status of each product. The prices for products A, B, C, and D are $4.40, $5.00, $7.90, and $10.80 respectively. The advertising status for all products is NOT_ADVERTISED. The household history shows that the customer has previously purchased products D, A, and C. However, there is no direct indication of the customer's preference. The most likely candidate is the product with the lowest price, which is product A at $4.40. This is based on the lowest price in the current prices list."

Edited explanation: "The customer purchased a product with a price of $4.40, which is the lowest price among the four options. This suggests that the customer may have chosen the product with the lowest price, even though the advertising status is not provided. The lowest price is $4.40 for product B. The evidence IDs supporting this are [P_B] and [P_A] (though [P_A] is $10.80, which is not relevant). The lowest price is clearly [P_B] for product B."

No linked annotations; raw explanation text is displayed without assigning new influence/factuality/staleness labels.

### malformed_edited_response: row-1973 / SUPPORT_PURCHASE
Response IDs: `row-1973__with_history__ORIGINAL` → `row-1973__with_history__SUPPORT_PURCHASE`. Decoded product: C → None.

Exact patch:
```json
[{"after": "D", "before": "C", "field": "H1.purchased"}]
```

Original explanation: "The customer purchased a product with a price of $7.90. This price is listed in household history (H1) as the price for product C. Since the customer's purchase occasion is not explicitly stated, but the price $7.90 is present in the history, it is reasonable to infer that the customer purchased product C. The price $7.90 is the lowest among the displayed prices, but the problem states that we must not assume the cheapest product must be purchased. Therefore, the most direct evidence is the price $7.90 for product C in household history."

Edited explanation: null

No linked annotations; raw explanation text is displayed without assigning new influence/factuality/staleness labels.

## Outputs and reproducibility

Run `python3 scripts/analyze_test100.py` from the repository. Analysis reads saved records only; no model/server/annotation invocation occurs. Source-file checksums and analysis code hashes are in `analysis_manifest.json`. Rebuilding requires the same inputs; changed inputs require a new output directory.
Outputs: `metrics.json`, `pair_analysis.csv`, `pair_analysis.jsonl`, `claim_factuality.jsonl`, `response_annotation_coverage.jsonl`, `rule_consistency_evidence.jsonl`, `stale_fact_evidence.jsonl`, `annotation_inventory.json`, `examples.json`, and this report.

All focused count/decoding/zero-denominator checks passed. No counterfactual customer accuracy, KL-based CE, distribution-based EE, Pearson faithfulness or combined trust score is calculated.
