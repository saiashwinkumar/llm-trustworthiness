# LLM customer-choice and explanation study

This repository contains the current research code, saved study records, and a self-contained presentation of the actual experiment.

## Start here

- [Actual experiment presentation](presentation/index.html): download and open locally in a browser.
- [Offline presentation bundle](presentation/actual-experiment-presentation.zip): the HTML and its matching source packets.
- [Presentation guide](presentation/README.md) and [metric definitions](docs/EXPERIMENT_PRESENTATION.md).
- [Eight-case repeated-sampling study handoff](choice_study/choice_faithfulness_8x50_v1/HANDOFF.md). Its status is separate from the saved presentation.

The presentation was built from saved records on 26 October 2026. The later repeated-sampling study is preserved at its local snapshot; consult its handoff and reports for status and denominators. Credentials, virtual environments, caches, local logs, and duplicate presentation snapshots are excluded. The export manifest records file hashes and whether each exported file matches the local project source. The notebook has outputs cleared while preserving its current cells.

---

## Project documentation

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

## Factual observation preview

`choice_trust/observations.py` builds target-free, deterministic observations from the existing prepared yogurt cases. Preview one real case in both conditions with:

```bash
python3 scripts/preview_observations.py --case-id row-2
python3 scripts/preview_observations.py --case-id row-2 --json
python3 -m unittest tests.test_observations -v
```

The adapter maps `brand_map` to candidate IDs and names, `query.prices` to `current.prices`, `query.ads` to `current.advertised`, and each selected `support` entry's `evidence_id`, `prices`, `ads`, and `choice` to its support ID, prices, advertised flags, and purchased candidate. It never reads `target`. The existing `P_A`/`F_A` pattern and `H1` support IDs are retained; derived IDs are prefixed `OBS:` or use an H-ID suffix. Field references in the generated JSON refer to these mapped input fields, such as `current.prices.A` and `H1.purchased`.

The compact v2 input exposes three source-field groups: `CURRENT_PRICES`, `CURRENT_ADVERTISING`, and `HOUSEHOLD_HISTORY`. Each price, flag, and linked support record appears once. Prices are assumed dollar amounts for this experimental version, with no scaling, and are rounded to two decimals using `Decimal(str(value))` and `ROUND_HALF_UP`. Raw source values and detailed summaries remain in the internal audit payload; comparisons of displayed prices use the same rounded cents. This grouping makes no claim of statistical independence. See [the compact input contract](docs/COMPACT_OBSERVATIONS.md) and [both real-case prompts](examples/compact_observation_preview.txt).

Preview the complete prompts without inference using `python3 scripts/preview_observations.py --case-id row-2 --prompt`. Add `--assignments` to inspect field-to-group provenance outside the prompt. Existing saved notebook and experiment outputs retain their original prompts and versions.

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

