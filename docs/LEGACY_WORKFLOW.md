# Implement a customer choice and explanation trust experiment

This project predicts which of four yogurt brands a household purchased, then checks whether the LLM's explanation identifies evidence that affects its prediction. Your laptop runs the experiment and analysis in VS Code. An AWS GPU runs Qwen3-8B. You do not need a local GPU, an OpenAI account, or an OpenAI API key.

Start with the local synthetic check. Launch AWS only after that works. The supplied code is a starter research implementation, with a complete synthetic workflow check; actual Qwen GPU inference and the real CSV download were not executable in the preparation environment. No real LLM findings are included.

## 1 What you are building

| Component | Location | Purpose |
|---|---|---|
| `prepare_data.py` | Laptop | Download, validate and split the purchase data |
| `experiment.py` | Laptop | Send prediction/explanation requests and test cited evidence |
| `analyze.py` | Laptop | Compare baselines, calibrate scores, create metrics and figures |
| `server.py` | AWS | Run the model and expose its prediction scores |
| `AWS_SETUP.md` | Guide | Create the GPU server and connect it to your laptop |
| `make_demo_data.py` | Laptop | Generate artificial data for a free workflow check |
| `tests/test_workflow.py` | Laptop | Check leakage prevention, splits and intervention logic |

An LLM is a model that reads and produces text. In this project, we also inspect its numerical scores for four answer labels. A prompt is the input text sent to the model. Inference means using an existing model; fine-tuning means changing its learned parameters. This first experiment uses inference only.

## 2 Install the local tools

