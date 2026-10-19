# Framework contract, methods and extension guide

## Architecture and compatibility

The new `python -m choice_trust` CLI wraps a small standard-library package:

| File | Responsibility |
|---|---|
| `schema.py` | Common case validation, evidence visibility and masking |
| `adapters.py` | Yogurt, configurable product CSV/JSONL, text classification, group/temporal splits, development-only edit support |
| `model.py` | Outcome-free prompts, explanation parsing, real/mock backend contracts and capability negotiation |
| `scoring.py` | Stable answer-label mapping, contextual tokenization validation and sequence score normalization; shared with server |
| `interventions.py` | Fixed grids, admissible edits, type-matched random controls, fixed-reference measurements |
| `runner.py` | Separate predict/explain/counterfactual stages and hash-linked manual audit templates |
| `storage.py` | Atomic manifests, fsynced records, content hashes, source links, single-writer lock and resume validation |
| `evaluation.py` | Metrics, group bootstrap, calibration, baselines, separate explanation/grounding/robustness dimensions |
| `legacy.py` | Read-only historical conversion with provenance warnings |
| `dashboard.py`, `dashboard.html` | Safe offline embedding and interactive saved-measurement views |

The original `experiment.py`, `prepare_data.py`, `make_demo_data.py`, and `analyze.py` retain their interfaces. Reusable JSONL/env helpers are imported from `experiment.py`; its yogurt-specific engine is not used for generic experiments. Its numerical/scientific plotting dependencies remain optional for the new workflow.

`server.py` keeps the old endpoints and introduces `/score_candidates`. Its default is the recorded Qwen3-1.7B CPU checkpoint. Changing defaults does not restart or modify an existing server. No AWS provisioning or remote deployment is performed by these scripts.

## Common prepared case schema, version 2

One JSON object represents one complete occasion or classification example:

```json
{
  "schema_version": 2,
  "case_id": "occasion-101",
  "dataset_id": "speaker-purchases",
  "task": "purchase",
  "group_id": "customer-12",
  "split": "test",
  "time": null,
  "synthetic": false,
  "candidates": [
    {"id": "sku-1", "name": "Compact speaker", "attributes": {"price": "attr:sku-1:price"}},
    {"id": "sku-9", "name": "Large speaker", "attributes": {}}
  ],
  "evidence": [
    {"id": "attr:sku-1:price", "candidate_id": "sku-1", "type": "price",
     "source": "displayed_price", "value": 49.0, "units": "USD",
     "pre_decision": true, "editable": true,
     "policy": {"kind": "numeric", "multipliers": [0.8, 1.2],
                "min": 0, "development_bounds": [20, 120]}},
    {"id": "context:request", "candidate_id": null, "type": "text",
     "source": "pre-purchase request", "value": "For a small room",
     "units": null, "pre_decision": true, "editable": false}
  ],
  "outcome": "sku-1",
  "constraints": [],
  "task_note": "Purchase among displayed alternatives; no verified timestamps."
}
```

Candidate attributes reference evidence IDs; they do not duplicate values in an unmaskable candidate description. Names/identities remain visible under masking. IDs must be unique within cases; case IDs must be unique within the dataset. Candidate counts can vary case by case. A prepared dataset contains one dataset ID/task and cannot mix real and synthetic records.

Supported task semantics are `purchase`, `click`, `rating_choice`, `sampled_candidate_ranking`, and `classification`, all represented as one optional observed candidate ID. Continuous ratings, multilabel classification, regression, images, open-ended generation, sets of simultaneous purchases, and arbitrary modalities need additional adapters/metrics. `rating_choice` means an explicitly constructed categorical choice from ratings, not continuous rating prediction. The schema does not infer that unobserved products were rejected. Include a no-purchase candidate only if actually supported by the source and document this in the task definition.

Evidence can contain scalars, structured JSON, or text. Units and source are explicit; unknown units remain null. Context evidence has no candidate ID. History must identify a separate `observation_id`, and no query case may be reused as a history observation. The yogurt adapter uses original support source rows when the original manifest is available, otherwise explicit support identifiers with no claim of chronology.

Prompt builders use only the task, candidate IDs/names, and allowlisted evidence values/types/units. They never serialize the original case object, its outcome, split, post-decision metadata or arbitrary extra top-level fields. An adapter cannot automatically recognize semantically leaked facts hidden in arbitrary text or product names: input allowlists and `pre_decision_reviewed: true` are a researcher-reviewed contract, not a proof of data validity.

## Configurable product adapter

