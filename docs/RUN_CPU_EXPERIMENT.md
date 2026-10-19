# Continue the real CPU experiment from VS Code

You can run this workflow in an ordinary VS Code terminal after Codex credits run out. The commands use your existing AWS model server; they do not depend on an active Codex session or an OpenAI API key. AWS continues to charge for a running EC2 instance.

The current prompt is `common-evidence-v4-unlimited-citations`, using citation policy
`available-evidence-unlimited-v1`. Any number of available, distinct evidence IDs is
allowed; the explanation JSON schema is unchanged. JSON readability, required fields,
ID availability and duplicate citations are assessed separately.

Old pilot, v2 and v3 files are preserved. Their separate offline reassessment is in
`reports/citation_policy_v1`; see [citation policy notes](CITATION_POLICY.md).
The phase runner now defaults to fresh v4 output/control folders. Its compatibility
checks intentionally refuse appending new prompts or code to old runs. Do not use the
old v3 resume command after this protocol change. No new study was started by this update.

Use the pinned **Qwen3-1.7B model on CPU**, with float32 precision, 4,096 input tokens and 600 explanation tokens. This guide does not change your EC2 instance, model weights, installed packages, prepared data or research-server key.

## 1. Apply the small source update and keep your files

Download `cpu-experiment-update.zip` and unzip it in Downloads. Stop any old experiment writer before applying the update; leave the working AWS server and tunnel open. In your local VS Code terminal, run:

```bash
cd /Users/saiashwin/llm-trustworthiness
source .venv/bin/activate
python ~/Downloads/cpu-experiment-update/apply_update.py --project "$PWD" --check
python ~/Downloads/cpu-experiment-update/apply_update.py --project "$PWD"
```

The installer checks that your code matches the uploaded project, backs up replaced source files, and refuses to overwrite unknown edits. If it reports a conflict, keep the message and affected file; do not force an overwrite. Keep your existing `.env`, `.venv`, `data`, `data_v2`, and all old output and execution folders. Do not replace the whole working folder, recreate the environment, rerun `init_env.py`, or regenerate prepared data. The complete updated project ZIP is a reference snapshot; use the small update to continue your existing project.

The updated explanation prompt runs on your laptop. If the remote server code and scoring helper have not changed, your already-working server can stay running. Restart it only if it has stopped or the verifier reports different source hashes; the conditional restart instructions are below.

In VS Code, open your existing project folder. Open **Terminal → New Terminal** and run on your **Mac**:

```bash
cd /Users/saiashwin/llm-trustworthiness
source .venv/bin/activate
python --version
python scripts/run_cpu_real_v2.py --help
```

The script keeps its old filename for compatibility; its new default run is v3. The explicit paths in this guide make that distinction clear:

| Folder | Purpose |
|---|---|
| `outputs_cpu_real_v4` | New formal predictions, explanations, interventions, metrics and dashboard |
| `outputs_cpu_real_v4_smoke` | Separate small check of the revised prompt |
| `execution_cpu_real_v4` | New study plan, stage logs, checkpoint and execution history |
| Earlier pilot, smoke and v2 folders | Preserved historical attempts; do not append or pool them into v3 |

The prepared dataset already contains **306 validation cases** and **804 test cases**. Each is evaluated under two conditions, so a complete prediction phase contains **612 validation prediction records** or **1,608 test prediction records**. A case and a prediction record are different counts.

## 2. Check the model server and tunnel

Keep three terminals separate:

| Terminal | Runs where? | Purpose |
|---|---|---|
| Server | AWS, through SSH | Holds the model in memory |
| Tunnel | Your Mac | Connects local port 8000 to AWS |
| Experiment | Your Mac, local `.venv` active | Runs the study scripts |

If the server and tunnel are already working, leave them running and skip to verification below. Do not launch duplicate servers or tunnels.

If the tunnel needs reopening, select your existing CPU instance in the EC2 console and copy its **current Public IPv4 address**. An address from an earlier session may have changed after stop/start. In a **local tunnel terminal**, replace the placeholder and run:

```bash
export CPU_IP="PASTE_CURRENT_EC2_PUBLIC_IPV4_HERE"
ssh -i ~/Downloads/llm-experiment.pem \
  -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8000:127.0.0.1:8000 \
  ubuntu@"$CPU_IP"
```

Leave this terminal open. An idle-looking terminal is normal. If port 8000 is already occupied by your working tunnel, reuse that tunnel. The local API URL stays `http://127.0.0.1:8000`; do not replace it with the EC2 public IP.