Install [Python 3.12](https://www.python.org/downloads/), [VS Code](https://code.visualstudio.com/), and Microsoft's **Python** extension inside VS Code. On Windows, enable the Python installer's PATH option if offered; the `py` launcher is used below.

Extract this ZIP. In VS Code choose **File → Open Folder**, and open the inner `customer-choice-trust` folder containing this README and the Python files. Use **Terminal → New Terminal**. All local commands below run from that folder.

Create an isolated Python environment. An environment is simply a project-specific place for installed packages.

On macOS or Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

On Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

If Windows blocks activation, use `.\.venv\Scripts\python.exe` instead of `python` in subsequent commands. You do not need to change the computer's execution policy. On macOS/Linux, use `.venv/bin/python` if activation is inconvenient.

Open the VS Code Command Palette (**Cmd+Shift+P** on macOS, **Ctrl+Shift+P** elsewhere), choose **Python: Select Interpreter**, and select `.venv`. Confirm `python --version` reports your installed 3.12 version. If you installed 3.11 instead, substitute that version when creating the environment.

Install only the laptop dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-client.txt
python -m pip check
python -m pip freeze > local-environment-lock.txt
python -m unittest discover -s tests -v
```

Expected checkpoint: all eight research-integrity tests pass. Do not install `requirements-server.txt` on your laptop; that file is for AWS.

## 3 Run the free synthetic workflow check

Run these commands locally:

```bash
python make_demo_data.py
python experiment.py predict --mock --cases data_demo/cases.jsonl --split all
python experiment.py faithfulness --mock --cases data_demo/cases.jsonl --split test --limit 20
python analyze.py --predictions outputs_demo/predictions.jsonl --cases data_demo/cases.jsonl --faithfulness outputs_demo/faithfulness.jsonl --output-dir outputs_demo
```

Open `outputs_demo/report.md` in VS Code and choose **Open Preview** (usually Ctrl+Shift+V or Cmd+Shift+V). Also inspect the PNG files under `outputs_demo/figures`.

This uses an artificial rule and artificial data. It checks the software plumbing, not Qwen's abilities. Never use these outputs as research results. The real and mock workflows use separate folders, and mock inference refuses the real data.

## 4 Prepare the real purchase data

The [public yogurt dataset documentation](https://jhelvy.github.io/logitr/reference/yogurt.html) describes 2,412 purchase occasions from 100 households, involving Dannon, Hiland, Weight Watchers and Yoplait. The code downloads the equivalent wide-format [Ecdat CSV mirror](https://vincentarelbundock.github.io/Rdatasets/csv/Ecdat/Yogurt.csv). See its [column documentation](https://vincentarelbundock.github.io/Rdatasets/doc/Ecdat/Yogurt.html).

Run:

```bash
python prepare_data.py
```

The script prints the observed row and household counts and the actual split sizes. Check that the source has the documented 2,412 occasions and 100 households; investigate discrepancies before proceeding. It writes:

| File | Contents |
|---|---|
| `data/raw/Yogurt.<hash>.csv` | Unmodified downloaded snapshot |
| `data/processed/cases.jsonl` | Prepared research cases, one JSON object per line |
| `data/processed/manifest.json` | Source hash, household allocation, support/query allocation and seed |

If the download fails, open the CSV link in a browser, save it as `Yogurt.csv` in the project folder, then run:

```bash
python prepare_data.py --source-csv Yogurt.csv
```

Do not save the HTML documentation page as the CSV. The parser rejects wrong schemas and invalid values. An R alternative is `data("Yogurt", package="Ecdat")`, followed by `write.csv(Yogurt, "Yogurt.csv", row.names=FALSE)` after installing Ecdat.

Preparation uses seed 42 to divide eligible households approximately 60/20/20 into development, validation and test. Within each household, five complete occasions become observed examples, called **support**; the remaining occasions are queries. Households with no remaining query are excluded and listed. All four alternatives stay together.

Important scope: there are no documented dates in these files. We predict held-out choices given other observed choices, not verified future purchases. The task is conditional on a purchase among these four brands; it does not model buying nothing or choosing another brand. Prices stay in their original numeric units. No nutrition, taste, budget, demographic or income attributes are supplied.

The query's actual choice is stored as `target` for evaluation. The prompt builder never uses that field. Support choices are allowed input evidence because they belong to different occasions.

The prepared files are not overwritten by default. Use `--overwrite` only when you deliberately want to rebuild them; a new data hash will require a new experiment output folder.

## 5 Generate your research server key

Run locally:

```bash
python init_env.py
```

Open the resulting `.env` file in VS Code. It contains the local server URL and a newly generated `MODEL_API_KEY`. Keep it private. This is a key for your own server, not an AWS credential. The `.gitignore` excludes it, along with private SSH keys and result folders.

## 6 Set up AWS and connect the GPU

Follow **[AWS_SETUP.md](AWS_SETUP.md)** from sections 1 through 7. It gives the console selections and all SSH commands for macOS, Linux and Windows.

The recommended first machine is a **g6.2xlarge** with one 24 GB NVIDIA L4 GPU and 32 GiB CPU memory; **g5.2xlarge** is an alternative. Use an Amazon-published, maintained Ubuntu GPU PyTorch Deep Learning AMI, 100 GiB EBS, SSH port 22 restricted to your IP, and a private SSH tunnel for model requests. Check your region's displayed price and G/VT quota before launch.

For this small study, direct EC2 provides the access needed for numerical label scores. More expensive GPUs or more CPU cores do not by themselves improve prediction accuracy. This is a simple single-request research server, not a benchmark for maximum serving throughput.

Keep three terminals conceptually separate:

| Terminal | Where commands run | What it does |
|---|---|---|
| AWS server terminal | Remote EC2 instance | Holds the loaded model |
| Tunnel terminal | Your laptop | Keeps the encrypted connection open |
| Experiment terminal | Your laptop, `.venv` active | Runs this project's scripts |

After the server and tunnel are ready, run locally:

```bash
python experiment.py health
```

Expected checkpoint: model ID is `Qwen/Qwen3-8B`, a resolved commit hash is shown, and the server reports a CUDA device. Save the commit hash and the remote `server-environment-lock.txt`. Use that exact `MODEL_REVISION` on later restarts.

## 7 Understand what each model request does

The experiment compares **no_history** (current prices and ads only) with **with_history** (the same current offers plus five support examples). The word history is a convenient condition name; the examples are not claimed to precede the query in time.

Each current price has an ID such as `P_A`; each current ad status has an ID such as `F_A`. The five complete support examples have IDs `H1` to `H5`. The four labels identify brands: A=Dannon, B=Hiland, C=Weight Watchers, D=Yoplait.

The server first computes next-token scores for the four permitted letters, normalized to sum to one. These are **label-conditional model scores**, not automatically trustworthy probabilities of customer behavior. It also saves the raw probability mass assigned to these letters before renormalization as a diagnostic.

In a separate call, the model explains its original prediction versus its strongest alternative, cites up to three evidence IDs, and may state a testable counterfactual. It may give no evidence IDs when it cannot defend an explanation. Invalid/truncated responses and abstentions remain recorded; they are not silently replaced with convincing text.

The explanation is post-hoc: it is generated after the prediction. The study tests how well that explanation matches observed input sensitivity. It does not treat the text as a transcript of hidden internal reasoning.

## 8 Run a tiny real-model smoke check

Use its own output folder so the quick check does not become part of the formal study:

```bash
python experiment.py predict --split validation --limit 5 --out outputs_smoke
python experiment.py faithfulness --split validation --limit 2 --conditions with_history --random-controls 1 --out outputs_smoke
```

Open `outputs_smoke/predictions.jsonl` and `outputs_smoke/faithfulness.jsonl`. Check that all four scores exist, the cited IDs exist in the input, and model/revision metadata are present. Inspect `raw_explanation` and `parse_error` if the explanation is invalid.

If HTTP 401 appears, the two API keys differ. If the connection is refused, check both server and tunnel. If HTTP 413 appears, do not silently truncate evidence: inspect the prompt and raise the server limit only if GPU memory permits. The server defaults to 4,096 input tokens and 600 generated explanation tokens.

## 9 Run validation before final testing

Run all validation predictions and a small, fixed validation explanation sample:

```bash
python experiment.py predict --split validation
python experiment.py faithfulness --split validation --limit 20
```

Inspect the explanations and errors here. If you change the prompt or evidence protocol, do so now and use a fresh `--out` folder for all subsequent runs. The project refuses to append records from changed data, model commits, code, server settings, or faithfulness control counts to an existing incompatible run.

Before opening final test results, write down the planned comparisons: with versus without support; LLM versus baselines; faithfulness on correct versus incorrect predictions; confidence versus observed correctness. Fix the explanation sample size and random-control count (default 5). The final test must not become the place where you keep improving your prompts.

## 10 Run final test predictions and explanation checks

With the protocol frozen, run:

```bash
python experiment.py predict --split test
python experiment.py faithfulness --split test --limit 100
```

The default runs both conditions. The 100 cases are selected reproducibly without looking at correctness; if fewer are available, it uses all. Each valid explanation needs an explanation call and approximately 14 additional scoring calls with five random controls. This is why faithfulness analysis can cost more GPU time than prediction alone. Run one experiment process at a time.

For each non-abstaining valid explanation, the code:

1. Hides its cited facts and re-scores the original predicted product.
2. Retains only its cited facts and re-scores, while keeping all four candidate identities.
3. Repeats removal/retention for five random evidence sets matched by count and evidence type.
4. Reorders serialization while preserving the same product identities and attributes.
5. Tests an optional price +/-20% or ad-toggle claim. Price edits outside the development-data range are skipped and reported.

All re-scoring calls are fresh. The old explanation and old predicted answer are not passed to the prediction endpoint. The original predicted product and original runner-up stay fixed for calculating score/margin changes, including on wrong predictions.

Commands resume by skipping complete existing records. They recover an incomplete final JSONL line left by an interruption but reject corruption in the middle. An interrupted explanation case may need to repeat its model calls. Do not run two writers into the same output folder.

## 11 Review factual claims manually

Open `outputs/manual_audit.csv` in a spreadsheet application or CSV editor. It includes the actual input evidence and generated explanation. Sample explanations without selecting only good-looking ones; ideally review all test explanation cases.

For each reviewed explanation, fill `supported_claims`, `total_factual_claims`, and optional `reviewer_notes`. Leave unreviewed rows blank. Count distinct checkable claims rather than treating a whole paragraph as one claim. Never fill a blank field with zero merely because you have not reviewed it.

Examples: "A is cheaper than D" is supported only if both prices establish that comparison. "The household selected A in four supplied examples" requires counting those examples. "The household is health conscious" is unsupported because this dataset provides no such evidence. "Repeated selections suggest a brand preference" is a qualified inference; record separately if your review rubric permits it. Predefine the rubric and use a second reviewer on a subset if possible.

The unsupported factual-claim rate is `1 - sum(supported_claims)/sum(total_factual_claims)` among reviewed claims. The analysis reports the reviewed denominator. Correct citations alone do not establish that the natural-language claim is correct or that it faithfully describes the model.

## 12 Generate the report and plots

Run locally:

```bash
python analyze.py
```

The default reads `outputs/predictions.jsonl`, `outputs/faithfulness.jsonl`, prepared real cases, and the manual audit if present. It fits temperature calibration on validation scores and evaluates that fixed calibration on test scores. It also fits the conditional-logit baseline using development data only. It never fits either model to test labels.

| Output | What to inspect |
|---|---|
| `outputs/report.md` | Readable results and caveats; preview in VS Code |
| `outputs/metrics.json` | Exact values, counts, calibration temperature and baseline fitting details |
| `outputs/figures/accuracy_conditions.png` | Whether support examples improve accuracy, with uncertainty |
| `outputs/figures/calibration.png` | Whether confidence matches observed correctness |
| `outputs/figures/error_vs_coverage.png` | Error after withholding less-confident predictions |
| `outputs/manual_audit.csv` | Your factual-grounding review |
| `outputs/run_manifest.json` | Model, data, code and server settings |

Predictions are compared with the cheapest brand, development-population popularity, support most-common brand, and a development-fitted conditional multinomial logit model. The support baseline is a fair comparison for the with-history condition; the no-history condition cannot use personal examples. The logit uses price, ads, brand constants and (with history) support brand frequencies, with fixed L2 regularization.

| Metric | How to read it |
|---|---|
| Accuracy | Higher means more exact choices predicted correctly |
| MRR | Higher means the purchased brand ranked nearer first |
| Log loss | Lower is better; confident mistakes receive a larger penalty |
| Multiclass Brier sum | Lower is better; this convention sums four squared errors, range 0–2 |
| Five-bin ECE and calibration plot | Lower ECE/closer diagonal suggests better confidence calibration; small samples are noisy |
| Comprehensiveness | Drop in the original product's score after cited facts are hidden |
| Removal advantage | That drop minus the average drop for matched random evidence; positive means cited facts mattered more in this test |
| Sufficiency gap | Full-input score minus cited-only score; inspect its magnitude and sign, not just "smaller is better" |
| Keep-only absolute change | Absolute score change in the retention test; nearer zero preserves the score |
| Counterfactual agreement | Fraction of tested claims with score movement in the stated direction; skipped tests have separate denominators |
| Order flip rate | Fraction that change choice under this one serialization permutation; it does not test all formats or label-token bias |

Confidence intervals resample whole households because their purchases are related. Twenty test households produce limited precision; report the uncertainty. Explanation metrics are shown for all tested cases and separately for correct and incorrect predictions. Invalid explanations and abstentions are reported as coverage, not silently counted as passing.

## 13 Turn the results into research insights

Inspect these questions without assuming the result in advance:

- Does personal support help more than a simple brand-frequency baseline?
- When the explanation claims price sensitivity, do price interventions actually change model scores?
- When the model is wrong, does its explanation expose the evidence it relied on?
- Does calibrated confidence identify errors better than raw confidence?
- Are convincing explanations factually unsupported or weak in intervention tests?

For a case study, show the supplied evidence, actual purchase, predicted product, original score, cited facts, removal/retention/random-control results, and your manual review. Include representative failures as well as successes. Do not turn negative findings into a vague overall trust score.

The dataset records choices, not actual customer motivations. Interventions test model behavior; they do not supply ground-truth customer choices for edited scenarios. Removal can create unfamiliar inputs and related facts can substitute for one another. Brand identity remains visible in retention tests, so keep-only preservation can reflect brand priors as well as cited evidence. This small historical, fixed-four-brand benchmark cannot establish performance on a large contemporary product catalog. Public benchmark contamination by model pretraining cannot be ruled out.

## 14 Stop AWS and preserve your records

Stop the Python server with Ctrl+C, close the tunnel, and **stop the EC2 instance in the AWS console**. Closing VS Code does not stop compute charges. Retained EBS storage continues to cost money while the instance is stopped; see the AWS guide's cleanup section.

Keep the raw-data snapshot, both manifests, source code, local/server environment lock files, raw predictions, explanations, manual audit, model commit, metrics and final report. Exclude `.env` and SSH private keys from anything you share.

## References

- Jain, Vilcassim and Chintagunta (1994), [original yogurt choice study](https://doi.org/10.1080/07350015.1994.10524547).
- [Yogurt data author documentation](https://jhelvy.github.io/logitr/reference/yogurt.html), [Ecdat data documentation](https://vincentarelbundock.github.io/Rdatasets/doc/Ecdat/Yogurt.html), [Ecdat package](https://cran.r-project.org/package=Ecdat). Data are downloaded separately; original provenance and package-license metadata are retained in the manifest.
- [Qwen3-8B model card](https://huggingface.co/Qwen/Qwen3-8B).
- [VS Code Python environment guide](https://code.visualstudio.com/docs/python/environments).
- [ERASER faithfulness metrics](https://aclanthology.org/2020.acl-main.408/).
- [Faithfulness Tests for Natural Language Explanations](https://aclanthology.org/2023.acl-short.25/).
- [Limits of sufficiency and comprehensiveness metrics](https://aclanthology.org/2024.findings-eacl.88/).
- [Temperature calibration](https://proceedings.mlr.press/v70/guo17a.html).
