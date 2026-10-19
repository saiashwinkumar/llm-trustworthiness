# Recorded research findings



no_history: measured test accuracy 40.0% on 20 cases / 8 groups; variable-candidate chance 25.0%. 95% cluster interval: [0.167, 0.722].

no_history: cited-versus-random removal advantage -0.7691, n=1, 95% CI=unavailable; uncertain difference (interval includes zero or unavailable).

no_history: calibration unavailable; no validation scores were supplied.

no_history: 9 invalid, 0 abstaining and 0 truncated explanations among 10 attempts; 10 test predictions have no explanation attempt.

no_history: factual grounding is not measured; no completed manual reviews.

with_history: measured test accuracy 90.0% on 20 cases / 8 groups; variable-candidate chance 25.0%. 95% cluster interval: [0.625, 1.000].

with_history: cited-versus-random removal advantage 0.1148, n=10, 95% CI=[-0.001, 0.329]; uncertain difference (interval includes zero or unavailable).

with_history: calibration unavailable; no validation scores were supplied.

with_history: 0 invalid, 0 abstaining and 0 truncated explanations among 10 attempts; 10 test predictions have no explanation attempt.

with_history: factual grounding is not measured; no completed manual reviews.



## Limits



LEGACY IMPORT: historical records are readable, but original code execution and unrecorded raw calls cannot be independently verified.

Legacy interventions did not save complete edited score vectors. These remain not measured/unavailable; no vectors are reconstructed.

This is a separate read-only conversion. New experiments must use a new run directory.

Scores are normalized answer likelihoods, not validated customer probabilities.

Edited scenarios have no observed outcome. Sensitivity does not establish customer motives.

Valid citations do not validate explanation prose; manual grounding review is separate.

Group-cluster intervals are exploratory with few groups. Subgroups are not confirmatory.

Candidate identities remain visible in retention tests; priors can preserve predictions.
