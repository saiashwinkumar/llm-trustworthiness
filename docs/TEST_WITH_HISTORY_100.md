# Frozen test / with-history 100-case study v1

This stage collects one joint explanation–prediction response per applicable original or edited input. It uses only 100 frozen test queries with history, seed 42, and the eight existing intervention implementations. It has no unchanged-input reruns, repeated sampling, bulk annotation, or automatic continuation to other cases. Actual edited-scenario purchases are unknown.

## Selection and interventions

`choice_study/test_with_history_100_v1/selected_cases.json` freezes 100 actual queries across 20 test households, sampled by seeded household round-robin without model outputs or target-based selection. Exhausted small households leave the rotation. The other 704 actual test query IDs are saved separately. Household splits and supplied support selections are preserved.

The manifest contains 900 items: 100 originals, 642 applicable edited inputs, and 158 predefined not-applicable interventions. Applicable edits are 100 each for CURRENT_PRICE, CURRENT_ADVERTISING, SUPPORT_PURCHASE, HISTORICAL_OFFER_REMOVAL, PRODUCT_ORDER_CONTROL and ANSWER_MAPPING_CONTROL, plus 16 historical-price and 26 historical-advertising association edits. The latter two families explicitly skip invariant associations or identical offer vectors. No skipped case is replaced.

CURRENT_PRICE alternates the already tested preserve-cheapest and reverse-cheapest rules by frozen selection index, starting with preserve. It uses the existing development-only bounds ($0.30–$19.30), assumed dollar amounts and ROUND_HALF_UP two-decimal canonical representation. All interventions delegate to the existing `plan_edit` and `verify_edit`, with full regeneration through the compact factual renderer. Historical offer removal retains every support purchase and replaces only its prices/advertising with NOT_PROVIDED. Counts/offer associations remain dependent parts of HOUSEHOLD_HISTORY.

The target is isolated in `evaluation_targets.json`; it never enters any predictor entry, server request prompt, or selection/intervention decision. It is used only by the read-only original-accuracy report.

## Transport and execution

The legacy server `/explain` route is unsuitable: it has a 600-token limit and strips decoded text. `choice_trust.test100_server:app` wraps the same existing server application and model with an authenticated transport that calls the unchanged `generate_joint_response` helper: 512 new tokens, greedy, one beam, no thinking, explicit existing settings, and a 4096-token input bound without truncation. It preserves raw text, token IDs, full prompts, model/tokenizer revision, settings and parser diagnostics. It does not change the predictor prompt or model.

On the existing AWS host, the launcher checks the frozen deployment, existing server identity and competing workloads before any restart. If the legacy server needs the transport wrapper, it gracefully replaces that one process using its existing environment and pinned checkpoint, retaining credentials privately in memory. It never loads a duplicate model or modifies the original project files. A replacement server remains running after study completion, as does EC2. A server import preflight uses the existing Python environment before stopping the legacy process.

The runner uses one exclusive process lock, and server/client journals reserve each request before generation. Completed response files are never overwritten. Requests have full input/runtime signatures. A lost HTTP response is recovered by reading the server journal; generation is never automatically repeated after failed or uncertain execution. Malformed model output is saved as a completed measured response with parsing diagnostics, not replaced with a fallback answer. Infrastructure failure stops the runner with its completed work intact. Remaining unresolved items prevent a complete status.

The runtime fingerprint and rendered prompts are frozen before the first inference. Original reuse requires identical case/support source observations (including renderer and price policy), candidate mapping, full messages and rendered prompt, model/tokenizer revision, device/precision/library metadata, and effective settings. Answer-only or separately generated explanations cannot match. Original sources are searched in the explicitly recorded existing project roots; reuse includes source-file hashes and any linked observation manifest.

## Commands

On the Mac, these commands only prepare/inspect; they do not infer:

```bash
.venv/bin/python scripts/run_test100.py plan
.venv/bin/python scripts/run_test100.py status
.venv/bin/python scripts/run_test100.py reuse-inventory
```

On EC2, use the deployed continuation root and existing venv:

```bash
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
/home/ubuntu/customer-choice-trust/.venv/bin/python scripts/run_test100.py status
screen -ls
tail -n 40 choice_study/test_with_history_100_v1/runner.log
```

The persistent runner session is `choice-test-100-night`; the compatible replacement model-server session is `choice-model-test100`. The secure launcher reads the existing server credential privately from its process environment, never from an interactive prompt and never into notebook output, logs or command arguments.

For initial launch or a stopped run with the same model server:

```bash
/home/ubuntu/customer-choice-trust/.venv/bin/python scripts/launch_test100_existing_aws.py \
  --root /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1 --launch
```

Inspect `screen -ls` and runner state before resuming. The launcher refuses competing workloads/sessions, and the runner verifies the complete frozen configuration and saved response bodies before using completed records. Failed/uncertain requests require journal inspection; this command does not automatically retry them. No AWS instance/service shutdown is scheduled by this stage.

## Read-only results

Notebook cells 71–79 append a read-only section after the previous 70 preserved cells. Loading them cannot infer, retry or annotate. A Mac view reflects only its downloaded snapshot; explicitly synchronize remote saved records before loading newer results. Accuracy is reported only for original predictions with known targets and explicit assessable/selected denominators. Family comparisons use decoded product identity and distinguish applicability, pending, failed, uncertain and unassessable pairs. Counterfactual customer accuracy is not computed.

All new responses are NOT_ANNOTATED and factually UNREVIEWED. The guide, six raw pilot annotations, and agent-assisted proposed review layer are preserved by hash. They are not treated as reliable automatic evaluation labels. Structural validity and correct parsing do not establish factual correctness or explanation faithfulness.

## Files and verification

New modules: `test100_plan.py`, `test100_execution.py`, `test100_server.py`, `test100_results.py`. New scripts: `run_test100.py`, `launch_test100_existing_aws.py`, `package_test100.py`. Focused tests cover selection/bounds/source integrity, safe resume, exact source/configuration reuse, lost-response recovery, corrupt/missing completed files, journal idempotence, whitespace preservation, and rejection before inference. Synthetic test responses are explicitly fixtures, never study measurements. This document and the appended notebook explain execution and inspection. The versioned study directory stores all frozen plans and incremental records.

## Mac snapshot refresh

Run `.venv/bin/python scripts/sync_test100.py` to download saved progress and responses, then rerun only notebook cells 72, 74, 76 and 78. Synchronization verifies the remote frozen plan ID and refuses to replace a differing immutable completed response. It makes no inference or annotation calls. The EC2 runner continues independently when the Mac disconnects.

The added SSH rule permits only TCP22 from the current client /32; the previous rule is preserved and the model port remains private. The first launcher rejected its screen supervisor as a duplicate Python process, and a later metadata field collision occurred after the runner successfully started. Both were launcher-only fixes; original errors and source amendments are retained. The actual runner was verified separately by PID, one held lock, sessions, logs and measured response files.
