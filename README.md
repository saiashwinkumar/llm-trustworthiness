# LLM customer-choice and explanation study

Can an LLM predict customer product choices, and do its explanations identify evidence that actually influences those predictions?

## Start here

- [Research presentation](presentation/index.html): download and open locally in a browser.
- [Offline presentation bundle](presentation/choice-study-presentation.zip): unzip to retain all linked supporting records.
- [Presentation instructions](presentation/README.md) and [verified findings](presentation/support/snapshot-0525cb3a9a0d665a/presentation_findings.json).
- [Experiment framework](docs/FRAMEWORK.md), [citation policy](docs/CITATION_POLICY.md), and [resumable study plan](execution_resumed_v1/EXECUTION_PLAN.md).

The presentation snapshot contains 3,828 original predictions, 242 explanation responses, and 3,736 measured interventions. Another 240 intervention records are skipped tests and do not contribute to measured findings. Test accuracy is 310/804 (38.6%) without support and 405/804 (50.4%) with history. Explanation-based test analyses use 100 selected purchases per condition. Systematic price, advertising, and history-removal analyses use 30 selected purchases with history.

For price edits, each of the 30 purchases has four products and two separate price changes per product (−20% and +20%): 30 × 4 × 2 = 240 edited-input predictions. Twenty changed the predicted product; these changes occurred across ten purchases. These are model behavior measurements, not observed customer responses to edited scenarios.

## Rebuild the presentation offline

```bash
python3 -B scripts/build_presentation_report.py
```

This uses the checked-in snapshot, checks source records, and regenerates the same HTML and ZIP without inference or cloud access. Python 3.10+ is recommended. The presentation builder uses Python's standard library. Optional historical analysis and server dependencies are listed separately in the requirements files.

For an authorized read-only refresh from the original EC2 setup, use `python3 -B scripts/build_presentation_report.py --refresh-aws`. That command requires the owner's existing SSH access; no credentials are included in this repository. Cloud commands in the historical instructions are environment-specific and are not run automatically.

## Saved research records

The authoritative snapshot behind the current presentation is `presentation/support/snapshot-0525cb3a9a0d665a/`. Other output and execution folders preserve earlier local experiment records and plans; they can reflect earlier stages. Do not add their counts to the presentation snapshot or interpret historical planning files as current execution status. Original prompts, raw explanation text, prior assessments, and versioned citation reassessments remain available. No human review is implied by the presence of audit templates.

This repository contains source code, prepared data, historical outputs, and the latest verified AWS result snapshot. Credentials, virtual environments, caches, temporary previews, duplicate backup archives, and older duplicated presentation snapshots are excluded. The export manifest records original file hashes. No software or dataset license is inferred by this export.

---

## Earlier project documentation

The documentation below is preserved for research provenance; some deployment and progress descriptions predate the completed presentation snapshot.

# Customer choice and explanation evidence

> Citation-policy update: future explanations use `common-evidence-v4-unlimited-citations`
> with any number of available, distinct evidence IDs and the unchanged JSON schema.
> Existing responses were reassessed offline under `available-evidence-unlimited-v1` in
> [the separate report](reports/citation_policy_v1/report.md). Old responses, prompts,
> assessments and measurements remain unchanged. New phase-runner defaults are v4;
> old v3 resume commands are incompatible after this prompt/code change. See
> [policy details and commands](docs/CITATION_POLICY.md).

Can a model predict an observed choice, and does its explanation identify evidence that affects that prediction—even when it is wrong?

This upgrade adds a reusable, versioned experiment framework and a standalone interactive HTML dashboard. It runs locally with Python's standard library; inference stays on your existing CPU model server. No GPU, hosted dashboard, OpenAI API key, or new AWS resource is required.

**Start with the existing real results:** open [the CPU pilot dashboard](reports/cpu_pilot_v2/dashboard.html) in Chrome, Safari, or another browser. It contains 40 saved predictions and 20 explanation attempts, imported without modifying their source files. The findings are exploratory; no calibration or manual grounding results are inferred when absent. A new synthetic product dashboard is at [outputs_v2/demo_products/dashboard.html](outputs_v2/demo_products/dashboard.html), and a text-classification demonstration is at [outputs_v2/demo_text/dashboard.html](outputs_v2/demo_text/dashboard.html).

## Verified deployment and preservation

The saved `outputs_cpu_pilot/run_manifest.json` and `outputs_cpu_smoke/run_manifest.json` identify:

- Model: `Qwen/Qwen3-1.7B`
- Resolved revision: `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`
- Device/precision: `cpu`, `torch.float32`
- Server Python: 3.12.3; Transformers: 4.57.6; Torch: 2.14.1+cpu as recorded by the server
- Limits: 4096 input tokens, 600 explanation tokens, thinking disabled