In your **local experiment terminal**:

```bash
cd /Users/saiashwin/llm-trustworthiness
source .venv/bin/activate
MODEL_BASE_URL=http://127.0.0.1:8000 python scripts/verify_cpu_server.py
```

The expected line begins **`PASS: pinned Qwen3-1.7B / CPU float32`** and confirms limits, capabilities and source hashes. The verifier privately reads the existing `.env` key; it does not print or replace it. The four inference probes already passed, so there is no need to repeat them routinely. If a restart or deployment change needs another interface check, use:

```bash
MODEL_BASE_URL=http://127.0.0.1:8000 python scripts/verify_cpu_server.py --inference --timeout 600
```

These four synthetic API checks are interface checks, not research findings.

### Only if the remote server has stopped

In a separate **local terminal**, connect to the same current IP:

```bash
export CPU_IP="PASTE_CURRENT_EC2_PUBLIC_IPV4_HERE"
ssh -i ~/Downloads/llm-experiment.pem ubuntu@"$CPU_IP"
```

Now run on **AWS**:

```bash
cd ~/customer-choice-trust
source .venv/bin/activate
set +x
export MODEL_ID=Qwen/Qwen3-1.7B
export MODEL_REVISION=70d244cc86ccca08cf5af4e1e306ecf908b1ad5e
export MODEL_DEVICE=cpu
export ALLOW_CPU=1
export MAX_INPUT_TOKENS=4096
export MAX_EXPLANATION_TOKENS=600
if [ -z "${MODEL_API_KEY:-}" ]; then
    IFS= read -r -s -p "Paste your EXISTING MODEL_API_KEY (hidden): " MODEL_API_KEY
    printf '\n'
fi
export MODEL_API_KEY
python -c 'import os; assert len(os.environ.get("MODEL_API_KEY", "")) >= 24, "Existing API key is missing or too short"'
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1
```

Copy the existing API-key value privately from your local `.env` only if prompted. Do not paste it into chat or a command containing its literal value. Wait for application startup to complete, leave the server terminal open, and rerun the local verifier. Do not install packages, change token limits or start a second worker to address an explanation-format error.

## 3. Run the fresh smoke check first

Return to the **local experiment terminal**. Run:

```bash
caffeinate -i python -u scripts/run_cpu_real_v2.py smoke --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

`caffeinate -i` keeps your Mac from idle sleep while this command runs. Keep the Mac plugged in, its lid open, and the server/tunnel terminals running. The wrapper runs stages sequentially and saves stage logs. A pause between messages does not by itself mean the model has stopped.

This checks **two validation cases per condition**, with one random control and one presentation permutation. The smoke records go into `outputs_cpu_real_v4_smoke`, using `execution_cpu_real_v4/smoke_study_plan.json`. They stay separate from the formal run and its five-control/two-permutation protocol.

Inspect the smoke result before starting the larger study. Completion means the planned calls were accounted for; it does not certify usable explanations. Check JSON/field issues, unavailable or duplicate IDs, empty citation sets, and truncation counts and inspect the saved text. If either condition produces no usable explanations, pause here and inspect the prompt/output before spending hours on the larger run. Preserve raw records and start fresh folders if the prompt changes; do not delete failures, trim citations, or silently relax the parser.

Open the smoke dashboard:

```bash
open outputs_cpu_real_v4_smoke/dashboard.html
```

## 4. Run validation

After inspecting the smoke explanations and accepting the protocol:

```bash
caffeinate -i python -u scripts/run_cpu_real_v2.py validation --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

This runs all validation predictions, explanations for **20 validation cases per condition**, and the planned explanation tests for those cases. The fixed protocol uses both conditions, five matched random controls and two attempted presentation permutations. The script saves each completed prediction, explanation and intervention; many extra model calls make explanation testing slower than prediction alone on CPU.

When validation finishes, review:

- Saved explanation text and any parse, citation, abstention or truncation failures.
- The validation dashboard/report and completeness information.
- Whether evidence tests completed or were explicitly skipped.

Before freezing, decide whether this is the final prompt and protocol. Changing the prompt, model, code, limits, data or study settings requires a new run and a new validation phase. Do not edit raw JSONL records or the run manifest to bypass the compatibility check.

## 5. Freeze the protocol, then run test

After reviewing validation, run:

```bash
python scripts/run_cpu_real_v2.py freeze --ack-validation-review --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

The `--ack-validation-review` flag records that you have actually reviewed validation and are fixing the protocol. It is not another model-training step. The script checks the frozen plan and code before allowing the test phase. The formal plan is `execution_cpu_real_v4/study_plan.json`; do not edit it after freezing.

Then run:

```bash
caffeinate -i python -u scripts/run_cpu_real_v2.py test --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

The test phase includes:

| Work | Planned scope |
|---|---|
| Predictions | 804 test cases under each of two conditions |
| Explanations | 100 test cases per condition |
| Explanation tests | The same 100 cases per condition |
| Systematic counterfactual tests | 30 test cases, `with_history` condition |

The prior pilot test results were already inspected. Label this new study an **exploratory follow-up**, not a previously untouched confirmatory test. Keep historical, synthetic and v3 records separate.

## 6. Check progress and resume after interruption

To inspect saved progress without sending model requests, open another local terminal, activate `.venv`, and run:

```bash
python scripts/run_cpu_real_v2.py status --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

The script reports planned, completed and missing work. It also preserves failed attempts and skipped measurements. A completed process or a generated dashboard is not proof that every planned measurement succeeded; read the completeness counts.

To pause a running experiment, press **Ctrl+C** in its experiment terminal. Keep the saved files. To resume, restore the same server and tunnel and run the same phase command with the same `--out` and `--control` paths. Completed records are skipped; an unfinished individual model call may repeat. Run one experiment writer at a time.

If a writer-lock message appears after an interruption, first confirm the earlier experiment process has stopped. Do not remove the lock while another writer is running. If the error says code, plan or server settings differ, preserve the current run and use a fresh run; do not force append.

Stage logs and the event history are in `execution_cpu_real_v4`. Open the latest named log in VS Code if a stage fails or appears inactive. Check the AWS server terminal too. Connection errors usually require restoring the tunnel/server; authentication errors require the same existing key on both sides.

## 7. Build and read the report

Run locally:

```bash
python scripts/run_cpu_real_v2.py report --out outputs_cpu_real_v4 --control execution_cpu_real_v4
open outputs_cpu_real_v4/dashboard.html
```

The dashboard opens in your Mac's browser. You can also double-click that HTML file in Finder. No dashboard hosting is needed. Read `outputs_cpu_real_v4/report.md`, `metrics.json`, `execution_summary.json` and `completeness.md` alongside it. Report/status commands use saved outputs; they do not rerun the LLM.

Keep prediction accuracy, confidence calibration, explanation sensitivity, presentation robustness, and factual grounding separate. Modified scenarios have no observed customer-choice labels. Their effects describe the model's behaviour, not proof of the customer's actual motives or response to a changed price.

## 8. Complete the manual factual review

The report creates `outputs_cpu_real_v4/manual_review_sample.csv` with **20 preselected test cases per condition**, or **40 explanations in total**. Open this file in a CSV editor or spreadsheet application. This fixed sample prevents choosing only attractive explanations. For each explanation you actually review, fill:

- `supported_claims`: number of checkable factual claims supported by the supplied evidence.
- `total_factual_claims`: number of checkable factual claims you assessed.
- `reviewer_notes`: your rubric, uncertainty or disagreement.

Use the included evidence, not outside assumptions about a household. For example, a comparison of two prices needs both prices; health consciousness is unsupported when no evidence of it was supplied. A valid evidence ID does not by itself make the attached statement true. Leave unreviewed counts blank, not zero; enter zero only when you actually reviewed the row and that count is zero. Prefer a second reviewer for a subset.

Save `manual_review_sample.csv` and rerun the **report** command from step 7. The script validates the filled counts and merges them into `manual_audit.csv`, which is the main audit used for analysis. Preserve the identifying columns and do not transfer reviews to different explanation text. The report distinguishes **automatic stages complete** from **manual review complete**. Factual grounding applies to the reviewed sample, with its denominator reported; it does not establish that every generated explanation is grounded.

## 9. End the session

Check that the local outputs are saved. Stop the experiment if still running, press **Ctrl+C** in the AWS server terminal, and close the tunnel with **Ctrl+C**. If you are finished using the instance, choose **Stop instance** for your existing CPU instance in the EC2 console.

Closing VS Code or SSH does not stop EC2 billing. Stopping the instance ends instance compute usage charges; retained EBS storage still costs money. Stop rather than terminate while you still need its files. On a later start, use the instance's new current public IP and restart the pinned CPU server and tunnel before resuming the same compatible phase.
