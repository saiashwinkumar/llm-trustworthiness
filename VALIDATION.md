# CPU continuation validation — 17 October 2026

This section records checks of the continuation supplied with `cpu-experiment-update.zip`. Historical upgrade checks below remain the original recorded evidence.

- `python -m compileall -q choice_trust scripts tests` passed.
- `python -m unittest discover -s tests -q`: **69 tests ran; 68 passed and one optional historical-run test skipped because its local source folder was absent**. Tests cover strict citation limits, eligible explanation measurements, monotonicity direction, frozen study scopes, missing-work accounting, review identity, integrity and resume behavior.
- The complete orchestrator sequence (smoke, validation, freeze, test, report, status) ran with the synthetic product backend and prepared synthetic data. Repeating the test phase wrote zero new records. An attempted concurrent phase was correctly refused.
- The synthetic run had 24 predictions, 24 explanations and 512 intervention records across its formal validation/test phases. These are software fixtures, not customer-choice research findings. Artificial review values used only to test completion were explicitly marked synthetic; they are not human grounding assessments.
- Completion reporting distinguished automated work from the fixed review sample. Editing an audit after report generation made the saved completion snapshot stale; dashboard generation refused to present it as current.
- **18 DOM-stub runtime checks passed**, with no console errors, against the actual embedded dashboard JavaScript: completion states, tabs/filters, measured and skipped interventions, safe text and unavailable legacy measurements. No real-browser layout, accessibility or native-interaction check was possible in this environment. Historical browser checks below do not verify the new UI additions.
- The real prepared dataset's status confirmed scopes of 612 validation predictions, 1,608 test predictions, 100 test explanations per condition, and 30 with-history systematic test cases. This read-only check made no model calls.
- The targeted installer passed disposable-copy checks against the uploaded archive: dry-run without mutation, active writer/orchestrator refusal, original-file backups, repeat-apply idempotence, unknown-edit refusal, and preservation of every unlisted file including data, environments and earlier outputs.

**No live AWS inference or full real-model study ran here.** The user's earlier live-server verification is reported context, not a check repeated in this environment. The stricter prompt still requires a new real smoke check. A completed stage counts recorded attempts, including invalid explanations and skipped measurements; it does not certify accuracy or faithfulness.

Server and scoring code, prepared data, earlier output records and historical reports are preserved. The continuation uses fresh v3 output/control folders. Manual factual review remains the researcher's work.

# Historical upgrade validation — 17 October 2026

These checks validate software behavior. Synthetic measurements are not research findings.

## Automated checks

Executed in the existing local `.venv` (Python 3.13.6), without installing any new packages:

```bash
python -m compileall -q choice_trust server.py tests
python -m unittest discover -s tests -v
```

**38 tests passed**, including all eight unchanged legacy tests. Coverage includes:

- Outcome/post-decision exclusion, explicit evidence review, separate support observations, group-disjoint splits, absent-date rejection, and development-only bounds.
- Legacy yogurt IDs/splits, equivalent CSV and JSONL adapters, 2/5/7 candidates, shared text-classification machinery, and stable IDs through presentation changes.
- Context-sensitive label tokenization, token-boundary failures, prefix collisions, >26 labels, conditional multi-token likelihoods, score normalization, and prediction-only backend handling.
- The actual server's generic scoring method executed with deterministic tensor doubles: single-token fast path, multi-token accumulation/conditioning, prefix forward reuse and context-limit rejection without truncation.
- Intervention isolation, candidate preservation, cleared edited outcomes, numeric bounds, cross-field constraints, matched random controls, fixed original rival after winner changes, and unavailable scores.
- Invalid/missing/abstaining/truncated explanations, unavailable citations, blank versus completed manual audits, invalid claim-count reviews.
- Record integrity, source prediction/explanation changes, dataset snapshot changes, single-writer locks, protocol mismatch rejection, interrupted-tail recovery and completed-record resume.
- Safe HTML embedding, credential redaction, historical import preservation and explicit absence of historical edited score vectors.

