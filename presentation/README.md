# Research presentation

Open `index.html` directly in a browser. Its styling and selected original-response
downloads are embedded; no web service, external fonts, or network connection is
needed to read the presentation. A small embedded script positions the counterfactual
inputs near the highlighted edits; all text remains readable with JavaScript disabled.
For all linked records, unzip
`choice-study-presentation.zip` and keep the `support` directory beside `index.html`.

From `/Users/saiashwin/llm-trustworthiness`, refresh the same dashboard with:

```bash
.venv/bin/python -B scripts/build_presentation_report.py --refresh-aws
```

The command reads the authoritative AWS continuation through the existing SSH
identity. It makes no model calls, performs no remote writes, and does not acquire
experiment writer locks or modify the model, queue, inputs, or original results.
The dashboard stays separate from `outputs_resumed_v1/dashboard.html`, which the
experiment queue manages.

The read-only snapshot captures newline-complete intervention records first,
explanations second, and predictions last. Read sizes are bounded at file-open time.
A trailing unfinished record is excluded and documented in provenance; malformed
complete records cause a failure. Source file hashes, record hashes, parent links,
household splits, prompt reconstruction, and before/after measurements are verified.
Independent checks recompute displayed accuracy, baseline counts, and measured
denominators, check downloadable quotes and links, and exercise partial-record reads.
The main page is replaced atomically only after these checks pass. The old page and
all experiment outputs survive a failed refresh. A ZIP contains the matching source
snapshot; older snapshots remain available locally.

Omit `--refresh-aws` for a local rebuild using the saved snapshot. Formatting is in
`presentation_src/style.css`; assembly and data-driven takeaways are in
`scripts/build_presentation_report.py`. Metadata and source counts belong in the
supporting files, not the presentation. The page contains no execution status.

Explanation examples preserve the original wording. The example selection rules,
prompt-version cohorts, citation policy, baseline definitions, record IDs, and
intervention denominators are recorded in the linked sources. Random controls are
not called uncited unless their evidence IDs are disjoint from the cited set.
All example prompts are displayed verbatim in scrollable panels. The counterfactual
section shows four types: cited removal, comparable uncited removal, a price change,
and presentation order. Original and edited inputs and predictions appear side by
side; highlighted lines differ in content or position from the saved original input. The builder
verifies the full displayed prompt text and highlighted changes against source records.
The observed purchase is explicitly the original dataset outcome, hidden from the
model; it is not a customer outcome for the edited scenario. The uncited example can
reuse a measured keep-cited test when its actual masked complement is wholly uncited
and matches the cited-removal case in evidence count and type. This equivalence is
verified from edited evidence and recorded with the source record IDs.
Example cards omit split labels; aggregate prediction sections retain their split names.

Local rendering was checked with headless Chrome using a fresh temporary profile.
`scripts/render_presentation_preview.py` is an optional local QA helper; it does not
alter the report or require the experiment server.