CSV is **long format**: one row per available candidate, with one shared case ID for the complete choice occasion. Outcome must be a stable candidate ID, repeated consistently across rows (or blank on every row). Group, split, time, and context must be consistent within an occasion. Duplicate candidate IDs and ambiguous split assignments are rejected.

```csv
occasion,customer,partition,chosen,sku,name,display_price,promotion,request
101,C12,test,S1,S1,Compact speaker,49,1,Small room
101,C12,test,S1,S9,Large speaker,99,0,Small room
```

A corresponding config:

```json
{
  "adapter": "product",
  "dataset_id": "speakers-v1",
  "synthetic": false,
  "pre_decision_reviewed": true,
  "task": "purchase",
  "task_note": "Actual purchase among available speakers; no dates provided.",
  "fields": {"case_id": "occasion", "group_id": "customer", "split": "partition",
             "outcome": "chosen", "candidate_id": "sku", "candidate_name": "name"},
  "attributes": [
    {"name": "price", "column": "display_price", "type": "price", "dtype": "number",
     "units": "USD", "editable": true,
     "policy": {"kind": "numeric", "multipliers": [0.8, 1.2], "min": 0}},
    {"name": "advertised", "column": "promotion", "type": "ad", "dtype": "boolean",
     "editable": true, "policy": {"kind": "categorical", "values": [false, true]}}
  ],
  "context": [{"name": "request", "column": "request", "dtype": "text"}],
  "seed": 42,
  "split_strategy": "group"
}
```

Missing optional candidate attributes are omitted; no zero price or false ad is invented. Supported declared dtypes are number, boolean, text and JSON. Price and advertising are optional conventions; other attributes work through the same policies. JSONL contains one complete object per case with a `candidates` array; candidate fields use the same mappings as CSV. See the equivalent [product JSONL](../examples/products.jsonl), [CSV](../examples/products.csv) and [config](../examples/products.config.json).

Optional `history` is a JSON array (a JSON-encoded cell in CSV):

```json
[{"observation_id":"separate-occasion-22","value":{"choice":"S9","note":"independently observed support occasion"}}]
```

The adapter does not automatically turn query labels into history. Do not provide future/post-decision histories. Dates, if supplied, must be genuine ISO-8601 strings with consistent timezone usage. Explicit supplied splits are preserved and checked for group overlap. If splits are absent, the default makes reproducible group-disjoint 60/20/20 allocations, keeping occasions intact. Tiny groups are adjusted so all three splits exist. `split_strategy: "temporal"` sorts groups by supplied dates and rejects overlapping boundary intervals; it does not infer dates from IDs or row order. For complex panel/time designs supply externally justified group-disjoint splits. Temporal designs with the same customer in multiple splits require an additional explicit adapter/protocol; the current validator rejects such overlap.

## Text classification adapter

Use one row/object per example with the mapped text/outcome fields and a declared label set:

```json
{"adapter":"text","dataset_id":"reviews-v1","task":"classification",
 "synthetic":false,"pre_decision_reviewed":true,
 "labels":[{"id":"negative","name":"Negative sentiment"},{"id":"positive","name":"Positive sentiment"}],
 "fields":{"case_id":"review_id","text":"review_text","outcome":"sentiment","group_id":"author_id"}}
```

The whole text is one evidence block by default. Removal and retention at that granularity are intentionally coarse. More informative sentence/span tests need an adapter that emits stable block/span IDs and preserves their semantics. No price/ad claims or editable-text sweeps are invented.

## Intervention policies and constraints

Numeric policies use either absolute `grid` values or `multipliers`. Their admissible range is the intersection of optional declared `min`/`max` and min/max observed in **development** evidence with the same type and attribute name. The engine does not estimate test-distribution bounds. If development support is absent, numeric edits are skipped. A changed price need not be plausible just because it lies inside a numerical range; richer constraints belong in the adapter.

Categorical policies enumerate `values`. A boolean ad is just a categorical alternative. Text and history are not editable unless an explicit supported policy is declared. Masking does not change candidate availability or treat missing evidence as zero. Every edited scenario clears the observed outcome.

Cross-field constraints compare named attributes of each candidate:

```json
{"constraints":[{"left":"sale_price","op":"le","right":"list_price"}]}
```

Supported operators: `le`, `lt`, `ge`, `eq`, `ne`. Missing fields or violations cause a skipped measurement with a reason. Domain constraints across candidates or complex causal dependencies require an adapter extension. Unrelated evidence is held fixed, and originals are deep-copied.

