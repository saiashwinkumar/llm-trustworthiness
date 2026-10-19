# Resumable execution plan

Prepared after the real six-call development check on 18 October 2026.
The full job has not started. The current counts are in `remaining_work.json`;
the exact case IDs, source hashes and protocol are in `study_plan.json`.

## Fixed inputs and inference

- Dataset: `data_v2/yogurt/cases.jsonl`; original household/support assignments unchanged.
- 804 development, 306 validation and 804 test queries per condition.
- Model: `Qwen/Qwen3-1.7B`, revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`.
- CPU `torch.float32`; 4096 input tokens; 600 explanation tokens; greedy generation;
  thinking disabled. The live server health and source hashes were verified.
- Same prediction prompt and `candidate_sequence_conditional_likelihood_v2` scoring.
  Scores are conditional answer likelihoods, not calibrated customer probabilities.
- Future explanation prompt: `common-evidence-v4-unlimited-citations`;
  citation policy: `available-evidence-unlimited-v1`; JSON schema unchanged.
- Formal tests: seed 42, five count/type-matched random controls and two attempted
  presentation permutations. Duplicate permutation attempts are deduplicated.

## Exact remaining record counts after the check

| Stage | no_history completed / planned | no_history remaining | with_history completed / planned | with_history remaining |
|---|---:|---:|---:|---:|
| Development predictions | 1 / 804 | 803 | 1 / 804 | 803 |
| Validation predictions | 90 / 306 | 216 | 89 / 306 | 217 |
| Test predictions | 0 / 804 | 804 | 0 / 804 | 804 |
| Validation explanations | 3 / 20 | 17 | 3 / 20 | 17 |
| Test explanations | 0 / 100 | 100 | 0 / 100 | 100 |
| Validation explanation-test cases fully accounted for | 0 / 20 | 20 | 0 / 20 | 20 |
| Test explanation-test cases fully accounted for | 0 / 100 | 100 | 0 / 100 | 100 |
| Test systematic-test cases | not scheduled | — | 0 / 30 | 30 |

There are **3,647 new original prediction calls remaining** and **234 planned new
explanation calls**. Case completion is not the same as individual scoring-call
completion: eight saved validation intervention measurements are already reused.

## Reuse with explicit provenance

`outputs_resumed_v1` contains 181 reused predictions, eight explanations and ten
measured interventions. Every imported record retains `reuse_origin` and its complete
`original_record`; effective hashes and parent links are sealed for this new run.
All original source folders remain unchanged. Exact prediction prompts, case hashes,
model identity, scoring method, full server metadata and repeated scores were checked.

The validation explanation set reuses the four v3 smoke responses, followed by the
two v2 responses for `row-1409`. Their original prompt versions and previous
assessments are preserved; the separate unlimited-citation assessment supplies
intervention eligibility. The two development-check explanations use the new prompt.
Four earlier v2 attempts on the same first two validation cases remain archived as
alternate attempts; they are not silently treated as additional purchase occasions.

The old pilot's 20 test predictions per condition used a different prediction prompt
and remain a separate historical cohort. They do not reduce the 804 comparable test
predictions per condition. Notebook results also use different prompts/support
assignments and are not imported. Synthetic results are excluded.

## Previously blocked validation measurements

The exact v3 responses blocked solely by the old cap were:

- `row-1351 / no_history`
- `row-84 / no_history`
- `row-84 / with_history`

The `recovery` command performs **12 remaining scoring calls** under their original
one-control smoke protocol: six cited removal/retention measurements corresponding
to explicit old skips, plus six matched-control measurements that were never planned
after the old eligibility failure. Counts are eight calls for `no_history` and four
for `with_history`. Their four already-measured presentation checks are reused.
Old skip rows remain untouched; new measurements are separate records.

These 12 measurements overlap the formal five-control validation tasks and are reused
there by exact prediction/spec IDs. Do not add them twice. The two selected v2
responses had **pending**, not explicitly skipped, intervention work; their 24 cited
and random-control scoring calls are included in the formal validation phase.

Across the six reused validation responses, **74 further scoring calls** are already
determinable, including recovery. The full validation scope has **70 remaining fixed
presentation calls**. Remaining cited/retained/random/claim counts depend on the 34
new responses, so their final total cannot truthfully be fixed before generation.

## Planned test interventions and overlap

For each of the 100 selected cases per condition:

- If supporting citations are usable: remove them, retain only them, and run five
  matched random removal/retention pairs: **12 scoring calls per eligible response**.
- If a saved, admissible explicit claim exists: score its exact proposed edit once.
- Run the fixed presentation checks even when an explanation is poor or unusable.

There are **195 presentation calls per condition**, not 200, because duplicate
permutation attempts are deduplicated. The 30 with-history systematic cases have
**450 admissible planned scoring calls**: 240 price edits, 120 advertisement toggles,
30 history masks, and 60 presentation permutations. Those 60 presentation calls are
also in the explanation-test suite and must run only once.

Thus test has **780 distinct fixed intervention scoring calls**, plus **0–2,400**
cited/random scoring calls and **0–200** exact-claim calls, depending on the actual
200 explanation responses. A missing claim, empty supporting citations, or structural
issue produces a specific saved skip; it is not an unperformed call counted as measured.

## Small real execution check and actual records

The saved check is `outputs_development_check_v1/execution_check.md`. It includes
the full actual inputs, raw outputs, edited inputs, numerical measurements and record
hashes. Case `row-2342`, household 96, is development-only. Both conditions were run.
The edit changed `P_A` from 8.600000300000001 to 6.880000240000001, selected before
reading the explanation and independently of the observed outcome.

| Condition | Original prediction | Edited prediction | Original A score | Edited A score |
|---|---|---|---:|---:|
| no_history | A | A | 0.9998737498207105 | 0.9998987030469073 |
| with_history | A | A | 0.9999983583753944 | 0.9999984566351302 |

The explanations cited four and thirteen available IDs, respectively. The no-history
text says A is higher-priced than C, then says their prices are equal. The with-history
text calls A the cheapest despite B costing less. These observations are preserved.
Execution success requires returned calls, normalized candidate scores, retained raw
text, applied edits and saved measurements—not a changed answer, correct prediction,
flattering explanation, or favorable effect direction.

## Resume commands

Run from `/Users/saiashwin/llm-trustworthiness`. Keep the existing verified server and
tunnel running. No package installation, model change or data preparation is needed.

```bash
# Read-only status; no model calls.
.venv/bin/python -B scripts/run_resumed_study.py status