These are the updated server defaults. **The EC2 instance type cannot be verified from these files.** The expected m7i.xlarge comes from your deployment description. The configured endpoint refused the health-check connection during this upgrade, so no new live inference or AWS changes were performed. See [CPU server instructions](AWS_SETUP.md). A subsequent read-only SSH inspection identified the existing remote `.venv` and a missing server helper package; use the [exact upload/start/verification commands](docs/AWS_CPU_DEPLOY.md) for `54.252.237.68`.

The original `.env`, virtual environment, raw/prepared data, split assignments, `experiment.py`, `analyze.py`, and all pre-existing result folders are preserved. The older scripts retain their four-brand interfaces. Historical results use a read-only compatibility import into a new directory. Do not append v2 experiments to historical run folders, or combine the pilot and smoke runs merely to obtain calibration data. The old instructions are archived in [docs/LEGACY_WORKFLOW.md](docs/LEGACY_WORKFLOW.md); its GPU recommendation is superseded.

## VS Code terminal: use the environment

From this folder in **Terminal → New Terminal**:

```bash
source .venv/bin/activate
python --version
python -m unittest discover -s tests -v
```

The local `.venv` was created with Python 3.13.6. The new `choice_trust` commands and tests require no third-party client packages. For the unchanged historical analysis/plots only:

```bash
python -m pip install -r requirements-client.txt
```

Server dependencies belong on EC2, not in the laptop environment. Nothing automatically starts or downloads a model locally.

## Finish a bounded CPU experiment with the new framework

The prepared yogurt data already exist. Convert them once, keeping their cases, support observations, and split assignments:

```bash
python -m choice_trust prepare --adapter yogurt --source data/processed/cases.jsonl --out data_v2/yogurt
```

This command refuses an existing destination. If you need to prepare the original data on a fresh checkout, run `python prepare_data.py` first, or `python prepare_data.py --source-csv Yogurt.csv` for an offline CSV. Do not rebuild existing prepared data to run an experiment.

Restore your existing server and SSH tunnel, then check it:

```bash
python experiment.py health
python -m choice_trust health
```

The new client can use the old four-label endpoint for four-candidate cases. Variable candidate counts require the updated `/score_candidates` server. Updating the server changes provenance: use a new output folder after a restart with changed code/settings.

Start a small **new** run (both conditions, two validation cases):

```bash
python -m choice_trust predict --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_smoke --split validation --limit 2 --conditions no_history with_history
python -m choice_trust explain --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_smoke --split validation --limit 2 --conditions no_history with_history
python -m choice_trust counterfactuals --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_smoke --split validation --limit 2 --conditions no_history with_history
python -m choice_trust analyze --out outputs_v2/cpu_smoke
python -m choice_trust dashboard --out outputs_v2/cpu_smoke
```

Open `outputs_v2/cpu_smoke/dashboard.html`. Systematic sweeps, controls and explanations can take much longer than original predictions on CPU. A yogurt case with five history observations can require up to about 28 fresh scoring calls with default controls, in addition to prediction and explanation. Calls are sequential and saved individually. Start with `--limit 1` if desired. `--random-controls`, `--permutations`, seed, and conditions must match across stages in a run; defaults are five controls, two attempted permutations, seed 42.

When ready to execute the planned study, use a separate folder and fixed protocol. The following is an **explicit user-run example**, not something launched automatically:

```bash
python -m choice_trust predict --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split validation --conditions no_history with_history
python -m choice_trust explain --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split validation --limit 20 --conditions no_history with_history
python -m choice_trust counterfactuals --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split validation --limit 20 --conditions no_history with_history
# Freeze the protocol before inspecting final test results.
python -m choice_trust predict --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split test --conditions no_history with_history
python -m choice_trust explain --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split test --limit 100 --conditions no_history with_history
python -m choice_trust counterfactuals --cases data_v2/yogurt/cases.jsonl --out outputs_v2/cpu_study --split test --limit 100 --conditions no_history with_history
python -m choice_trust analyze --out outputs_v2/cpu_study
python -m choice_trust dashboard --out outputs_v2/cpu_study
```

Changing prompts or protocol after validation requires a new run folder and rerunning the relevant predictions. Baselines and numeric edit bounds use development data; temperature calibration uses only validation predictions. Test results never fit those settings.

To continue an **unchanged legacy protocol**, `python experiment.py predict --out outputs_cpu_pilot --split test` and the other existing commands remain available. They check their original hashes and refuse incompatible appends. The v2 workflow changes the prompt and is a separate experiment, not a continuation of the same statistical sample.

## Free synthetic examples: products and text

The checked-in examples are conspicuously synthetic. They demonstrate the shared pipeline, not model quality. Run each preparation command once; choose a fresh output folder after code/protocol changes.

