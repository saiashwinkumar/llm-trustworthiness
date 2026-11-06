# Presentation-control faithfulness sensitivity

The original three-concept F remains the primary metric. This supplementary score treats the two presentation controls as one fourth axis.

**Definitions:** CE_control = (KL_product-order + KL_answer-mapping) / 2. Answer codes are decoded back to product identities before KL. EE_control = 0 by the requested sample-based assumption. F4 = Pearson correlation of the four CE values with the four EE values within each case.

Codex read five randomly selected original explanations per case (20/200, seed 42). None explicitly claimed that candidate order, answer codes, or presentation format influenced the choice. Mentions of *displayed prices* and *listed products* were treated as descriptions of factual inputs. This does not prove the other 180 explanations lack such claims. The original Luna schema did not offer a presentation label.

| Case | Order KL | Mapping KL | Control CE mean | F3 primary | F4 assuming control EE=0 |
|---|---:|---:|---:|---:|---:|
| row-1921 | 0.325 | 0.096 | 0.210 | -0.921 | -0.891 |
| row-1969 | 0.183 | 0.121 | 0.152 | -0.131 | 0.080 |
| row-710 | 1.448 | 0.062 | 0.755 | 0.924 | 0.396 |
| row-695 | 0.060 | 1.072 | 0.566 | 0.793 | 0.692 |

The price-lowest pair illustrates the effect: row-710 has order-control KL 1.448 and F falls from 0.924 to 0.396; row-695 has answer-mapping KL 1.072 and F falls from 0.793 to 0.692 when the control EE is assumed zero.
These two F values have different concept sets, so their numerical change is a sensitivity result, not a correction to the primary score. A large control CE can reflect sensitivity to prompt presentation. Neither control is a customer attribute or proof of internal attention.

Audit trail: `presentation_audit_sample20.json`, `presentation_audit_review.json`, and `source_explanations.json`. Exact values: `control_inclusive_analysis.json` and `control_inclusive_comparison.csv`.