The systematic grid runs regardless of whether an explanation is valid or convincing: each editable attribute's predefined sweep/alternatives, all-history masking where present, and seeded candidate presentation permutations. Labels and IDs remain fixed under presentation changes. At most two distinct nonidentity permutations are attempted by default; two candidates have only one distinct nonidentity permutation. This tests serialization sensitivity, not all possible formatting or answer-label biases.

Explanation tests remove cited evidence, retain only cited evidence, and repeat both with five random sets matched by count and type. Random sets may overlap the citations; when only one fact of a type exists, a matched control may be identical. This limits power and is not silently repaired by matching a different type. Responses with unreadable JSON, missing required fields, unsuitable field types, unavailable or duplicated citations, empty supporting citation sets, or recorded truncation are retained with specific diagnostics; cited-evidence tests are skipped when these checks prevent use. Any number of available, distinct evidence IDs is allowed. Systematic tests still run. An explanation response record, including one with recorded issues, must exist before the intervention stage; this avoids later attaching a new explanation to already-saved measurements.

Explicit claims have a cited editable `evidence_id`, concrete proposed `value`, and `expected_direction` concerning the original selected candidate. Agreement is tested only for that exact edit. Merely citing price does not imply a directional claim. Score differences within ±1e-6 do not count as directional agreement. A separate own-price monotonicity diagnostic measures whether the affected candidate score is nonincreasing with price (allowing numerical ties); it is not an explanation metric or a claim about economic/customer causality.

## Scoring and backend capabilities

The client maps sorted stable candidate IDs to A…Z, AA… and keeps the mapping unchanged under reordering. Generic server requests have the form:

```json
{"prompt":"…", "answers":{"sku-1":"A","sku-9":"B"}}
```

`/score_candidates` returns `prediction` and normalized `scores` keyed by candidate ID, plus answer token IDs/counts, unnormalized answer log likelihoods, score method and model identity. It supports 2–256 answers subject to input/context limits. In the actual rendered chat-template context, labels must tokenize as a suffix without changing prompt tokens. Duplicate or token-prefix-overlapping answer sequences are rejected. For >26 candidates the client scores newline-terminated labels so A and AA represent complete, nonoverlapping answer strings.

For a token sequence y, scoring is `sum_t log P(y_t | prompt, y_<t)`, then a softmax across candidate sequences. **No length averaging** is applied: longer strings can be disadvantaged. This is likelihood of the exact supplied answer strings, not semantic class probability over all verbalizations, and includes the newline token when used. Single-token answers share one forward pass. Multi-token scoring caches requested prefix/token log probabilities, with one forward per distinct prefix, retaining final-position logits only. It is exact teacher forcing but may be slow on CPU. Tests verify the actual method against deterministic tensor doubles; real tokenizer/model execution awaits the endpoint smoke test.

`/health` advertises `scores`, `variable_candidates`, `multi_token_labels`, `explanations` and the maximum candidate count. A compatible prediction-only backend can advertise scores=false and implement `/predict` with the same candidate-ID contract. The client discards any self-reported confidence and returns `scores: null`. Accuracy, winner changes and presentation robustness remain applicable; score/margin/log-loss/calibration measurements are explicitly unavailable. This repository ships the scored Transformers server and a mock backend; it does not bundle arbitrary third-party service integrations.

Legacy `/score` still uses A–D next-token normalization and retains its response keys. The client only uses it when the case has exactly four candidates. **Normalized scores are model answer scores requiring calibration, not automatically validated customer-choice probabilities.**

Qwen's [official quickstart](https://qwen.readthedocs.io/en/stable/getting_started/quickstart.html) documents disabling thinking through the chat template. The [Transformers Qwen3 implementation](https://github.com/huggingface/transformers/blob/main/src/transformers/models/qwen3/modeling_qwen3.py) exposes last-position logits support. Server code retains `enable_thinking=False`, fixed greedy explanation decoding and explicit context limits from the original protocol.

## Evaluation and uncertainty

Accuracy uses every labelled original prediction; MRR, natural-log loss, multiclass Brier sum (range 0–2), five-bin ECE and selective-error curves use only available genuine normalized scores. Tied ranks use their average rank; tied confidence cutoffs retain all equal-confidence records. Candidate-count strata and per-case uniform chance `1/n` replace the four-choice assumption.

Baselines are development-population frequency with Laplace smoothing restricted to each available set, cheapest where complete prices exist, and support frequency where personal support is supplied. Population frequency has no claim of product-feature generalization to unseen catalogs. The original yogurt conditional-logit baseline remains in `analyze.py`; the generic engine deliberately does not infer universal cross-dataset feature/utility specifications. Use the legacy analysis for that historical baseline or add an adapter-specific baseline with documented development-only fitting.

