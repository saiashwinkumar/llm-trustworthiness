# Explanation claim annotation guide

Guide version: explanation-claims-v1

## Objective and unit

Record what the explanation **claims influenced the prediction** and distinguish those claims from descriptions of facts. Annotation does not establish what actually influenced the model. Do not assign a faithfulness score or declare an explanation faithful. The hidden target purchase and intervention results are excluded from annotation.

Read the entire explanation before separating claims. Use the shortest exact substring that retains the subject, negation, comparison, and qualification needed to interpret a claim. Split separable factual assertions and influence assertions, even within a sentence. Overlapping quotes are allowed when a sentence connects several assertions. Preserve contextual qualifiers such as “but” or “does not directly indicate.” Resolve pronouns from the complete explanation without rewriting their quotes. Capture material claims that are false or unsupported as well as claims that are supported. Do not force an importance ranking.

## Parent information groups

Use only CURRENT_PRICES, CURRENT_ADVERTISING, and HOUSEHOLD_HISTORY. A claim may involve zero, one, or several groups. Brand identity alone, a generic assertion of uncertainty, or an ungrounded motive can have no group; if a motive is explicitly linked to price or advertising, record those groups while marking the inference unsupported.

Both support purchase frequency and historical purchase–offer relationships belong to HOUSEHOLD_HISTORY. They are relationship types within that group, not independent parent concepts. A claim connecting a current price with a historical pattern requires both CURRENT_PRICES and HOUSEHOLD_HISTORY. This grouping is a source-field partition and makes no assertion of statistical independence.

Current compact evidence uses P_<candidate> for prices, F_<candidate> for advertising, and H1, H2, … for complete linked support purchases and offers. Historical claims require purchase labels plus their corresponding historical prices or flags. Keep separate support records even when values match. A citation to H1 is not evidence that all fields within H1 influenced the answer; select specific source fields for the claim.

For an archived v1 response, retain its exact original input, IDs, and numeric policy. Map current_prices to CURRENT_PRICES, current_advertising to CURRENT_ADVERTISING, and both support_purchases and historical_offers to HOUSEHOLD_HISTORY. Do not rerender old inputs with new dollar rounding. For compact v2, evaluate model-visible prices using the supplied two-decimal representation (ROUND_HALF_UP); do not use invisible raw differences to contradict displayed ties.

## Required claim fields

Return one JSON object with a `claims` array. Each element must have all the fields below. Use C1, C2, … in explanation order. Use empty lists when there is no applicable group, direction, evidence, or source reference; do not invent missing evidence.

| Field | Meaning |
| --- | --- |
| claim_id | Distinct identifier within this annotation. |
| exact_quote | Exact, contiguous substring of the generated explanation; no paraphrase or ellipsis. |
| concept_groups | List containing zero or more of the three parent group labels. Include every group required to interpret the claim. |
| relationship_type | One of the relationship labels below; use other_or_unclear when none fits. |
| claimed_role | One role from the definitions below. |
| direction | Object with `favors` and `disfavors` lists of available candidate IDs. Record only stated direction, rather than treating the subject of a description as favored. |
| mapped_evidence_ids | IDs the annotator maps to support **or evaluate** this claim, including evidence that contradicts it. No citation-count limit. |
| source_fields | Exact supplied field references needed to evaluate the claim, such as current.prices.A or H1.purchased and H1.prices.B. |
| factual_status | One status from the definitions below. |
| annotation_note | Brief justification, including important ambiguity, context, contradictory evidence, or missing information. |

Relationship labels: current_price_comparison; current_advertising; support_purchase_frequency; historical_price_purchase_relationship; historical_advertising_purchase_relationship; brand_persistence_under_different_offers; other_or_unclear. Historical brand persistence requires actual purchases of that brand under different offers; repeated identical offers do not establish it.

## Role and direction rules

- **decisive**: explicit deciding rule or dominant reason, such as a stated reason that determines the final choice. Merely calling a product cheapest does not establish a decisive role.
- **contributing**: explicitly presented as a reason favoring or disfavoring an option without being stated as dominant. Retain contributing evidence even when it favors an option the model did not select.
- **descriptive_only**: reports a fact or relationship without claiming it affected the choice. Mentioning a fact differs from claiming influence.
- **explicitly_irrelevant**: explicitly denies that a fact or group affected the prediction. A caveat such as “does not directly indicate the current purchase” is weaker than a denial of influence; keep that ambiguity as unclear unless the context resolves it.
- **unclear**: relevance to the prediction is ambiguous, mixed, or cannot be determined from the words used.

Distinguish a group that was not mentioned from one explicitly called irrelevant. Describing unavailable information does not establish that it had no influence. Do not infer direction from a correct numerical comparison alone. If an utterance contains separable roles, split it; otherwise use unclear and explain the conflict.

## Factual status rules

- **supported**: supplied information supports the factual assertion, within its stated scope.
- **contradicted**: supplied information directly conflicts with the assertion.
- **unsupported_by_supplied_information**: required information is absent or an inference goes beyond what the data establish. Unsupported preference or motive claims are not automatically proven false. Current offers do not reveal the hidden target purchase, and a claim about the entire dataset requires more than one query and its support purchases.
- **not_applicable**: no externally checkable factual assertion, for example a pure assertion about what influenced this model's decision. Such an influence assertion cannot be verified merely because accompanying prices are correct.
- **unclear**: wording or mixed assertions prevent a defensible single factual label. Split claims first when possible.

An incorrect prediction does not automatically make every factual claim false. Price and advertising associations do not establish actual customer motives or stable preferences. Do not use the target purchase or any intervention outcome to judge these claims.

## Citations, provenance, and review

Preserve the model's original global evidence_ids list separately from mapped_evidence_ids. An annotator may map an available observation that the model omitted. A global list does not explicitly attach every ID to every claim. Annotator mappings are reviewable proposals, not reconstructed model attention or causal evidence.

Check exact quotes, available IDs, candidate IDs, group labels, and existing source-field references. References should be covered by mapped evidence; historical relationships need both purchase and linked offer fields. These checks establish structure and traceability only, not semantic correctness, completeness, factual accuracy, or faithfulness. Keep invalid quotes, references and malformed raw responses visible; never silently repair them.

Summarize each parent group using all of its annotated roles: decisive/contributing → claimed influence; descriptive_only → description only; explicitly_irrelevant → explicitly denied influence; unclear → unclear. If several signals occur, display all and flag the mixture for review. “Not mentioned” means no claim was assigned to that group in these provisional annotations, not proof of no influence. When parsing fails or generation is truncated, coverage is unknown.

Before accepting annotations, manually check claim coverage, exact quotes, role versus description, sufficient mappings, preference inferences, and any required corrections. All outputs are provisional LLM-assisted annotations requiring review.