# Health only, using the existing key privately from .env.
.venv/bin/python -B scripts/verify_cpu_server.py

# Source-protocol recovery; 12 remaining scoring calls.
caffeinate -i .venv/bin/python -B -u scripts/run_resumed_study.py recovery

# Complete predictions for development.
caffeinate -i .venv/bin/python -B -u scripts/run_resumed_study.py development

# Complete validation predictions, selected explanations and explanation tests.
caffeinate -i .venv/bin/python -B -u scripts/run_resumed_study.py validation

# After actually reviewing recorded validation outcomes, freeze the protocol.
.venv/bin/python -B scripts/run_resumed_study.py freeze --ack-validation-review

# Remaining test predictions, 100 explanations/tests per condition, 30 systematic cases.
caffeinate -i .venv/bin/python -B -u scripts/run_resumed_study.py test

# Rebuild reports from saved records; no inference.
.venv/bin/python -B scripts/run_resumed_study.py report
```

Defaults are `--out outputs_resumed_v1 --control execution_resumed_v1`. Repeat the
same interrupted phase to resume; completed IDs are skipped. One writer is allowed.
Each completed response or scoring measurement is saved immediately. An in-flight
call interrupted before its record was saved may repeat. Logs are in the control
folder; outputs and reports are in the output folder. Do not edit the plan or protocol
code mid-run. The freeze checks accounted-for attempts, including poor responses and
explicit skips; it never requires a favorable result.

If the SSH tunnel must be reopened, use the current EC2 IP:

```bash
ssh -i ~/Downloads/llm-experiment.pem -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8000:127.0.0.1:8000 ubuntu@54.252.237.68
```

The bounded check itself can be resumed using
`.venv/bin/python -B -u scripts/check_development_workflow.py`; its six records are
already complete. Do not rerun it after changing source code or settings.

## Subsets and final reporting

Predictions cover every query in all three splits under both conditions. Explanation
analyses cover **1/804 development cases per condition** (execution check only),
**20/306 validation cases per condition**, and **100/804 test cases per condition**.
Systematic counterfactual analysis covers **30/804 test cases, with_history only**.
Manual grounding review remains **20 preselected test explanations per condition**.
No explanation-wide or counterfactual-wide conclusion should claim coverage of every
purchase occasion. Report prompt-version cohorts, attempts, measured calls and skips
separately; eligibility is not factual correctness or behavioral faithfulness.