`tests/test_framework.py` includes an optional test using the locally available real historical pilot; it skips only when those untracked results are not present on another checkout. Generic fixtures are checked in under `examples/`; the yogurt compatibility fixture is generated in memory. No test requires rebuilding existing data.

## End-to-end saved demonstrations

| Run | Predictions | Explanations | Intervention records, including skipped |
|---|---:|---:|---:|
| `outputs_v2/demo_products` | 18 | 18 | 250 |
| `outputs_v2/demo_text` | 18 | 18 | 90 |
| `reports/cpu_pilot_v2` (historical conversion) | 40 | 20 | 190 |

Both synthetic workflows ran preparation → prediction → explanation → counterfactuals → analysis → HTML. Products include 2, 5 and 7 candidates. The text workflow uses the same shared modules. Repeating the final product prediction and intervention commands wrote **zero new records**. The imported pilot retains its original predictions, explanation failures and available effects, without reconstructing missing edited score vectors.

## Browser verification

Headless Google Chrome opened the actual standalone HTML artifacts through `file://`, with no hosted application. All assertions passed on the real pilot, product demonstration and text demonstration:

- Initialization and tab navigation.
- Search and useful empty states.
- Correctness and confidence filters.
- Counterfactual type/measurement selection.
- Exact saved intervention reference and edited prediction.
- All seven candidate scores before/after for a selected product intervention.
- Explicit missing-score state for historical interventions.
- Methods/provenance display.
- No external resources or fabricated-input sliders.
- Adversarial `</script><img … onerror=…>` model text remains inert.
- Text dashboard fits a 520-pixel narrow viewport without horizontal overflow.

Desktop and narrow layouts were visually inspected. Machine-readable results are at `reports/browser_validation.json`. `tests/browser_smoke.py` generates a repeatable local harness without editing a run:

```bash
python tests/browser_smoke.py reports/cpu_pilot_v2/dashboard.html /tmp/choice-report-check.html
```

Open the harness in Chrome, or execute Chrome's `--headless --dump-dom file:///tmp/choice-report-check.html`; inspect the `browser-test-result` element for PASS/FAIL. Browser executable paths vary by OS.

## Preservation and configuration checks

SHA-256 checks verified **31 pre-existing credential/data/result files unchanged**, including `.env`, real raw/prepared data and manifests, synthetic prepared data, pilot/smoke/demo predictions, explanations, audits and reports. No environment packages were changed. Original experiment and analysis command interfaces were preserved. New outputs are in separate directories.

The historical manifests verify Qwen/Qwen3-1.7B at revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`, CPU float32, 4096 input / 600 explanation-token limits. The EC2 instance type is not recorded; m7i.xlarge remains the user's stated deployment, not an independently verified fact.

## Checks not performed

The configured health endpoint returned **connection refused**, including outside the filesystem/network sandbox. Consequently no live prediction/explanation smoke call could run. No large experiment was launched, no AWS resource was provisioned, and the remote server was not modified.

Actual Qwen tokenization, upgraded server dependency loading, authentication over the tunnel, real multi-token inference and CPU performance must be verified when the existing server/tunnel are reachable. Torch/Transformers are not installed locally; numerical server tests use deterministic doubles, not actual model weights. Existing historical results verify the old CPU deployment only.

The original SciPy/Matplotlib analyzer was not rerun in the new dependency-free environment; its existing saved outputs were preserved. New analysis and dashboard generation were executed. The original conditional-logit implementation remains available through `analyze.py`; no universal cross-dataset logit feature specification is claimed.

No factual-grounding audit was invented or filled in, no absent calibration data was supplied, and no synthetic result is presented as empirical LLM performance. See `docs/FRAMEWORK.md` for scoring interpretation, dependence assumptions and methodological limits.
