# Test / with-history 100-case overnight handoff

**Launched and running; the study is not complete.** The authoritative writer is on EC2. Closing the Mac/SSH connection does not stop it.

- EC2: `i-0fca8c4016c36b737`, `ubuntu@54.252.237.68`.
- Remote root: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1`.
- Study directory under that root: `choice_study/test_with_history_100_v1/`.
- Frozen plan: `ccc6f3295785f5107b45dad8f122f734cbd46ecec26740843fdcd4e90818c37b`.
- Selection: seed 42, 100 actual test queries across 20 households; IDs in `selected_cases.json`; other 704 test IDs in `remaining_test_case_ids.json`.
- Runner: PID **78498**, screen **choice-test-100-night**.
- Model server: PID **78300**, screen **choice-model-test100**, pinned Qwen3-1.7B CPU float32, exact existing joint generator with 512-token output bound.
- Verified one Python runner, one Python model server and a held exclusive runner lock. Safe verification metadata is in `launch_state.json`.
- No matching joint originals existed in the inspected project roots: **0 reused; 100 originals require generation**. One original was already saved in the initial snapshot; the other 99 remained pending.

## Frozen workload

| Family | Applicable edits | Predefined skips |
|---|---:|---:|
| CURRENT_PRICE | 100 | 0 |
| CURRENT_ADVERTISING | 100 | 0 |
| SUPPORT_PURCHASE | 100 | 0 |
| HISTORICAL_PRICE_ASSOCIATION | 16 | 84 |
| HISTORICAL_ADVERTISING_ASSOCIATION | 26 | 74 |
| HISTORICAL_OFFER_REMOVAL | 100 | 0 |
| PRODUCT_ORDER_CONTROL | 100 | 0 |
| ANSWER_MAPPING_CONTROL | 100 | 0 |

Total: **100 originals + 642 edited responses = 742 applicable joint inputs**. Another 158 items are explicitly not applicable. No unchanged reruns, repeated sampling, bulk annotation, or continuation to the remaining 704 test cases is scheduled.

The downloaded initial snapshot contains **3 real responses** (one original, current-price edit, current-advertising edit), 158 skips, 738 pending items and one known in-flight call. These counts are a snapshot, not a final report. The notebook shows actual saved examples and explicit partial denominators; refresh before interpreting newer progress.

## Inspect on EC2

```bash
ssh -i ~/Downloads/llm-experiment.pem ubuntu@54.252.237.68
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
screen -ls
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/run_test100.py status
cat choice_study/test_with_history_100_v1/runner_state.json
tail -n 40 choice_study/test_with_history_100_v1/runner.log
```

For live logs:

```bash
tail -f choice_study/test_with_history_100_v1/runner.log
```

## Refresh the Mac notebook without inference

From the local repository:

```bash
.venv/bin/python scripts/sync_test100.py
```

Then rerun only notebook cells **72, 74, 76 and 78**. Cells 71–79 were appended; the prior 70 cells and outputs are preserved. The sync checks the frozen plan ID, reads remote files only, and refuses to replace a differing immutable completed response. Loading results never calls the model. Source targets are used only for original accuracy; no edited-scenario customer accuracy is computed. All new explanations remain unannotated and unreviewed.

## Resume if the runner stops

First inspect status, logs and `screen -ls`. Do not start another writer while PID 78498/the runner session remains active. After it stops, on EC2:

```bash
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/launch_test100_existing_aws.py \
  --root /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1 --launch
```

The launcher privately inherits the existing model-server credential; do not print/copy it. The same compatible server is reused. The runner verifies frozen sources, full inputs/settings, saved response bodies and decoded identities, then processes pending work only. Failed or uncertain requests are not automatically repeated. Server journals can recover completed requests after lost HTTP delivery; unresolved work prevents a complete status.

The runner exits after this stage. **The model server and EC2 instance remain running afterward.** No shutdown is scheduled.

## Verification and launch issues retained

All 950 initially packaged file hashes matched, and **15 focused tests passed on EC2**. Tests used synthetic fixtures, not model inference. The deployed base server matches the existing server/scoring code. The legacy `/explain` route used a different token bound and stripped text, so the existing server was gracefully replaced with a wrapper around the unchanged exact joint generator; no duplicate model was loaded.

Two launcher-only errors are preserved in `launch.log`: an initial false duplicate from counting the screen supervisor, and a metadata logging parameter collision after successful runner startup. Both are corrected and recorded in `deployment_amendments.json`; predictor/intervention code and the running job were unchanged. `launch_state.json` verifies the actual active process independently of those old errors.

A narrow TCP22 ingress rule for client `223.185.21.253/32` restored SSH access after the client IP changed. The previous SSH rule remains, and model port 8000 remains private. See `access_change.json`.

## Changed files

- `choice_trust/test100_plan.py`, `test100_execution.py`, `test100_server.py`, `test100_results.py`.
- `scripts/run_test100.py`, `launch_test100_existing_aws.py`, `package_test100.py`, `sync_test100.py`.
- `tests/test_test100_plan.py`, `test_test100_execution.py`, `test_test100_server.py`.
- `docs/TEST_WITH_HISTORY_100.md`; appended read-only `test.ipynb` cells 71–79.
- New versioned study records and deployment/progress snapshots in this directory.

Source data, established intervention implementations, factual renderer, predictor prompt/settings, annotation guide, raw pilot annotations and agent-assisted review proposals are preserved. No automatic annotation labels are accepted for this stage.
