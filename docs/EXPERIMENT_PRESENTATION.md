# Saved-record, two-tab experiment presentation

Build: `.venv/bin/python -B scripts/build_experiment_presentation.py --refresh-aws`.
An offline rebuild omits `--refresh-aws`. The output is `presentation/index.html`,
with embedded CSS, JavaScript, native MathML and two JSON source downloads.
`presentation/actual-experiment-presentation.zip` adds matching supporting files.
No prediction, annotation, OpenAI client, model server, protocol edit or remote
write occurs in the builder. The existing annotator continues independently.

## Data and snapshot boundaries

The current joint experiment is the two-query development pilot and the frozen
100-query test/with_history run. No joint validation or test/without-support run
is invented. The presentation shows joint-workflow original accuracy only for
Test with history. The existing
score-then-explain accuracy is shown separately for all three splits and both
support conditions. Every other displayed metric is restricted to Test with
history. The two workflows are not pooled. Household split
and model provenance remain those saved by the original experiment. No weight
training/fine-tuning is claimed.

With refresh enabled, read-only SSH captures the set of published canonical Luna
records first. Each is immutable and was atomically published by the existing
writer; it is read once. Reused pilot links resolve to their exact preserved raw
records. Mutable states/attempts/progress files and partially published adapters
are not used for annotation results. Snapshot hashes and original remote paths
are retained. The earlier append-only workflow uses its existing bounded,
newline-complete, child-before-parent snapshot reader. All report calculations
then use these immutable local snapshots.

Test source responses, complete saved prompts, runtime/input signatures, model
identity, frozen manifest, canonical answer decoding and source hashes are
validated through the existing metrics loader. Luna records must match the exact
response hash, request, settings, guide/schema versions, raw response and parsed
diagnostics. Their quotations, evidence fields and candidates are revalidated
offline. Only complete-source records passing traceability checks enter aggregate
annotation metrics; invalid raw annotations are preserved and listed as exclusions.
The three pre-existing truncated predictor outputs remain excluded from full
explanation coverage even if their literal prefixes later receive annotations.

The report's example is frozen as **row-44** in `presentation/report_config.json`.
Its selection ranks complete decodable saved responses, then applicable family
count, then numeric query ID. Correctness, change outcomes, explanation wording,
annotation quality and annotation availability do not affect selection. It has
all eight applicable edit families. Later annotations cannot change the example.

## Definitions and deliberate reporting adapters

The frozen prediction formulas and denominators are preserved. Original accuracy
uses evaluated original predictions with known targets. Change/invariance use
valid decoded original–edited product pairs; skipped and malformed outputs are
excluded rather than classified unchanged. The100 original targets are never
used as customer outcomes for edited scenarios. Results are reproduced against
the existing saved prediction metrics during every build.

Conditional change rates retain decisive/contributing versus no-claimed-influence
as distinct labels, regardless of factual status. The report additionally requires
actual changed-field overlap, or an explicit support-purchase-frequency dependency,
to avoid treating every mention of a parent concept as a reason about every edit.
Broad group-only claims remain unclear. An absent relevant claim can enter the
negative group only for a Luna record reporting complete claim extraction; the
older Qwen annotations have no complete-coverage assertion. This is a documented,
more conservative reporting adapter, not a silent rewrite of the frozen analysis.
Per-pair differences from the archived matcher appear in evaluation.json under
`influence_match_differences`. Linked-annotation and claim-classification coverage
are shown separately. No-claimed-influence is never called proof of non-use.

The existing automatic rule evaluator supports a unique-cheapest-current-product
template. The report can consume a full Luna rule only when it is the sole saved
rule, explicit, sufficiently specified, eligible, scoped to all current candidates,
links exactly one decisive claim, has valid supported premises, and lists only
the complete-price/unique-minimum conditions implemented by that template.
Contributing or ambiguous reasons, other rule types, extra conditions, invalid
premises, missing prices and ties stay unassessable. The raw rule remains intact;
a validation-only in-memory projection supplies the existing evaluator's narrower
`rule_specification`. No universal rule is inferred from prose or a price mention.

