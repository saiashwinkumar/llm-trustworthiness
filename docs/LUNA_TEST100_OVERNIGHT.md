# Luna annotation of the completed test100 run

Authorized scope: the existing completed `test/with_history` study
`ccc6f3295785f5107b45dad8f122f734cbd46ecec26740843fdcd4e90818c37b`.
The actual manifest and response inventory contain 100 originals and 642 edits,
742 total, across exactly the selected 100 queries. No additional test queries,
development/validation cases or without-history responses are scheduled.

The annotation manifest is
`choice_study/test_with_history_100_v1/luna_all_742_v1/manifest.json`, ID
`9251cf0e682aeee0852e3ce26dc07e262d921e47507a52cc6471d022ef6a0e6c`.
It links query/household IDs, original/edited response IDs, intervention family,
edit ID, response hash, guide/prompt/schema/configuration versions, exact request
and job signatures. All 742 requests and their source linkage were inspected
before launch. Hidden purchase labels and correctness are absent.

## Method and execution

The ten pilot annotations are reused with verified response hashes, exact request
content, guide, schema, model and settings. Their raw records remain unchanged;
the batch contains links, avoiding duplicate metrics records or paid calls.
The row-2227 quotation failure remains a failure rather than successful coverage.

Original requests use the exact original pilot prompt and schema, including
`gpt-6-luna`, high reasoning, 32768 output tokens, `store=false` and disabled
input truncation. SDK3.37.0 has automatic retries disabled. Four independent
requests run concurrently. The first four pending originals are normal saved
jobs used for the live execution/linkage/parsing check, with no extra diagnostic
calls. After that check passes, the other originals run before the edited phase.

Edited requests use the documented extension in
[LUNA_EDITED_ANNOTATION_V1.md](LUNA_EDITED_ANNOTATION_V1.md). Exact edited facts,
mapping, explanation, prediction and citations are the current scenario. Original
facts/mapping and the exact intervention patch are separate comparison context;
original predictions, explanations, correctness and annotations are excluded.
Every edited claim retains its original claim fields plus temporal scope,
stale status, original evidence/fields, patch fields and a justification. A
contradiction alone does not establish staleness, and an explicit reference to
the original scenario is distinguished from an old fact asserted as current.

Three edited predictor outputs were already truncated:

- `row-1871__with_history__PRODUCT_ORDER_CONTROL`
- `row-1973__with_history__SUPPORT_PURCHASE`
- `row-1969__with_history__SUPPORT_PURCHASE`

Their exact unescaped literal explanation prefixes are annotated with raw
character offsets and a truncation flag. The source JSON is never repaired;
missing endings, predictions and citations remain unavailable. Prefix annotations
are reported separately and excluded from complete-explanation success/metrics
exports. This retains all existing explanations without regenerating predictions.

An exclusive OS lock prevents simultaneous runners for the same manifest.
Each job has separate atomic request-attempt, raw HTTP response, canonical result,
transport and state files. No concurrent shared JSONL append is used. Raw bytes
are durable before parsing. Quote spans, candidate IDs, evidence references,
source fields, schema and API completion are checked without correcting output.

Temporary HTTP failures have at most four total attempts per job, with exponential
backoff/jitter and a shared rate-limit delay honoring Retry-After. Server delays
over900 seconds defer the job and stop new scheduling rather than retrying early.
Authentication, permission, missing-model and billing/quota errors stop new
scheduling. Existing in-flight calls can finish and save normally. Connection
errors/timeouts are uncertain and never automatically resent. Saved raw responses
are recovered locally on resume. Because the preserved setting is `store=false`,
a request lost before any response ID/body is available cannot be retrieved by
client request ID; preserve the uncertain state and use its request identifiers
for investigation rather than send another paid request automatically.

Failed/invalid results remain preserved. Resuming reuses matching completed
records and processes pending work or bounded, eligible temporary failures; it
does not repair labels or automatically repeat uncertain/terminal failures.
The run can finish **with issues** while accounting for every job. Successful
complete-explanation coverage is a separate count, never the saved-file count.

## EC2 and credentials

Verified with refreshed AWS discovery and EC2 instance metadata on2026-10-25:
`i-0fca8c4016c36b737`, `m7i.xlarge`, `ubuntu@54.252.237.68`.

Root: `/home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1`.
Existing Python: `/home/ubuntu/customer-choice-trust/.venv/bin/python`.
Screen session: `choice-luna-annotations-100`.
Output directory: `choice_study/test_with_history_100_v1/luna_all_742_v1/`.
Log: that directory's `runner.log`.

The credential is loaded from OPENAI_API_KEY or a private `.env.luna`/`.env` file,
never command-line arguments or notebook/log output. The existing ignored local
key was transferred through encrypted SSH stdin to `.env.luna` with mode0600.
Archives explicitly exclude credential paths. For future private key entry, run
`scripts/set_luna_key.py` interactively on EC2. Do not paste keys into chat.

Deployment verifies every bundled hash and refuses to overwrite any differing
existing file. The existing model-server process and experiment records remain
untouched. Installation constrains every previously installed package to its
existing version; dependency verification is saved beside the run. No Qwen
server or prediction experiment is launched. EC2 is never stopped automatically.

## Monitoring and resuming

Connect, then define these paths in the EC2 shell:

```bash
ssh -i ~/Downloads/llm-experiment.pem ubuntu@54.252.237.68
cd /home/ubuntu/customer-choice-trust/continuations/test_with_history_100_v1
LUNA_PY=/home/ubuntu/customer-choice-trust/.venv/bin/python
LUNA_OUT=choice_study/test_with_history_100_v1/luna_all_742_v1
```

Check the detached session:

```bash
screen -ls
```

Latest log output:

```bash
tail -n 30 "$LUNA_OUT/runner.log"
```

Current counts, coverage by family, failures, usage, throughput and updated ETA:

```bash
"$LUNA_PY" -B scripts/run_luna100.py status
```

Resume after interruption (the launcher refuses a duplicate live session/runner):

```bash
"$LUNA_PY" -B scripts/launch_luna100_existing_aws.py
```

Generate a summary from saved results only, with no API or predictor calls:

```bash
"$LUNA_PY" -B scripts/run_luna100.py summary
cat "$LUNA_OUT/completion_summary.md"
```

The runner also writes `progress.json` after ordinary job completions and writes
`completion_summary.json`/`.md` when it exits. `live_check.json`,
`launch_state.json`, attempts, states and the dedicated log retain execution
evidence. Status separates original/edited families, reused/new responses,
pending/running/failed outcomes, structural validity and complete-source coverage.
ETA is an observed-throughput estimate, initially based on a small sample.

## Metrics compatibility and interpretation

Valid complete-source new annotations export into
`annotations/luna-all-test100-v1/<response-id>.json`. The reused pilot records
remain in `annotations/luna-originals-10-v1/`, with no duplicate export. Existing
claim/influence/factuality loaders can join by response ID and exact facts.
Edited claims retain the full comparison extension; explicit stale_status is
projected into the older boolean stale_fact field only when assessable.
Unassessable staleness remains absent, not false. The complete-stale-coverage flag
requires all claims assessed. Full rule objects remain in
`result.parsed_rule_annotations` and canonical records for later rule-aware
comparison; they are not forced into the legacy narrower rule_specification or
invented rule-consistency labels. A subsequent rule-aware analysis must consume
these preserved scope/conditions/premise links explicitly.

All outputs are automated Luna annotations, not human-reviewed or validated for
semantic correctness. No overall faithfulness score, new prediction, HTML
dashboard or metric recalculation is produced by this stage. Historical analysis
outputs and notebook cells are preserved.
