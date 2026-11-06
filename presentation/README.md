# Actual experiment presentation

Open `index.html` directly in a browser. It is self-contained: styles, tab behavior,
offline MathML formulas and downloadable source packets are embedded. No CDN,
server, login or network connection is required to read it. There are exactly two
main tabs: **Evaluation** and **One complete example**.

Refresh the saved EC2 annotation snapshot and rebuild:

```bash
.venv/bin/python -B scripts/build_experiment_presentation.py --refresh-aws
```

Rebuild offline using the last captured immutable snapshots:

```bash
.venv/bin/python -B scripts/build_experiment_presentation.py
```

These commands never call the predictor or annotator, regenerate predictions,
change protocol/settings, or write to EC2. The refresh option uses read-only SSH
with the existing experiment identity. The independent overnight annotator can
continue running while its already published results are captured.

`report_config.json` freezes **row-44** as the complete example. Selection ranks
saved-record completeness, then applicability breadth, then numeric query ID; it
does not consult correctness, explanation quality or annotation judgments.

Original prediction accuracy for the joint workflow shows only Test with history.
The existing score-then-explain workflow's accuracy
is shown separately for all three splits, with both support conditions. All other
displayed metrics show only Test with history; their Development/Validation and
Test-without-support results are omitted.

Supporting files in `support/actual-experiment-*/` retain metric definitions,
counts, exclusions, canonical-identity comparisons, exact prompts/responses,
source hashes and annotation linkage. Both source downloads also work from the
standalone HTML. `actual-experiment-presentation.zip` bundles the HTML with its
matching supporting files and frozen report configuration. Older snapshots and
the previous report (`earlier-workflow.html`) are preserved.

Luna assessments are automated, not human-confirmed truth. Only structurally
traceable complete-source annotations enter aggregate metrics; failed raw records
remain preserved. Earlier raw Qwen annotations and agent-assisted correction
proposals remain in their separate source layers and are not substituted or
represented as human review.

The frozen stale metric is response-level; the requested claim-level view has an
explicit separate denominator. A conservative read-only adapter handles supported
Luna deciding rules and changed-field influence matches; these choices and any
comparison with the archived matcher are documented in the supporting analysis.
No old metric output or annotation is overwritten. See
`docs/EXPERIMENT_PRESENTATION.md` for these details and unavailable results.

Focused source-integrity checks run before the main page is replaced. Local Chrome
QA verifies both tabs, arrow/Home/End keyboard navigation, offline formulas,
responsive layout, exact source quotations and changed-span highlighting:

```bash
.venv/bin/python -m unittest tests.test_experiment_presentation tests.test_test100_metrics
.venv/bin/python scripts/render_experiment_presentation.py --width 1440 --tab evaluation
.venv/bin/python scripts/render_experiment_presentation.py --width 1440 --tab example
```

The old `build_presentation_report.py` command belongs to the archived earlier
workflow and is not the builder for this two-tab report.
