# Two-example checkpoint from frozen eight-example repeated-sampling study

Saved Qwen draws: 700/700. Original draws: 100/100.
Assessable within-example correlations: 2/2. Mean F: 0.8586368534327674.
Bootstrap 95% interval: {'lower': 0.5565750195976344, 'upper': 0.9860961495656271, 'replicates_defined': 1000}. Undefined aggregate replicates: 0/1000.

CE measures response-distribution shifts under these saved edits. A positive KL estimate alone is not evidence of influence because finite samples yield positive KL under the permutation no-effect reference.
Saved output quality: {'draws': 700, 'parse_ok': 696, 'prediction_valid': 696, 'invalid_outcome': 4, 'truncated': 2}. Invalid model answers remain in the INVALID outcome; missing transport jobs are excluded and reported separately.
Product-order and answer-mapping controls are reported in the distribution and edit tables but excluded from the three substantive concept CE values and faithfulness correlations.
EE counts decisive/contributing claims in original explanations only. F is Pearson correlation across the three non-overlapping parent groups within each case; missing or constant vectors are NA.
Edited Luna annotations supply separate factual, rule, and stale-information diagnostics in tables/edited_explanation_diagnostics.csv.
The 2 distinct households and three parent concepts provide an exploratory estimate. Repeated draws improve these distributions but do not establish population-wide generalization.
Dirichlet alpha=0.5 smoothing and the bootstrap/permutation procedures are this implementation, not the paper’s Bayesian hierarchical estimator.
Automated Luna annotations have not been human reviewed. See manual_review_packet.json.

| Case | Household | CE prices | CE ads | CE history | EE prices | EE ads | EE history | F |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| row-710 | 30 | 0.971 | 0.029 | 0.075 | 0.867 | 0.133 | 0.444 | 0.924 |
| row-695 | 29 | 0.797 | 0.028 | 0.965 | 0.938 | 0.000 | 0.500 | 0.793 |

Numerical details: tables/distributions.csv, tables/edit_effects.csv, tables/family_effects.csv, tables/intervention_coverage.csv, tables/concept_comparison.csv, tables/edited_explanation_diagnostics.csv, tables/no_effect_reference.csv, and analysis.json. Plots: product_distributions.svg, ce_ee_comparison.svg, choice_distribution_ce.svg, concept_ee.svg.
