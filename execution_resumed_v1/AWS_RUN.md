# EC2 execution and resumption

The authoritative running copy is on EC2:

`/home/ubuntu/customer-choice-trust/continuations/resumed_v1`

The Mac outputs remain the pre-launch snapshot. Do not launch a Mac experiment writer
while this EC2 queue is active. The remote queue connects directly to
`http://127.0.0.1:8000` on EC2 and reuses the existing model server credential privately
from its process environment. It needs neither the Mac nor an SSH tunnel.

The existing model server stays in `choice-model-night`; the experiment queue runs in
`choice-study-resumed-v1`. No model server, environment, dependency or checkpoint was
replaced. All 56 transferred files were hash-verified before launch. The original
server project files and original experiment results remain untouched.

The sequential order is recovery → development → validation → automatic accounting
review/freeze → test → report. User authorization to execute the prepared fixed
protocol is recorded in `automated_validation_review.json` when validation finishes.
This is explicitly an automated check, not a claim that a human reviewed future
responses. Poor explanations and unchanged/wrong answers do not prevent progress
when their attempts are recorded. Manual grounding review remains separate.

## Check progress

From the Mac:

```bash
ssh -i ~/Downloads/llm-experiment.pem ubuntu@54.252.237.68
```

Then on EC2:

```bash
cd /home/ubuntu/customer-choice-trust/continuations/resumed_v1
screen -ls
cat execution_resumed_v1/queue_state.json
/home/ubuntu/customer-choice-trust/.venv/bin/python -B scripts/run_resumed_study.py status
tail -n 40 execution_resumed_v1/queue.log
```

To follow the current phase log (read its filename from `queue_state.json`):

```bash
/home/ubuntu/customer-choice-trust/.venv/bin/python -c 'import json; from pathlib import Path; s=json.loads(Path("execution_resumed_v1/queue_state.json").read_text()); print(s.get("current_log", "No active log"))'
tail -f execution_resumed_v1/queue_PHASE_TIMESTAMP.log
```

Or attach to the queue's screen:

```bash
screen -r choice-study-resumed-v1
```

Its output is redirected to files. Detach with **Ctrl+A, then D**. Closing an SSH
connection or the laptop does not stop the detached EC2 processes.

## Logs and completion records

- `execution_resumed_v1/queue.log`: queue start/complete/error messages.
- `execution_resumed_v1/queue_events.jsonl`: phase attempts and outcomes.
- `execution_resumed_v1/queue_state.json`: current queue PID, child PID, phase and log.
- `execution_resumed_v1/queue_*_TIMESTAMP.log`: complete per-phase output.
- `execution_resumed_v1/queue_*_completion.json`: per-phase exit code, measured elapsed
  seconds, and saved coverage snapshot.
- `execution_resumed_v1/stage_events.jsonl` and stage-specific logs: prediction,
  explanation and counterfactual substage attempts.
- `outputs_resumed_v1/execution_summary.json`, `completeness.md`, `report.md`,
  `metrics.json`, `dashboard.html`: reports refreshed at phase completion.
- `outputs_resumed_v1/predictions.jsonl`, `explanations.jsonl`, `interventions.jsonl`:
  append-only saved responses/measurements, flushed after each completed call.

Use `status` for live counts; completion snapshots describe the time they were written.
Errors stop the queue rather than silently advancing. Every successful phase gets a
completion snapshot, and existing completed phases are detected on restart.

## Resume after interruption

First check `screen -ls`, `queue_state.json`, and the logs. If the existing queue is
still running, leave it running. If it stopped, use this command on EC2:

```bash
cd /home/ubuntu/customer-choice-trust/continuations/resumed_v1
screen -dmS choice-study-resumed-v1 bash -c 'exec /home/ubuntu/customer-choice-trust/.venv/bin/python -B -u scripts/aws_queue.py >> execution_resumed_v1/queue.log 2>&1'
```

The queue has an exclusive lock and refuses competing experiment processes. Completed
records are reused by ID. A call interrupted before saving may repeat. A writer PID
lock is removed automatically only when that PID is dead and no competing runner is
found. Code/data/source integrity and server metadata are checked again on resume.

If the EC2 instance or model server was stopped, restore the same existing pinned
server and credential first; the queue deliberately does not start another model
server or replace credentials. A changed EC2 public IP affects SSH access, not the
runner's loopback connection. Screen protects against laptop/SSH disconnection, not
instance shutdown or host reboot.

No end-to-end runtime estimate was asserted at launch. Phase completion records
contain measured durations; heterogeneous explanation and intervention calls should
not be extrapolated from a single short scoring call.
