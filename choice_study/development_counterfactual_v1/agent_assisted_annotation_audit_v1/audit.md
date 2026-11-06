# Six-record annotation quality audit

**Review: agent-assisted. Proposed corrections require user review. No human review is claimed.**

No new predictor or annotator calls were made. Raw annotations, predictor outputs, inputs, guide and pilot ledger are unchanged; hashes are recorded in `verification.json`.

## Separate quality axes

- JSON/schema shape: 6/6 parse with the expected fields/enums. This does not establish annotation quality.
- Exact quotations: 4/6 records pass; two quotes rewrite the explanation.
- ID/field existence: 6/6 reference existing names. Evidence-to-field coverage: 4/6 pass; two map current price IDs to historical fields.
- Original predictor citation lists: all six contain available IDs and match the exact saved predictor response. They are global lists, not claim-level attributions. A reviewer may map available H records omitted by the predictor; doing so does not prove that history influenced the model.
- Combined structural/traceability checks: 2/6 pass. These checks do not judge semantic truth.
- Factual-label correctness: two records incorrectly label a false/unsupported compound claim as supported; one has a correct supported numeric statement within its narrow scope; three use unclear for separable availability/descriptive assertions and need scoped correction. These record-level categories are not an annotation accuracy estimate.
- Material claim coverage: 6/6 need expansion or splitting. Five omit material text; the sixth quotes the entire explanation as one mixed claim, so it still lacks atomic coverage. Neither structural pass is ready for unchecked use.

## Compact audit table

| Record | Traceability errors | Incorrect/inadequate semantic labels | Missing claims | Proposed corrections | Questions for user |
|---|---|---|---|---|---|
| row-1289__no_history__ORIGINAL | Nonexact quote | False minimum labeled supported; price role missed | Explicit lowest-price rule | B is cheapest; keep decisive price claim toward D | Contextual direction D? |
| row-1289__with_history__HISTORICAL_PRICE_ASSOCIATION | P IDs cannot cover H fields | Uncertainty bundled; major facts unjudged | False D minimum; nonexistent B purchase; tentative D reason | Map chronology to instruction/history; B count=0; price premise false, influence retained | Tentative contributing role despite caveat? |
| row-1289__with_history__ORIGINAL | No structural failure; excessive fields | Diversity mislabeled price relationship/unclear | H5 recency; false missing prices; A-price reason | Narrow H fields; split supported facts, unsupported recency, cross-group A reason | Closeness threshold; contributing vs decisive? |
| row-2379__no_history__ORIGINAL | Nonexact quote | Price-list role unclear; supported numbers are correct | B/C comparison; advertising/popularity argument | Exact price quote descriptive; popularity unsupported but possible contributing B reason | Rhetorical price role; tentative ad role? |
| row-2379__with_history__HISTORICAL_PRICE_ASSOCIATION | Passes exact-quote/reference checks | Unknown paid-price match labeled supported; compound role | Atomic claims absent despite full-text quote | Split unknown target paid price, correct D/history facts, claimed D price-match rule | Decisive vs contributing; occasion referent? |
| row-2379__with_history__ORIGINAL | P IDs cannot cover H fields | Generic motive caveat assigned history | All-four-products purchase assertion; offer/paid distinction | Remove invented history mapping; split offer values from unsupported purchase assertion | Does purchase included mean bought or offered? |

## Requested factual checks

- Household 53 current offers are A $8.10, B $4.90, C $7.90, D $5.30. B is cheapest. Both original no-history and historical-price-edited explanations falsely call D cheapest. Correct labels for the factual minimum claims are contradicted.
- The original no-history explanation explicitly says **“the choice is based on the lowest price.”** Proposed role: decisive; factual status for that influence-only assertion: not_applicable. Its context favors D even though its price premise is false. Do not turn a false premise into “no claimed price influence.”
- Household 53 support purchases are A,C,C,D,A: A=2, B=0, C=2, D=1. The historical-price edit does not change them. Its all-four-brands claim is contradicted. Household 99 purchases are D,D,B,A,D: D=3, A=1, B=1, C=0. No omitted/duplicated support records are assumed.
- H5 is not a timestamp. Calling it most recent is unsupported, not directly disproved. The statement that recency is not supplied is supported by the explicit unordered-history instruction.
- In household 99 historical-price-edited input, P_D is a **candidate offer** of $10.30. H1 has a historical D offer at $10.30. Neither supplies the hidden current purchase or actual paid price. The asserted current paid-price match is unsupported. Proposed price-match deciding rationale still records claimed influence toward D.
- Preference/popularity is unavailable. NOT_ADVERTISED is a known flag, not evidence that a product is popular or preferred. A caveat about unknown preference is not an explicit assertion that price or advertising was irrelevant.

## Proposed layer and supporting values

`reviewed_layer.json` contains exact quotations and occurrence offsets, proposed guide labels, source values (untouched and displayed canonical prices), mapped IDs, required fields, prompt constraints, reasons, missing information and unresolved questions for every proposed correction. `source_snapshots.json` preserves the six exact factual inputs, explanations, original citations, raw annotations and guide snapshots. Proposed quotes/references pass mechanical checks only; semantic judgments remain agent-assisted proposals.

## Recommendation for the 100-case analysis

**Unchecked automatic annotations are not suitable in their current form.** Automatic JSON/traceability checks should be a gate, followed by claim-coverage and semantic review that explicitly audits deciding rules, false factual premises, chronology and unavailable outcomes. Preserve separate raw and reviewed layers and adjudicate the listed ambiguities before accepting labels. These six diagnostics and agent-assisted corrections do not validate the annotator or establish reliability on 100 cases. No larger experiment was launched.
