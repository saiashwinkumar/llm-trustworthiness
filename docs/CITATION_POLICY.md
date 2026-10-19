# Citation policy change — 18 October 2026

Policy `available-evidence-unlimited-v1` removes the three-ID cap. Any number of
available, distinct IDs can be cited. The response JSON schema remains unchanged:
`evidence_ids`, `explanation`, `counterfactual`, including the existing nested claim
schema. The legacy client retains its own existing nested claim schema.

Checks are separate: JSON readability, required fields, field types, unavailable IDs,
and duplicated IDs. JSON inside surrounding prose/fences can still be extracted by
the historical reader, with a specific surrounding-text diagnostic. No JSON repair,
ID trimming, invented citations, or factual judgment is performed. Empty supporting
citations are a permissible response but provide no set for cited-evidence tests.
Recorded truncation prevents eligibility. Explicit-claim admissibility remains separate.

Future framework prompts are versioned `common-evidence-v4-unlimited-citations`
(previously `common-evidence-v3`). The legacy prompt is now
`yogurt-evidence-v2-unlimited-citations` (previously `yogurt-evidence-v1`). New manifests
and assessments record the citation-policy version; framework explanation records
also record their prompt version. The notebook already allows unlimited citations;
its original notebook and saved outputs remain unchanged.

The offline report is `reports/citation_policy_v1/report.md`. Its companion files are:

- `assessments.jsonl`: source file/line/hash, original complete record and previous
  assessment, prompt provenance, and separate new checks.
- `policy.json`: versioned rules and eligibility definition.
- `manifest.json`: source hashes, assessor hashes, future prompt version, and zero
  model calls/new measurements.
- `summary.json`: response-attempt counts by source, split and condition.

Canonical real-model responses are counted once; synthetic fixtures and imported or
backup duplicates are excluded. Notebook attempts on the same case remain separate
and are distinguished by line number and prompt hash. Notebook finish metadata was
not recorded. Historical legacy explanation prompts were not saved in those response
records; no reconstructed prompt is presented as an original prompt.

Reproduce into a fresh destination without inference:

```bash
.venv/bin/python -B scripts/reassess_citations.py --out reports/citation_policy_v1_repeat
```

The command refuses an existing destination. Existing source records and skipped
interventions are never rewritten. Newly eligible means that evidence interventions
could now be planned, not that they have been measured or that claims are faithful.

Future inference must use new output/control folders because the prompt and code
identity changed. When separately requested, the fresh smoke command is:

```bash
caffeinate -i .venv/bin/python -B -u scripts/run_cpu_real_v2.py smoke \
  --out outputs_cpu_real_v4 --control execution_cpu_real_v4
```

No new smoke, validation or test run was started for this policy change. Do not append
v4 responses to v3 folders or edit their manifests to bypass compatibility checks.
