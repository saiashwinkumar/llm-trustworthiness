# Eight-example repeated-sampling experiment handoff

Experiment ID: `f9b1b6bcfd4ee5fea677e849b1356a47c6092375c6208417ac492af1a5e12571`.

Frozen eight selected cases (one per household):

| Case | Household |
|---|---:|
| row-2374 | 98 |
| row-710 | 30 |
| row-1921 | 77 |
| row-695 | 29 |
| row-54 | 4 |
| row-1875 | 75 |
| row-1969 | 81 |
| row-2231 | 90 |

The frozen manifest has 8 originals and 52 applicable edited inputs. At 50 draws per input, the job total is 400 original plus 2,600 edited responses, 3,000 total. Twelve historical-association edits retain their saved source-based skip reasons. The `manifest.json` includes the exact original and edited facts, messages, source edit values, support identities, candidate mappings, source hashes, crosswalk, randomized job order and seed derivation. `protocol.json` is a compact review copy. No old deterministic response was reused as a sampled draw.

The existing EC2 instance is `i-0fca8c4016c36b737`, `m7i.xlarge`, in `ap-southeast-2`. Its public IP on 2026-10-31 was `54.79.40.111`. The previous trusted SSH host key is referenced with `HostKeyAlias=54.252.237.68`. The current client `/32` SSH rule was added without removing older rules. The Qwen server binds to loopback.

Remote root: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1`.

Detached sessions:

- `choice-model-repeated8` (single Qwen CPU float32 server)
- `choice-faithfulness-8x50` (generation, four Luna annotation workers, analysis and report)

Remote output: `choice_study/choice_faithfulness_8x50_v1` relative to the root.

Logs: `choice_study/choice_faithfulness_8x50_v1/server.log` and `choice_study/choice_faithfulness_8x50_v1/runner.log`.

On a machine with the existing SSH identity:

```bash
ssh -i ~/Downloads/llm-experiment.pem -o HostKeyAlias=54.252.237.68 ubuntu@54.79.40.111
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
screen -ls
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/run_repeated8.py status
tail -n 40 choice_study/choice_faithfulness_8x50_v1/runner.log
tail -n 40 choice_study/choice_faithfulness_8x50_v1/server.log
```

If the runner has stopped, inspect states and journals first. To resume without duplicating completed jobs:

```bash
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/start_repeated8_server_existing_aws.py
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/launch_repeated8_existing_aws.py
```

The launcher refuses duplicate sessions/runners. A prior Qwen request with an uncertain outcome is reconciled from the server journal and never sent again automatically. Luna raw API bodies are saved before parsing; a request with an unknown outcome and no raw body is not resent automatically. Model-invalid answers remain draws in the `INVALID` outcome. Credentials remain in private EC2 configuration, outside the bundle and output files.

The initial `generator=` argument failed before model inference in Transformers 4.57.6. Its two failed journals and unused runtime fingerprint were archived under `operational_amendments/presampling_generator_kwarg_20261031/`. The corrected server applies each job seed inside `torch.random.fork_rng` and records actual sampling kwargs in every response. The first completed response verifies `do_sample=true` and `temperature=0.7`. A later edited Luna job metadata correction was made without changing the saved requests; four already saved raw API bodies validated against it. The migration is documented under `operational_amendments/annotation_patch_metadata_20261031/`. Two edited Luna requests interrupted during this repair are marked `execution_uncertain` without a saved body and are not automatically repeated. They are `row-1969/HISTORICAL_OFFER_REMOVAL/r23` and `row-710/PRODUCT_ORDER_CONTROL/r08`.

At 2026-10-31 10:28:58 UTC, 10/3,000 Qwen responses and 7 validated Luna annotations were complete. Eight uninterrupted adjacent Qwen completions averaged 47.9 seconds (median 43.6 seconds), giving about 40 hours for the remaining generation at that early rate. Six measured Luna requests averaged 85 seconds, implying about 18 hours of four-worker capacity for 3,000 requests; generation is the current bottleneck. This is a provisional ETA, subject to response length, rate limits and network conditions. The instance must remain on; no automatic EC2 stop is configured.

After collection, the supervisor writes `analysis.json`, `report.md`, tables, SVG plots and `manual_review_packet.json`. The annotation layer is automated Luna output, not human review. The report states coverage and any remaining uncertainty explicitly.