```bash
python -m choice_trust prepare --source examples/products.jsonl --config examples/products.config.json --out data_v2/products_example
# examples/products.csv works with the same config (long format, one candidate per row).
python -m choice_trust predict --mock --cases data_v2/products_example/cases.jsonl --out outputs_v2/products_example --split all
python -m choice_trust explain --mock --cases data_v2/products_example/cases.jsonl --out outputs_v2/products_example --split all
python -m choice_trust counterfactuals --mock --cases data_v2/products_example/cases.jsonl --out outputs_v2/products_example --split test
python -m choice_trust dashboard --out outputs_v2/products_example

python -m choice_trust prepare --source examples/text.jsonl --config examples/text.config.json --out data_v2/text_example
python -m choice_trust predict --mock --cases data_v2/text_example/cases.jsonl --out outputs_v2/text_example --split all
python -m choice_trust explain --mock --cases data_v2/text_example/cases.jsonl --out outputs_v2/text_example --split all
python -m choice_trust counterfactuals --mock --cases data_v2/text_example/cases.jsonl --out outputs_v2/text_example --split test
python -m choice_trust dashboard --out outputs_v2/text_example
```

Products have 2, 5, and 7 available candidates. Text classification uses the same prediction/explanation/removal/retention/permutation/evaluation code, with sentiment labels as candidates. No price or ad field is required. The mock backend refuses real data. A real backend may evaluate labelled synthetic fixtures, but reports still mark them synthetic.

## Historical HTML report, without new model calls

The supplied conversion has already been generated at `reports/cpu_pilot_v2`. To generate another copy in a fresh directory:

```bash
python -m choice_trust import-legacy --source outputs_cpu_pilot --cases data/processed/cases.jsonl --out reports/cpu_pilot_copy
python -m choice_trust dashboard --out reports/cpu_pilot_copy
```

Unrecorded historical edited scores display “not recorded,” even where a scalar effect was retained. Do not reconstruct score vectors or simulate new responses from those scalar effects. Imports verify available source hashes and joins; they explicitly warn that historical execution and unrecorded calls cannot be independently verified.

## Manual factual-grounding review

Edit `RUN/manual_audit.csv`. Fill `supported_claims` and `total_factual_claims` only for reviewed explanations. Count individual checkable claims against the input evidence; a valid ID is not proof that the associated prose is true. Leave unreviewed cells blank, specify a rubric in reviewer notes, and preferably use a second reviewer on a subset. Do not select only convincing explanations. Reviews bind to an explanation content hash; stale reviews are not silently transferred.

Re-run `python -m choice_trust dashboard --out RUN` after review. Factual grounding, prediction accuracy, behavioral faithfulness and robustness remain separate dimensions. Edited scenarios have no observed customer outcome and cannot establish actual customer motives.

## Add another dataset

Copy [examples/products.config.json](examples/products.config.json), review the pre-decision evidence allowlist, set `synthetic` appropriately, specify task semantics, and map your CSV/JSONL fields. Run `prepare`, inspect `cases.jsonl` and `manifest.json`, then use the same stage commands with a fresh run directory. See [the schema, architecture and methods guide](docs/FRAMEWORK.md) for exact formats, history, constraints, scoring, resumption, and supported limitations.

[Validation record](VALIDATION.md) includes the automated and browser checks and the unavailable live endpoint check.
# Continue the interrupted real CPU study

Use **[docs/RUN_CPU_EXPERIMENT.md](docs/RUN_CPU_EXPERIMENT.md)** for the current manual workflow. The phase runner is still named `scripts/run_cpu_real_v2.py`, but now defaults to fresh **v4** folders because the explanation prompt changed. Keep existing pilot, smoke, and v2 records intact. The update applies locally; `server.py` and `choice_trust/scoring.py` are unchanged, so a verified running CPU server can stay running.

After applying the targeted update, activate the existing environment and verify the endpoint:

```bash
source .venv/bin/activate
python scripts/verify_cpu_server.py
caffeinate -i python -u scripts/run_cpu_real_v2.py smoke
```

Inspect the smoke explanations. Then run `validation`, inspect its saved failures and coverage, run `freeze --ack-validation-review`, and run `test`. Use `status` to inspect progress without model calls and `report` to rebuild the HTML. On Linux, omit `caffeinate -i`. Every phase can be resumed by repeating its unchanged command; completed records are reused. Do not run two experiment writers at once or edit protocol code after a run starts.

The formal plan has 612 validation prediction records, 1,608 test prediction records, 100 test explanations and explanation-test cases per condition, and systematic counterfactuals on 30 with-history test cases. The wrapper records the exact selected IDs and checks saved coverage. Invalid responses and explicit skips are reported as recorded outcomes, not successful explanations. Citation-format failure alone does not establish unfaithfulness.

The report distinguishes automatic execution from a planned manual review of 20 test explanations per condition. Fill `outputs_cpu_real_v4/manual_review_sample.csv`, then rerun `report` to validate and merge those reviews. Until then, full-study completion remains false. The dashboard shows this completion state and refuses to display a stale completion snapshot as current.

