# GPT-6 Luna: ten original explanations for inspection

**Executed on 2026-10-25 after the user supplied the key and authorized the run.** All ten original-only Luna responses are saved: nine pass structural/traceability checks; row-2227 fails the exact-quotation check for claim C5. The raw result is preserved without repair or retry. There were exactly ten API attempts, no fallback model, and no truncated responses. No predictor calls were made.

The model returned 81 claims and two rule objects. These are model annotations, not human-reviewed judgments; neither factual correctness nor complete claim coverage has been established. Review warnings identify historical relationship mappings in rows 2227, 686 and 215, and a decisive claim without a corresponding rule entry in row-495. See `choice_study/test_with_history_100_v1/luna_originals_10_v1/execution_summary.json` for the saved diagnostics and usage.

No API calls were made during the earlier implementation phase. Execution began only after the subsequent authorization.

## Scope and selection

Source: the completed frozen test/with_history study, plan `ccc6f3295785f5107b45dad8f122f734cbd46ecec26740843fdcd4e90818c37b`.

The100 original query IDs are sorted numerically, then `random.Random(42).sample(...,10)` freezes ten distinct queries. Selection does not consult target purchases, correctness or explanation quality. The selected order is row-2002, row-196, row-51, row-2227, row-695, row-686, row-495, row-215, row-195, row-2142. Only each case's ORIGINAL with-history explanation is included. The frozen selection includes exact response IDs and hashes.

Jobs/configuration are in `choice_study/test_with_history_100_v1/luna_originals_10_v1/`. There is no counterfactual annotation job and no automatic continuation to the other90 original cases.

## Verified API contract

Verified against official OpenAI documentation on2026-10-25:

- Exact model: [`gpt-6-luna`](https://developers.openai.com/api/docs/models/gpt-6-luna). The model documentation lists high reasoning and structured-output support.
- Official Python SDK `openai==3.37.0`, installed from the documented package; use the [Responses API](https://developers.openai.com/api/reference/python/resources/responses/methods/create).
- Reasoning: `reasoning={"effort":"high"}`; output allowance32768 tokens, including reasoning/output budget. The [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) advises reserving sufficient space for both.
- Strict [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): `text.format={type:"json_schema",name:...,schema:...,strict:true}`. Every object has required fields and `additionalProperties:false`. Candidate IDs, evidence IDs, source fields and annotation enums are constrained to the actual source case.
- `store=False`, `truncation="disabled"`; no temperature, top_p, top_k, beam count, local-predictor generation configuration or fallback model is supplied.
- SDK transport: official API base URL,1200-second timeout, `max_retries=0`. All ten responses returned the requested `gpt-6-luna` model. No model-list or token-count API probe was made.

Install dependencies for the notebook's kernel if necessary:

```bash
.venv/bin/python -m pip install -r requirements-annotation.txt
```

## Credentials

Add the key privately to the existing local `.env`:

```text
OPENAI_API_KEY=<supply privately in the local file>
```

Alternatively set OPENAI_API_KEY in the kernel's environment. Do not put the value in notebook code/output or commit it. `.env` and `.env.*` are already ignored by git; `.env.example` contains only an empty template. The implementation never prints or persists the key. Preparation, previews and summaries do not access credentials or construct an SDK client. Missing credentials return an actionable message before any attempt is reserved.

## Inputs and annotations

The request contains only the original candidates/mapping, original prediction, exact explanation, original global citations, exact predictor-visible facts and factual instructions, evidence/field provenance, existing guide and versioned supplement. Actual targets, correctness, edited outcomes and previous judgments are excluded. Raw source prices remain internal; the annotator evaluates displayed two-decimal prices. Current offers do not establish the actual paid price, and support identifiers do not establish recency.

Claims retain the established guide fields and three parent groups. Influence role and factual status remain separate. Rule objects add exact quote, claim/premise links, explicitness, sufficient specification, scope/conditions, structured type, potential later-test eligibility and its reason. Ambiguous trade-offs and contributing price mentions are not forced into universal rules. Model coverage reports are preserved as self-reports, not human verification.

## Execution and records

`LunaInspection.annotate_first()` can issue only the first frozen request. `annotate_remaining()` requires a first saved result and processes only the other nine jobs. Running the second cell is the user's choice after inspecting the first; no human-review approval label is invented. Neither import nor preparation runs annotations.

Each real response preserves exact raw HTTP bytes, ordered output-text parts (no stripping/repair), requested and returned model, complete request, SDK/effective settings, response ID, usage, parsed claims/rules and structural diagnostics. Records are model-generated and not human-reviewed. Checks cover exact quotes, IDs, fields, mappings, candidate/label validity, rule references, API completion, output truncation and internal eligibility consistency. A false coverage self-report flags known incompleteness; a true self-report still does not establish semantic coverage or factual correctness.

Raw HTTP bodies are in `raw_api/`; canonical detailed records in `records/`; request attempts, state, transport metadata and errors have separate directories. Credential text, if echoed in an error, is explicitly redacted; all other error content is retained. Invalid/incomplete outputs are preserved, not silently corrected or replaced. One attempt per frozen job is automatic; uncertain/failed calls are not retried merely by rerunning a cell. If raw bytes were saved before a processing interruption, rerunning recovers them locally without a new call.

Completed matching records are reused only after checking source hash, job/request signature, prompt/guide/schema/code versions, exact raw text, model identity and settings. A mismatch requires a separate versioned inspection directory. Do not edit raw records to apply review corrections.

## Metrics adapter

A complete structurally traceable record is projected, without changing any claim quotation, factual status, role, direction or mapping, to:

`choice_study/test_with_history_100_v1/annotations/luna-originals-10-v1/<source-response-id>.json`

The existing saved-record metrics loader recognizes this directory, stable call_id, annotation_input and parsed_annotations.claims. Full Luna rule objects remain in `result.parsed_rule_annotations` and the canonical raw record, retaining scope/conditions and eligibility. They are **not** flattened into invented decisive claims or silently translated into the older metric code's narrower rule_specification format. A later rule-aware adapter must consume those original rule objects and edited conditions explicitly. This initial inspection does not run counterfactual rule-consistency/stale-fact analysis or assign edited labels.

The existing `analysis_v1/` outputs remain unchanged. A future metric recalculation with new annotation inputs must use a new versioned analysis directory and explicitly account for only10/100 originals and0/642 edited explanations. Do not present ten annotations as full study coverage or automatically reuse the historical no-annotation report text as a newly covered report.

## Inspectability and tests

The new notebook section is organized into configuration, ten exact source explanations, full request preview, one-call cell, remaining-nine cell, and a read-only summary. The two API cells now contain the authentic execution outputs. The other cells can be run without a key. The refreshed summary displays all ten saved results, factual labels from the model, rule eligibility, validation errors and review warnings. It does not treat a model coverage self-report as verified coverage.

Offline tests cover reproducible selection, original-only scope, allowlisted inputs, actual SDK argument names, strict schema structure, credential-free previews, key-missing/no-client guards, invalid/incomplete/foreign output rejection without quote repair, secret redaction, raw whitespace preservation and frozen-job tampering. Negative test inputs are in-memory fixtures, not saved annotations for the selected cases.

## Exact notebook order and changed files

The new section is cells92–104, after91 preserved cells/outputs. The intended order is configuration93, selected examples95, full prompt97, first API cell99, remaining-nine API cell101, then read-only summary103. All six code cells now have saved outputs, including the actual first-call and remaining-nine execution results. Matching completed results are reused on rerun; the invalid row-2227 result is preserved rather than repeated. Reload `test.ipynb` from disk to view the saved results if the editor still shows an older version.

Added during implementation: `choice_trust/luna_annotations.py`, `choice_trust/luna_schema.py`, `choice_trust/luna_views.py`, `scripts/prepare_luna10.py`, `tests/test_luna_annotations.py`, `requirements-annotation.txt`, `.env.example`, `docs/LUNA_ANNOTATION_PROMPT_V1.md`, and this workflow document. The notebook section was appended after the existing cells and has now been executed. The prompt, guide, schema, settings and frozen jobs remain unchanged. Ten offline tests passed; post-execution verification checked1658 prior source files unchanged. Nine structurally traceable adapter records were exported; the invalid annotation remains in its canonical/raw directories and was excluded from adapter export. This stage covers ten saved originals out of100 (nine structurally traceable) and zero of642 edited explanations.