Temperature is selected on validation predictions only from 121 fixed log-spaced values over exp(-3) to exp(3), then applied to test scores. Small validation sets give unstable calibration; the grid can hit its bounds. No validation data means calibration is unavailable. Raw and calibrated test scores are both reported, without silently rewriting recorded predictions.

Behavioral score change is edited minus original. Removal advantage is the cited drop minus average matched-random drop, calculated within each case before aggregation. Fixed-rival margin is `log(score(original winner)) - log(score(original strongest other candidate))`, with floor 1e-12. The reference and rival never switch after edits, including on incorrect predictions. Retention reports signed and absolute changes. Explicit-claim agreement, presentation flips, invalid citations, abstentions, truncations, coverage and skip reasons have separate denominators.

95% percentile intervals resample entire supplied groups with replacement, seed 42, 500 draws by default; missing group IDs fall back to case IDs. At least two groups are required for an interval. Repeated systematic measurements are weighted per measurement and clustered by group; paired removal contrasts are per case. Coverage uncertainty applies to explanation attempts, with missing attempts shown separately. Subgroup analysis is exploratory, and dependence beyond supplied groups is not modeled.

## Run artifacts and safe resume

A run contains a frozen common-case snapshot, run manifest, `predictions.jsonl`, `explanations.jsonl`, `interventions.jsonl`, manual audit CSV, metrics JSON, Markdown findings, and standalone HTML. Records keep raw responses, prompts, label maps and explanation failures. Manifests record source/prepared hashes, adapter configuration, split assignments, evidence policies, model revision, backend settings/precision, prompt/protocol versions, decoding settings, seeds and code hash. The run ID is the manifest digest. Each explanation links to its exact original prediction hash; each intervention links to both source hashes and stores original/edited evidence and available scores.

One writer per run is enforced with `.writer.lock`, containing its PID. Ctrl+C releases the lock. After an unclean process kill, verify that the PID is stopped before manually deleting the stale lock. Do not delete a live writer's lock. Complete records are fsynced; only an incomplete last JSONL line can be repaired on resume. Middle corruption, duplicate records, changed source records, mixed run IDs and incompatible manifests are rejected. A model call interrupted before its complete record is saved will repeat. Report generation validates input hashes and refuses partially written/corrupt sources; run it after the writer has stopped.

The code fingerprint is deliberately conservative and covers the package, including reporting code. After changing source, start a new inference folder. Existing runs can still be analyzed/read through their frozen metadata. These hashes detect accidental changes, not malicious tampering with both data and recomputed manifests. Historical imports are explicitly less verifiable and cannot be resumed as new v2 inference.

## Dashboard and boundaries

The HTML embeds JSON with HTML-significant characters escaped and creates model-text elements through `textContent`. It has no external resources, network calls or interpolation of unmeasured model outputs. A restrictive content security policy and credential-field/exact-key redaction protect generated reports. Audit exports escape formula-like strings. Reports still contain the input data and model text: apply your dataset's sharing rules before distributing them.

Case filters support correctness, confidence, dataset, condition, group/case search and available intervention type. The lab selects saved measurements only. “Not measured,” skipped, invalid, missing and zero effects remain distinct. Synthetic warnings persist across all views. Useful empty states handle absent measurements. No LLM judge or unexplained composite trust score is used.

Remaining methodological limits include post-hoc rationalization, correlated/redundant evidence, distribution shift under masking, limited permutations, label verbalization/length effects, finite group counts, benchmark contamination, observational rather than causal customer data, and human audit subjectivity. None of the tests establishes actual customer motives or a true outcome for an edited scenario.

## Citation policy and prompt provenance

The current citation policy is `available-evidence-unlimited-v1`; the future prompt is
`common-evidence-v4-unlimited-citations`. The output JSON keys remain `evidence_ids`,
`explanation`, and `counterfactual`; nested counterfactual fields are unchanged.
The parser stores JSON readability, required-field presence, ID availability, and
duplicate-ID checks separately under `citation_assessment`. It never trims citations.
Legacy wrapped JSON extraction remains supported and is explicitly identified.
Eligibility means a nonempty supported citation set suitable for evidence removal/retention,
not factual correctness or an eligible explicit counterfactual claim.

Future run manifests and explanation records record prompt and citation-policy versions.
The separate historical reassessment in `reports/citation_policy_v1` binds each assessment
to its source file, line, hashes, and complete previous record. It does not replace historical
assessments or mark skipped interventions as measured. See `docs/CITATION_POLICY.md`.
