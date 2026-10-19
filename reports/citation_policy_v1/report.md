# Saved-response citation reassessment

Policy: `available-evidence-unlimited-v1`. Future prompt: `common-evidence-v4-unlimited-citations`.

Original records, text, prompts and previous assessments are preserved in the source files and copied into assessments.jsonl. Source hashes and line numbers bind each assessment to its original attempt.

| Source | Split | Condition | Responses | Previously usable | Now usable | Newly usable |
|---|---|---|---:|---:|---:|---:|
| choice_study/runs/20261018T104944_832764 | development | no_history | 2 | 2 | 2 | 0 |
| choice_study/runs/20261018T104944_832764 | development | with_history | 2 | 1 | 1 | 0 |
| outputs_cpu_pilot | test | no_history | 10 | 1 | 1 | 0 |
| outputs_cpu_pilot | test | with_history | 10 | 10 | 10 | 0 |
| outputs_cpu_real_v2_smoke | validation | no_history | 3 | 0 | 3 | 3 |
| outputs_cpu_real_v2_smoke | validation | with_history | 3 | 0 | 3 | 3 |
| outputs_cpu_real_v3_smoke | validation | no_history | 2 | 0 | 2 | 2 |
| outputs_cpu_real_v3_smoke | validation | with_history | 2 | 1 | 2 | 1 |
| outputs_cpu_smoke | validation | with_history | 2 | 2 | 2 | 0 |

Total: 26/36 responses usable; 9 newly usable.

Usable means eligible for cited-evidence removal/retention. It does not certify factual statements or faithfulness. No predictions, explanations, or intervention measurements were generated. Existing skipped measurements remain skipped.

Notebook rows are attempts, not unique cases. Its four existing with-history edits belong to the earlier prompt; the revised explanation has no supporting citations. Finish metadata was not saved by the notebook.

Checks are separate: JSON readability; required fields; field types; unavailable IDs; duplicate IDs; empty supporting citations; recorded truncation. Wrapped JSON is identified explicitly.

choice_study/runs/20261018T104944_832764 / with_history: No supporting evidence IDs supplied (1)

outputs_cpu_pilot / no_history: Unavailable IDs in evidence_ids: H1 (9)