Factual contradiction follows the existing guide: contradicted / (supported +
contradicted) claims, with originals and edits separate. Unsupported, unclear and
not-applicable claims are excluded and counted separately. Each explanation is
counted once, not once for each intervention pair.

The frozen stale metric is **response-level**: distinct assessable edited
explanations containing at least one stale label / assessable edited explanations.
A positive needs an explicit stale label; a negative needs complete assessable
staleness coverage. The report preserves this definition.

The user's requested **claim-level** stale rate is an explicitly separate
descriptive view; no claim-level denominator was frozen in the earlier protocol.
Here eligibility means complete-source edited claims whose comparison extension
says `temporal_scope=current_edited` and `stale_status=stale|not_stale`. The numerator
is those labelled stale. Explicit original references, general/influence claims,
unclear scopes, unassessable and not-applicable statuses are excluded. This ratio
uses all assessable current assertions, including assertions judged not stale;
it is not a ratio restricted only to assertions about modified fields. Its source
annotation coverage and eligible-claim coverage are displayed. Its denominator
is never pooled with the response-level metric.

Development raw annotations are the existing Qwen3-1.7B layer; test annotations
are GPT-6 Luna. Only the test annotation metrics are displayed. The two layers
are never combined into a single estimate. Two of the six development raw annotations pass structural
checks; their semantic limitations are explicit, including the saved false
support judgment about an unknown paid price. Agent-assisted proposed corrections
are preserved separately and not substituted or labelled human review. No
annotation is treated as semantically validated simply because it parses.

## Example and source preservation

The main example displays original source offers and all unordered support
records, a separately labelled hidden target, exact saved observations, actual
joint prompt, verbatim explanation, decoded prediction and its original citations.
Only the exact matching Luna annotation fills the Luna column. The older local
annotator column displays the separately labelled Development case
`row-1289__no_history__ORIGINAL`, a diagnosed failure from the existing six-record
agent-assisted audit. It highlights the false minimum marked supported, the
nonexact returned quotation, and the omitted explicit price-influence statement.
Exact source facts, predictor explanation, raw annotation and pending review
questions remain expandable. Proposed corrections are labelled agent-assisted,
pending user review; no human review is claimed. These different cases are not a
matched comparison of annotator accuracy, and the pilot labels do not enter Test
metrics. The example source download includes the pilot records and audit hashes.

All eight actual edit families remain visible. Patches come directly from the
frozen manifest. Historical offer removal groups its exact changed fields by
record for readability and retains purchase identities. Each full original/edited
prompt and explanation is preserved character-for-character beneath markup-only
diff spans. Answer mapping displays product→answer identifiers and compares
decoded product identities. Missing edited annotations are not replaced with
pilot records or newly generated labels. Rebuilding incorporates newly published
matching annotations without changing the example selection.

`complete-example.json` and its embedded download preserve exact messages,
rendered prompts, raw predictor responses, token records, mappings, source facts,
raw annotation/API responses, requests, guide versions and diagnostics. The
evaluation download retains formulas' source counts, pair assessments, coverage,
exclusions and matcher differences. Source provenance also records snapshot
hashes and development source hashes. The former presentation and all earlier
source snapshots remain preserved. Main-page replacement is atomic and follows
successful integrity checks.

## Verification

Focused tests cover exact changed-field matching, false factual premises retaining
claimed influence, description versus influence, frequency versus removed offers,
stale denominators and explicit-original references, rejection of a contributing
consideration as a unique rule, exact diff reconstruction, stable example selection
and execution with network/inference entry points disabled. The existing metrics
tests additionally cover canonical mapping, malformed responses and zero
denominators. The source-to-HTML verifier checks both tabs,13 offline formulas,
all selected prompts/quotes and all eight families before publication.

`scripts/render_experiment_presentation.py` uses a separate temporary local
headless Chrome profile. It checks arrow/Home/End navigation, exactly one visible
panel, no external asset requests, native formula layout and responsive overflow,
and saves screenshots for visual inspection. It does not touch experiment
processes. No overall trust/faithfulness score, KL causal score, Pearson score,
new human review or new experimental measurement is manufactured.
