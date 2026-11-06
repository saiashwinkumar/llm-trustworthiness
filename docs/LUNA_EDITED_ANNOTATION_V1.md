# Luna edited-response extension

Prompt version: luna-edited-claims-rules-stale-v1
Schema version: luna-edited-claims-rules-stale-v1

This extension applies only to edited explanations. Keep the original guide's claim definitions, concept groups, roles, factual statuses and decision-rule distinctions. The original-only supplement is supplied as the baseline definition; its instructions to exclude edited context and avoid stale labels are superseded only for this edited-response task. No actual purchase, correctness label, other explanation or previous annotation is supplied.

CURRENT_EDITED_SCENARIO contains the exact facts, mapping, prediction, explanation and citations for the explanation you annotate. ORIGINAL_COMPARISON_CONTEXT contains only original facts/mapping and the exact intervention patch, never the original prediction, explanation, outcome or annotation. Evaluate current assertions against CURRENT_EDITED_SCENARIO. Original-only values are comparison evidence, not currently supplied facts. Raw numeric patch values are retained for provenance; evaluate their displayed two-decimal dollar representations. No raw floating-point difference breaks a displayed tie. Candidate codes may have changed: follow product identities and the supplied mappings. Unordered support IDs do not imply recency.

Extract claims and rules using the unchanged baseline definitions. Each claim additionally has comparison_assessment:

- temporal_scope: current_edited, explicit_original_reference, general_or_influence, or unclear.
- stale_status: stale, not_stale, unassessable, or not_applicable.
- original_evidence_ids and original_source_fields refer only to ORIGINAL_COMPARISON_CONTEXT. Core mapped_evidence_ids and source_fields refer only to CURRENT_EDITED_SCENARIO. Do not move an original-only citation into the current evidence mapping.
- changed_patch_fields link a possible stale claim to actual patch fields (including a presentation/mapping change if relevant).
- reason must state the relevant old/current displayed values, identity, availability, or the missing information. Use exact source values; do not invent an asserted value.

A stale claim incorrectly treats a changed, removed or remapped original fact as currently applicable. Establish both the old fact and the relevant edit. A contradiction unrelated to the patch is not automatically stale. An explicit, accurate statement about the original scenario is not stale. An old offer removed from the current input does not establish the unknown current offer or actual paid price; an assertion that the removed offer is still supplied can be stale while factually unsupported rather than contradicted. A false statement can still claim decisive influence. Merely changing a rationale is not stale. For claims where staleness cannot be established, use unassessable rather than inventing a negative label.

Use factual_status for the assertion in its stated temporal scope. An accurate explicit reference to original facts may be supported using comparison evidence; explain that scope. Do not treat historical offers within the edited household history as the separate pre-edit scenario. Pure influence claims remain not_applicable for factual truth and usually for staleness. Preserve all claim quotations exactly and separately record claimed influence and factual correctness.

Some source predictor responses were already truncated. If source_explanation.status is truncated_literal_prefix, the supplied explanation is an exact literal substring of the saved raw response, not a repaired JSON object or a complete explanation. Annotate only that prefix. The original prediction and citations are unavailable, not fabricated. State this limitation in coverage.notes. Coverage refers only to the supplied prefix, never the missing ending or full response.

Do not infer a new deciding rule from the intervention or the original context. Annotate only rules actually stated in this edited explanation. Rule eligibility describes potential later testing, not consistency with any other response. Do not assign a single faithfulness score.

Return the supplied strict schema with the comparison extension for every claim. Do not rewrite quotations, fill absent source outputs, or impose a citation-count limit. These are automated annotations, not human review.
