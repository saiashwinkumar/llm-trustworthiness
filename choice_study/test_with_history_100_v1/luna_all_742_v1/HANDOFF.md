# Luna test100 overnight handoff

**Running on EC2; newly saved annotation files verified.** Snapshot: 2026-10-25T16:53:29.271775+00:00.

- Instance: `i-0fca8c4016c36b737`, `m7i.xlarge`, `ubuntu@54.252.237.68`.
- Session: `choice-luna-annotations-100`; Python runner PID `83043`; four concurrent requests.
- Root: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1`.
- Output: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1/choice_study/test_with_history_100_v1/luna_all_742_v1`.
- Log: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1/choice_study/test_with_history_100_v1/luna_all_742_v1/runner.log`.
- Frozen annotation manifest: `9251cf0e682aeee0852e3ce26dc07e262d921e47507a52cc6471d022ef6a0e6c`.
- Inventory: 100 originals +642 edits =742 saved predictor responses, only the existing selected test/with_history queries.
- Matching pilot annotations reused: 10; newly saved: 4; total saved: 14/742.
- Structural/traceability passes: 13/742. States: `{"completed": 13, "running": 4, "pending": 724, "completed_with_validation_errors": 1}`.
- Original first-four live check passed. Their raw API bodies, source linkage and parsed outputs were verified; processing continued automatically. No duplicate diagnostic calls.
- Early observed throughput: 121.1 new annotations/hour; remaining ETA: 6.0 hours, around 26 Oct 2026 04:24 IST. This small-sample estimate will change, especially during edited explanations.

All remaining originals run before the edited phase. All outputs are automated Luna annotations, not human-reviewed. The reused row-2227 exact-quote failure stays preserved. Three already-truncated edited predictor outputs are annotated only over literal saved prefixes; they remain separate from full-explanation successful coverage. Saved/accounted work is not the same as successful annotation coverage.

The existing model-server PID78300 remains alive. No predictions or edited predictor responses were regenerated. Existing experiment sources, raw pilot annotations and historical metrics remain unchanged. The instance stays running after annotation finishes.

The initial screen-launch attempt closed before making any API request. A launcher-only PTY/TERM fix, its prior source and hashes are preserved remotely under `deployment_amendments/`; frozen annotation content/settings were unchanged.

## Monitor on EC2

```bash
ssh -i ~/Downloads/llm-experiment.pem ubuntu@54.252.237.68
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
LUNA_PY=/home/ubuntu/customer-choice-trust/.venv/bin/python
LUNA_OUT=choice_study/test_with_history_100_v1/luna_all_742_v1
screen -ls
tail -n 30 "$LUNA_OUT/runner.log"
"$LUNA_PY" -B scripts/run_luna100.py status
```

## Resume after interruption

The launcher refuses another live runner/session. Matching completed results are reused; uncertain requests are not automatically resent.

```bash
"$LUNA_PY" -B scripts/launch_luna100_existing_aws.py
```

## Generate a read-only summary

```bash
"$LUNA_PY" -B scripts/run_luna100.py summary
cat "$LUNA_OUT/completion_summary.md"
```

The summary contains original/edited coverage by family, reused/new counts, failed/uncertain/invalid outcomes, validation findings, input/cache/output/reasoning-token usage, throughput and ETA. It makes no semantic-validation or human-review claim. See `docs/LUNA_TEST100_OVERNIGHT.md` for protocol, retries, source-prefix limitations, credentials and metrics-adapter details. The authoritative writer is EC2; the local frozen preparation remains a preparation snapshot and `remote_execution_snapshot.json` records this verified remote snapshot.
