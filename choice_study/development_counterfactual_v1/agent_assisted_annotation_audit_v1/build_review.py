"""Rebuild case-specific agent-assisted review proposals from six saved records.

No predictor/annotator calls. Proposals are authored judgments, not a general
annotation algorithm, accepted gold labels, or evidence of human review.
"""
from pathlib import Path
from collections import Counter
from hashlib import sha256
import json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from choice_trust.observations import canonical_price
from choice_trust.explanation_annotation import validate_annotations, FIELDS

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
PILOT=OUT.parent
manifest=json.loads((PILOT/'manifest.json').read_text())
entries={e['call_id']:e for e in manifest['entries']}
files=sorted((PILOT/'annotations').glob('*.json'))
assert len(files)==6
protected={str(p.relative_to(ROOT)):sha256(p.read_bytes()).hexdigest() for p in PILOT.rglob('*') if p.is_file() and OUT not in p.parents}
protected['docs/EXPLANATION_ANNOTATION_GUIDE.md']=sha256((ROOT/'docs/EXPLANATION_ANNOTATION_GUIDE.md').read_bytes()).hexdigest()
records={p.stem:json.loads(p.read_text())['result'] for p in files}
review={}
CP='CURRENT_PRICES';CA='CURRENT_ADVERTISING';HH='HOUSEHOLD_HISTORY'
PIDS=['P_'+c for c in 'ABCD'];PFS=['current.prices.'+c for c in 'ABCD']
FIDS=['F_'+c for c in 'ABCD'];FFS=['current.advertised.'+c for c in 'ABCD']
HIDS=['H'+str(i) for i in range(1,6)];HFS=[h+'.purchased' for h in HIDS]


def begin(cid, trace, semantics, missing, questions, factual_assessment):
 global current
 current=cid
 saved=records[cid];entry=entries[cid];inp=saved['annotation_input']
 response=json.loads((PILOT/'responses'/f'{cid}.json').read_text())['response']
 assert inp['explanation']==response['parsed_result']['explanation']
 assert inp['model_citations']==response['parsed_result']['evidence_ids']
 assert inp['predicted_candidate']==response['parsed_result']['prediction']
 assert response['messages']==entry['messages']
 assert inp['observations']['text']==entry['observations']['text']
 assert inp['observations']['observations']==entry['observations']['observations']
 assert saved['annotation_guide']==manifest['annotation_guide']
 assert saved['annotation_guide']['text']==(ROOT/'docs/EXPLANATION_ANNOTATION_GUIDE.md').read_text()
 prov=inp['provenance'];claims=saved['parsed_annotations']['claims']
 raw_parsed,raw_checks=validate_annotations(saved['raw_annotation_response'],explanation=inp['explanation'],
    candidates=inp['candidates'],provenance=prov,truncated=saved['diagnostics']['generation_truncated'])
 assert raw_parsed==saved['parsed_annotations'] and raw_checks==saved['diagnostics']
 visible=set(prov);fields={f for p in prov.values() for f in p['source_fields']}
 for c in claims:
  assert set(c['mapped_evidence_ids'])<=visible and set(c['source_fields'])<=fields
 assert set(inp['model_citations'])<=visible
 source=entry['observations']['audit']['source_values']
 prices={c:canonical_price(source['current.prices.'+c]) for c in 'ABCD'}
 counts={c:sum(source[f]==c for f in HFS) for c in 'ABCD'} if all(f in source for f in HFS) else None
 review[cid]={
  'review_label':'agent-assisted; proposed corrections pending user review; no human review claimed',
  'annotation_file':str((PILOT/'annotations'/f'{cid}.json').relative_to(ROOT)),
  'source_response_file':str((PILOT/'responses'/f'{cid}.json').relative_to(ROOT)),
  'original_global_evidence_ids':inp['model_citations'],
  'audit_axes':{'json_parse_ok':saved['diagnostics']['parse_ok'],
    'schema_fields_and_enums_ok':not saved['diagnostics']['schema_issues'] and all(not any('field' in x.lower() and 'source' not in x.lower() or 'Invalid' in x for x in c['issues']) for c in saved['diagnostics']['claim_checks']),
    'exact_quotes_ok':all(c['exact_quote'] in inp['explanation'] for c in claims),
    'all_ids_and_fields_exist':True,
    'mapped_ids_cover_fields':all(set(c['source_fields'])<={f for eid in c['mapped_evidence_ids'] for f in prov[eid]['source_fields']} for c in claims),
    'original_combined_structure_traceability_ok':saved['diagnostics']['structure_and_traceability_ok'],
    'factual_label_assessment':factual_assessment,
    'important_claim_coverage':'incomplete',
    'claimed_influence_and_description_assessment':'corrections required'},
  'traceability_errors':trace,'incorrect_or_inadequate_semantic_labels':semantics,
  'missing_material_claims':missing,'unresolved_questions_for_user':questions,
  'factual_context':{'current_prices_dollars_2dp':prices,'current_cheapest_candidates':[c for c in prices if prices[c]==min(prices.values(),key=lambda x:float(x))],
                     'support_purchase_counts':counts,'history_order':'NOT_PROVIDED; explicitly unordered',
                     'target_purchase':'NOT_PROVIDED','target_paid_price':'NOT_PROVIDED'},
  'proposed_claims':[]}


def C(quote,groups,rel,role,status,ids=(),fields=(),reason='',favors=(),disfavors=(),origin='missing',scope='factual_assertion',prompt=(),missing=()):
 record=review[current];entry=entries[current];inp=records[current]['annotation_input'];text=inp['explanation']
 assert quote in text,(current,quote)
 prov=inp['provenance'];assert set(ids)<=set(prov)
 covered={f for i in ids for f in prov[i]['source_fields']};assert set(fields)<=covered
 source=entry['observations']['audit']['source_values'];values=[]
 for f in fields:
  raw=source[f]
  visible=('NOT_PROVIDED' if raw is None else '$'+canonical_price(raw)) if '.prices.' in f else ('ADVERTISED' if raw else 'NOT_ADVERTISED') if '.advertised.' in f and raw is not None else raw
  values.append({'source_field':f,'untouched_source_value':raw,'model_visible_value':visible})
 prompt_content='\n'.join(m['content'] for m in entry['messages'])
 for p in prompt:assert p in prompt_content,(current,p)
 start=0;occ=[]
 while True:
  index=text.find(quote,start)
  if index<0:break
  occ.append({'start':index,'end':index+len(quote)});start=index+1
 claim={'claim_id':'C'+str(len(record['proposed_claims'])+1),'exact_quote':quote,'concept_groups':groups,
        'relationship_type':rel,'claimed_role':role,'direction':{'favors':list(favors),'disfavors':list(disfavors)},
        'mapped_evidence_ids':list(ids),'source_fields':list(fields),'factual_status':status,'annotation_note':reason,
        'correction_reason':reason,'original_claim_link':'C1' if origin=='replacement' else None,
        'proposal_action':'replace_or_split_original_C1' if origin=='replacement' else 'add_missing_claim',
        'claim_scope':scope,'supporting_source_values':values,'exact_quote_occurrences':occ,
        'supporting_prompt_quotes':list(prompt),'unavailable_information':list(missing)}
 record['proposed_claims'].append(claim)

cid='row-1289__no_history__ORIGINAL'
begin(cid,['C1 quote changes the original wording/capitalization; not an exact substring.'],
 ['C1 supported is incorrect: D is not cheapest and the stated order is wrong.','C1 unclear overlooks the separate explicit price deciding rule; descriptive price assertions and claimed influence must be split.'],
 ['Explicit lowest-price deciding rule and its direction toward predicted D.','Separate supported numerical prices, false minimum/order, unknown motives and unordered-record premise.'],
 ['Confirm D as contextual direction of the stated cheapest rule, even though B is the actual cheapest.','The no-history unordered-record sentence is a procedural premise, not evidence that support records were provided.'],
 'incorrect: the only returned supported label covers a false minimum/order assertion')
C('The evidence shows that the cheapest product is D (Yoplait at $5.30), followed by C (Weight at $7.90), then B (Hiland at $4.90), and finally A (Dannon at $8.10).',[CP],'current_price_comparison','descriptive_only','contradicted',PIDS,PFS,'Exact replacement; visible order is B $4.90 < D $5.30 < C $7.90 < A $8.10. Correct component prices do not make the cheapest/order assertion true.',origin='replacement')
for quote,c in [('D (Yoplait at $5.30)','D'),('C (Weight at $7.90)','C'),('B (Hiland at $4.90)','B'),('A (Dannon at $8.10)','A')]:
 C(quote,[CP],'other_or_unclear','descriptive_only','supported',['P_'+c],['current.prices.'+c],'Component candidate-price description is correct; assess it separately from the false price ordering.')
C('Since the customer motive is unknown',[],'other_or_unclear','descriptive_only','supported',reason='Prompt explicitly withholds motives; this does not establish customer price preference.',prompt=['Customer motives are unknown.'])
C('the choice is based on the lowest price.',[CP],'current_price_comparison','decisive','not_applicable',PIDS,PFS,'Explicit claimed deciding rule. Factual falsity of the preceding minimum claim does not erase claimed price influence. D is favored in the explanation context and final prediction; this is not proof of actual model influence.',favors=['D'],scope='claimed_influence_only')
C('The support records are unordered',[],'other_or_unclear','descriptive_only','supported',reason='Matches the procedural prompt instruction. Household history is NOT_PROVIDED here; do not invent historical records or a frequency claim.',prompt=['Support records are unordered separate purchases.','Household history: NOT_PROVIDED'])
C('so the cheapest product is the most likely candidate.',[CP],'current_price_comparison','decisive','not_applicable',PIDS,PFS,'Reiterates the claimed lowest-price selection rationale; D is its contextual referent. This influence assertion is distinct from a verified customer-choice rule.',favors=['D'],scope='claimed_influence_only')

cid='row-1289__with_history__ORIGINAL'
begin(cid,[],['C1 uses historical_price_purchase_relationship for a purchase-diversity statement.','C1 unclear factual/role labels conflate descriptive support purchases with unknown current outcome.','All 45 historical fields are overbroad for the single quoted claim.'],
 ['Unsupported most-recent H5 chronology (twice).','False claim that current occasion prices are not supplied (twice).','Supported H5 A/$6.30 and H4 D/$4.20 record facts.','Current-price list; final historical/current A-price comparison favoring A.'],
 ['Closeness of $6.30 and $8.10 has no declared threshold; proposed unclear.','Is the historical/current A-price reason contributing or decisive? Contributing is proposed because no dominant rule is explicit.','Historical bought-at wording is interpreted as the linked supplied offer context, not verified receipt paid price.'],
 'inadequate: unclear unnecessarily bundles supported purchase diversity and unavailable target outcome')
C("The customer's previous purchases (H1, H2, H3, H4, H5) show that they have bought multiple products",[HH],'other_or_unclear','descriptive_only','supported',HIDS,HFS,'Supplied purchases are A,C,C,D,A: A=2, C=2, D=1, B=0. Diversity is supported; this is not a price-purchase relationship or a stated influence.',origin='replacement')
C('but the specific purchase on this occasion is not explicitly stated.',[],'other_or_unclear','descriptive_only','supported',reason='Hidden current purchase is absent. This availability assertion is separate from the history description.',origin='replacement',missing=['actual target purchase'])
C('The most recent purchase (H5)',[HH],'other_or_unclear','descriptive_only','unsupported_by_supplied_information',['H5'],[], 'H5 is an identifier, not chronology. Unordered history neither proves nor disproves that H5 happened last.',prompt=['Support records are unordered separate purchases.'],missing=['historical chronology'])
C('the most recent purchase (H5)',[HH],'other_or_unclear','descriptive_only','unsupported_by_supplied_information',['H5'],[], 'Second chronology assertion; no timestamps or ordering are supplied.',prompt=['Support records are unordered separate purchases.'],missing=['historical chronology'])
C('the customer bought product A at $6.30',[HH],'historical_price_purchase_relationship','descriptive_only','supported',['H5'],['H5.purchased','H5.prices.A'],'H5 links purchased A with associated A offer $6.30. This does not supply the hidden current purchase or establish recency.')
C("The current purchase occasion's prices are not explicitly stated",[CP],'other_or_unclear','descriptive_only','contradicted',PIDS,PFS,'Current occasion prices are supplied under CURRENT_PRICES, including A $8.10 and B $4.90.')
C("Since the current purchase occasion's prices are not explicitly stated",[CP],'other_or_unclear','unclear','contradicted',PIDS,PFS,'Repeated false availability premise, used to justify uncertainty; do not reinterpret it as current prices being irrelevant.')
C('the prices provided in the current prices are $8.10 for A, $4.90 for B, $7.90 for C, and $5.30 for D.',[CP],'other_or_unclear','descriptive_only','supported',PIDS,PFS,'The separately stated numerical values are correct even though the same explanation incorrectly says they are unavailable.')
C("The customer's previous purchase (H4) shows that they bought product D at $4.20",[HH],'historical_price_purchase_relationship','descriptive_only','supported',['H4'],['H4.purchased','H4.prices.D'],'H4 links purchased D to associated D offer $4.20. Do not map unrelated A/B/C prices or advertising.')
C('the customer bought product A at $6.30, which is close to the current price of $8.10.',[CP,HH],'historical_price_purchase_relationship','contributing','unclear',['H5','P_A'],['H5.purchased','H5.prices.A','current.prices.A'],'The two prices are supplied and differ by $1.80; close has no defined threshold. However/Therefore context presents this as a reason favoring A, not a generic history description.',favors=['A'])

cid='row-1289__with_history__HISTORICAL_PRICE_ASSOCIATION'
begin(cid,['C1 maps P_A..P_D to H1..H5 fields: fields exist but are not covered by those evidence IDs.'],
 ['C1 bundles supported absence of recency with uncertainty; all history prices/flags are unnecessary.','Missing false D-cheapest and all-four-brands-purchased claims.','Preference caveat is not an explicit denial of price influence.'],
 ['Correct current prices and advertising descriptions.','False purchase coverage: B never purchased in supplied history.','False D minimum, tentative price reason favoring D, and preference caveat.'],
 ['Confirm contributing for which could be a candidate despite the later caveat; do not convert it to explicitly_irrelevant.','Generic uncertainty about the target is not an externally verified prediction-accuracy claim.'],
 'inadequate: unclear should be split into supported missing chronology and generic uncertainty; major false claims unassessed')
C('The prices for the products are: A: $8.10, B: $4.90, C: $7.90, D: $5.30.',[CP],'other_or_unclear','descriptive_only','supported',PIDS,PFS,'All four numerical current prices match the exact displayed input.')
C('The advertising status for all products is NOT_ADVERTISED.',[CA],'current_advertising','descriptive_only','supported',FIDS,FFS,'In context this describes current advertising, which is false for all four flags. It must not be expanded to all historical flags: historical H4.C is advertised.')
C('the customer has previously purchased products A, B, C, and D',[HH],'other_or_unclear','descriptive_only','contradicted',HIDS,HFS,'All five records remain distinct. A=2, C=2, D=1, B=0, so the claimed B purchase is false.')
C('with varying prices.',[HH],'historical_price_purchase_relationship','descriptive_only','supported',HIDS,HFS+[h+'.prices.'+c for h in HIDS for c in 'ABCD'],'Historical purchased products have varying associated offers. This does not create an independent parent group or imply preference.')
C('The most recent purchase is not explicitly stated',[HH],'other_or_unclear','descriptive_only','supported',HIDS,[],'The explicit unordered-record instruction supports missing chronology. No timestamps are supplied; current P IDs cannot support historical source fields.',origin='replacement',prompt=['Support records are unordered separate purchases.'],missing=['historical chronology'])
C('The lowest price is for product D at $5.30',[CP],'current_price_comparison','descriptive_only','contradicted',PIDS,PFS,'B $4.90 is strictly below D $5.30 using canonical visible prices.')
C('The lowest price is for product D at $5.30, which could be a candidate.',[CP],'current_price_comparison','contributing','not_applicable',PIDS,PFS,'Scope here is the tentative price-based reason favoring D, not factual endorsement of the false minimum premise; that premise is separately contradicted.',favors=['D'],scope='claimed_influence_only')
C('there is no direct evidence indicating a preference for the lowest price.',[CP],'other_or_unclear','unclear','supported',reason='No direct customer motive/preference is provided. A caveat about preference does not explicitly deny influence on the prediction.',prompt=['Customer motives are unknown.'],missing=['direct evidence of customer preference'])
C('so we cannot definitively determine the product purchased.',[],'other_or_unclear','unclear','not_applicable',reason='Generic uncertainty about the hidden outcome. This is neither a history-offer relationship nor an explicit no-influence claim.',origin='replacement',missing=['actual target purchase'])

cid='row-2379__no_history__ORIGINAL'
begin(cid,['C1 quote capitalizes/rewrites the explanation prefix and is not exact.'],
 ['The numerical supported label is correct within its scope, but role should be descriptive_only.','Do not infer a decisive cheapest rule from a correct minimum or prediction B alone.'],
 ['Correct B-minimum/C-next comparison.','Known F_B=NOT_ADVERTISED versus unsupported popularity/preference inference.','Unknown motives and final uncertainty; caveat is weaker than explicit irrelevance.'],
 ['The However price comparison could imply rhetorical contribution; proposed descriptive_only, with no inferred direction.','Tentative advertising-to-popularity argument is proposed contributing toward B, not decisive; confirm intended contextual role.'],
 'correct for returned numeric price assertion only; materially incomplete')
C('The evidence shows that the price of product A is $9.80, product B is $4.90, product C is $7.90, and product D is $10.30.',[CP],'other_or_unclear','descriptive_only','supported',PIDS,PFS,'Use an exact quotation. All four values match; a price list is descriptive, not by itself a claimed influence or a comparison.',origin='replacement')
C('Since the customer motive is unknown',[],'other_or_unclear','descriptive_only','supported',reason='Customer motives are explicitly unknown in the predictor instructions.',prompt=['Customer motives are unknown.'])
C('we cannot infer a preference based on price.',[CP],'other_or_unclear','unclear','supported',reason='Direct price-preference information is unavailable. This does not say price had no influence on the model.',prompt=['Customer motives are unknown.'],missing=['customer price preference'])
C('product B has the lowest price, and product C has the next lowest.',[CP],'current_price_comparison','descriptive_only','supported',PIDS,PFS,'Correct ordering B $4.90 < C $7.90 < A $9.80 < D $10.30. No explicit deciding rule is stated; do not infer direction solely from correct comparison.')
C('product B is advertised as NOT_ADVERTISED',[CA],'current_advertising','descriptive_only','supported',['F_B'],['current.advertised.B'],'Read NOT_ADVERTISED as the supplied flag, not a literal claim that an advertisement exists.')
C('The fact that product B is advertised as NOT_ADVERTISED may indicate it is a more popular or preferred product.',[CA],'current_advertising','contributing','unsupported_by_supplied_information',['F_B'],['current.advertised.B'],'The flag is known, but popularity/preference cannot be inferred from it. The tentative favorable argument still claims a possible contributing reason toward B; factual unsupportedness does not remove claimed influence.',favors=['B'],missing=['popularity or preference evidence'])
C('without additional information, we cannot definitively determine the target purchase.',[],'other_or_unclear','unclear','not_applicable',reason='Outcome uncertainty, not verified customer behavior and not explicit denial of price/advertising influence.',missing=['actual target purchase'])

cid='row-2379__with_history__ORIGINAL'
begin(cid,['C1 maps current P IDs to 45 H fields. All names exist, but evidence-to-field coverage is invalid.'],
 ['No HOUSEHOLD_HISTORY attribution is justified by the quoted generic unknown-motive statement.','An unknown-motive caveat is not evidence of no preference and not explicitly irrelevant.'],
 ['Unsupported claim that the current purchase included all four candidates.','Correct listed offer prices must be separated from actual bought/paid assertions.','Statement of unknown motives versus claimed absence of stable preference.'],
 ['Does included mean purchased all four products or loosely mean considered/offered candidates? Literal purchase reading is unsupported; offer reading would make the numbers supported.','No explicit deciding rule for D is stated; leave influence and direction unclear rather than inventing one.'],
 'inadequate: generic unknown motives should be separated from unsupported assertion about revealed preference; major purchase claim absent')
C('The customer made a purchase where the prices for all products were displayed.',[CP],'other_or_unclear','descriptive_only','unclear',PIDS,PFS,'Prices are displayed to the model. Whether the actual customer saw them is not independently supplied; avoid treating prompt display as observed customer exposure.',missing=['customer exposure to offers'])
C("The customer's purchase included products A, B, C, and D with prices $9.80, $4.90, $7.90, and $10.30 respectively.",[CP],'other_or_unclear','descriptive_only','unsupported_by_supplied_information',PIDS,PFS,'Current candidate offers do not establish buying all candidates or their actual paid prices. The task concerns one hidden purchased product. If purchase included is loose shorthand for candidate set, label interpretation requires user review.',missing=['actual target purchase','actual paid prices'])
C('These prices are consistent with the current prices listed in the CURRENT_PRICES.',[CP],'other_or_unclear','descriptive_only','supported',PIDS,PFS,'The four numerical offer values match. This does not validate the preceding actual-purchase interpretation.')
C("The customer's purchase does not indicate a preference for any particular product",[],'other_or_unclear','unclear','unsupported_by_supplied_information',reason='The target purchase is hidden and unknown motives do not prove that a purchase indicates no preference. No historical field is referenced by this generic statement.',origin='replacement',missing=['actual target purchase','customer preference'])
C('as the motives are unknown.',[],'other_or_unclear','descriptive_only','supported',reason='Supported by prompt; separate this valid availability statement from the stronger no-preference assertion.',origin='replacement',prompt=['Customer motives are unknown.'])

cid='row-2379__with_history__HISTORICAL_PRICE_ASSOCIATION'
begin(cid,[],['C1 supported incorrectly labels an unknown target paid price and supposed direct match as established.','Whole explanation is bundled into one contributing current-price-comparison claim; factual and influence scopes differ.','Direction toward D is appropriate for the explicit conclusion, but not for each historical description.'],
 ['No text omitted literally, but no atomic coverage: unsupported paid-price premise, correct D offer, correct historical purchases, price-match inference, and explicit selection reason must be split.'],
 ['The final Since rule is proposed decisive as the explicit stated basis for D; confirm decisive versus contributing.','The earlier This corresponds phrase inherits an unknown paid-price premise; do not treat it as an independently observed transaction match.','Historical D repetitions can describe purchases under different offers, but do not establish customer preference or actual model causality.'],
 'incorrect: supported bundles an unavailable target paid price with correct candidate/historical offer facts')
C('The customer purchased a product with a price of $10.30.',[CP],'other_or_unclear','descriptive_only','unsupported_by_supplied_information',['P_D'],['current.prices.D'],'P_D establishes only candidate D current offer $10.30. H1 also has a historical D offer $10.30, but that is a separate support purchase, not the hidden target.',origin='replacement',missing=['actual target purchase','actual target paid price'])
C('This corresponds to product D',[CP],'other_or_unclear','unclear','unsupported_by_supplied_information',['P_D'],['current.prices.D'],'The referent is the asserted target paid price. A correct candidate-price association cannot establish which target product was bought.',origin='replacement',missing=['actual target paid price'])
C('which has a price of $10.30 in the current prices.',[CP],'other_or_unclear','descriptive_only','supported',['P_D'],['current.prices.D'],'D current offer is correctly stated. It is not an actual paid-price observation.',origin='replacement')
C("The customer's previous purchases (H1, H2, H5) also included product D at various prices",[HH],'brand_persistence_under_different_offers','descriptive_only','supported',['H1','H2','H5'],['H1.purchased','H1.prices.D','H2.purchased','H2.prices.D','H5.purchased','H5.prices.D'],'H1,H2,H5 purchase D with distinct associated D offers $10.30,$12.20,$11.50. This is supported repeated purchase under different offers, not a preference label or price deciding rule.',origin='replacement')
C('but the specific purchase occasion is not specified.',[],'other_or_unclear','unclear','unclear',reason='Ambiguous referent: the task specifies a current occasion but hides its purchase; historical records have no timestamps. Either interpretation requires scope clarification.',origin='replacement',missing=['target purchase identity','historical timestamps'])
C('Since the price is directly matched',[CP],'other_or_unclear','unclear','unsupported_by_supplied_information',['P_D'],['current.prices.D'],'The asserted actual-target-to-offer match depends on an unavailable paid price. Historical H1 matching D price does not supply it.',origin='replacement',missing=['actual target paid price'])
C('Since the price is directly matched, the most likely candidate is D.',[CP],'other_or_unclear','decisive','not_applicable',['P_D'],['current.prices.D'],'Scope is the claimed choice rationale: an explicit Since price-match reason for D. Retain claimed price influence despite the unsupported match premise, separately assessed above. This is not a verified paid-price match or actual causal influence.',favors=['D'],origin='replacement',scope='claimed_influence_only')

# Preserve all exact inputs, responses, citations, raw annotation text and guide snapshots.
snapshot=[]
for cid,result in records.items():
 snapshot.append({'call_id':cid,'predictor_messages':entries[cid]['messages'],
  'predictor_raw_response':json.loads((PILOT/'responses'/f'{cid}.json').read_text())['response']['raw_response'],
  'annotation_input':result['annotation_input'],'raw_annotation_response':result['raw_annotation_response'],
  'parsed_annotations':result['parsed_annotations'],'original_diagnostics':result['diagnostics'],
  'annotation_guide':result['annotation_guide']})
checks={}
for cid,r in review.items():
 original=records[cid];claims=[{k:c[k] for k in FIELDS} for c in r['proposed_claims']]
 parsed,d=validate_annotations(json.dumps({'claims':claims}),explanation=original['annotation_input']['explanation'],
    candidates=original['annotation_input']['candidates'],provenance=original['annotation_input']['provenance'])
 assert d['structure_and_traceability_ok'],(cid,d)
 checks[cid]={'proposed_claim_count':len(claims),'proposal_exact_quotes_and_reference_structure_pass':True,
             'semantic_correctness_and_complete_coverage_not_machine_verified':True}
# Expected, non-inferential factual checks for the requested error cases.
assert review['row-1289__no_history__ORIGINAL']['factual_context']['current_cheapest_candidates']==['B']
assert review['row-1289__with_history__HISTORICAL_PRICE_ASSOCIATION']['factual_context']['support_purchase_counts']=={'A':2,'B':0,'C':2,'D':1}
assert review['row-2379__with_history__HISTORICAL_PRICE_ASSOCIATION']['factual_context']['support_purchase_counts']=={'A':1,'B':1,'C':0,'D':3}
for rel,h in protected.items():assert sha256((ROOT/rel).read_bytes()).hexdigest()==h,rel

def save(name,data):
 (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
save('source_snapshots.json',snapshot)
save('reviewed_layer.json',{'review_label':'agent-assisted','status':'proposed corrections; user review pending; no human review claimed',
 'scope':'Six existing pilot annotations only. No model calls. No predictor changes. Not a validation sample or accepted gold standard.',
 'guide_version':manifest['annotation_guide']['version'],'guide_sha256':manifest['annotation_guide']['sha256'],
 'rules':['Factual correctness and claimed influence are separate axes.','Mappings evaluate claims, including contradictions; they do not establish attention or actual influence.',
 'Prompt constraints and missing information are recorded separately from existing source-field references.',
 'Overlapping quotations separate factual premises and influence-only scopes; not_applicable on an influence-only row does not endorse its premise.',
 'Descriptive price lists use other_or_unclear because the guide has no dedicated price-level label.',
 'Unquoted boilerplate, literal evidence-ID recitations and pure final prediction restatements are not expanded into redundant claims; material factual and reason claims are reviewed.'],
 'records':review})
save('verification.json',{'review_label':'agent-assisted','records_reviewed':6,'predictor_calls_added':0,'annotator_calls_added':0,
 'all_protected_original_files_unchanged':True,'protected_sha256':protected,'proposed_claim_checks':checks,
 'semantic_correctness_automatically_validated':False,'human_review_occurred':False})

short={
 'row-1289__no_history__ORIGINAL':('Nonexact quote','False minimum labeled supported; price role missed','Explicit lowest-price rule','B is cheapest; keep decisive price claim toward D','Contextual direction D?'),
 'row-1289__with_history__ORIGINAL':('No structural failure; excessive fields','Diversity mislabeled price relationship/unclear','H5 recency; false missing prices; A-price reason','Narrow H fields; split supported facts, unsupported recency, cross-group A reason','Closeness threshold; contributing vs decisive?'),
 'row-1289__with_history__HISTORICAL_PRICE_ASSOCIATION':('P IDs cannot cover H fields','Uncertainty bundled; major facts unjudged','False D minimum; nonexistent B purchase; tentative D reason','Map chronology to instruction/history; B count=0; price premise false, influence retained','Tentative contributing role despite caveat?'),
 'row-2379__no_history__ORIGINAL':('Nonexact quote','Price-list role unclear; supported numbers are correct','B/C comparison; advertising/popularity argument','Exact price quote descriptive; popularity unsupported but possible contributing B reason','Rhetorical price role; tentative ad role?'),
 'row-2379__with_history__ORIGINAL':('P IDs cannot cover H fields','Generic motive caveat assigned history','All-four-products purchase assertion; offer/paid distinction','Remove invented history mapping; split offer values from unsupported purchase assertion','Does purchase included mean bought or offered?'),
 'row-2379__with_history__HISTORICAL_PRICE_ASSOCIATION':('Passes exact-quote/reference checks','Unknown paid-price match labeled supported; compound role','Atomic claims absent despite full-text quote','Split unknown target paid price, correct D/history facts, claimed D price-match rule','Decisive vs contributing; occasion referent?')}
report=['# Six-record annotation quality audit','', '**Review: agent-assisted. Proposed corrections require user review. No human review is claimed.**','',
 'No new predictor or annotator calls were made. Raw annotations, predictor outputs, inputs, guide and pilot ledger are unchanged; hashes are recorded in `verification.json`.',
 '', '## Separate quality axes','',
 '- JSON/schema shape: 6/6 parse with the expected fields/enums. This does not establish annotation quality.',
 '- Exact quotations: 4/6 records pass; two quotes rewrite the explanation.',
 '- ID/field existence: 6/6 reference existing names. Evidence-to-field coverage: 4/6 pass; two map current price IDs to historical fields.',
 '- Original predictor citation lists: all six contain available IDs and match the exact saved predictor response. They are global lists, not claim-level attributions. A reviewer may map available H records omitted by the predictor; doing so does not prove that history influenced the model.',
 '- Combined structural/traceability checks: 2/6 pass. These checks do not judge semantic truth.',
 '- Factual-label correctness: two records incorrectly label a false/unsupported compound claim as supported; one has a correct supported numeric statement within its narrow scope; three use unclear for separable availability/descriptive assertions and need scoped correction. These record-level categories are not an annotation accuracy estimate.',
 '- Material claim coverage: 6/6 need expansion or splitting. Five omit material text; the sixth quotes the entire explanation as one mixed claim, so it still lacks atomic coverage. Neither structural pass is ready for unchecked use.',
 '', '## Compact audit table','',
 '| Record | Traceability errors | Incorrect/inadequate semantic labels | Missing claims | Proposed corrections | Questions for user |',
 '|---|---|---|---|---|---|']
for cid in sorted(review):
 report.append('| '+cid+' | '+' | '.join(short[cid])+' |')
report+=['','## Requested factual checks','',
 '- Household 53 current offers are A $8.10, B $4.90, C $7.90, D $5.30. B is cheapest. Both original no-history and historical-price-edited explanations falsely call D cheapest. Correct labels for the factual minimum claims are contradicted.',
 '- The original no-history explanation explicitly says **“the choice is based on the lowest price.”** Proposed role: decisive; factual status for that influence-only assertion: not_applicable. Its context favors D even though its price premise is false. Do not turn a false premise into “no claimed price influence.”',
 '- Household 53 support purchases are A,C,C,D,A: A=2, B=0, C=2, D=1. The historical-price edit does not change them. Its all-four-brands claim is contradicted. Household 99 purchases are D,D,B,A,D: D=3, A=1, B=1, C=0. No omitted/duplicated support records are assumed.',
 '- H5 is not a timestamp. Calling it most recent is unsupported, not directly disproved. The statement that recency is not supplied is supported by the explicit unordered-history instruction.',
 '- In household 99 historical-price-edited input, P_D is a **candidate offer** of $10.30. H1 has a historical D offer at $10.30. Neither supplies the hidden current purchase or actual paid price. The asserted current paid-price match is unsupported. Proposed price-match deciding rationale still records claimed influence toward D.',
 '- Preference/popularity is unavailable. NOT_ADVERTISED is a known flag, not evidence that a product is popular or preferred. A caveat about unknown preference is not an explicit assertion that price or advertising was irrelevant.',
 '', '## Proposed layer and supporting values','',
 '`reviewed_layer.json` contains exact quotations and occurrence offsets, proposed guide labels, source values (untouched and displayed canonical prices), mapped IDs, required fields, prompt constraints, reasons, missing information and unresolved questions for every proposed correction. `source_snapshots.json` preserves the six exact factual inputs, explanations, original citations, raw annotations and guide snapshots. Proposed quotes/references pass mechanical checks only; semantic judgments remain agent-assisted proposals.',
 '', '## Recommendation for the 100-case analysis','',
 '**Unchecked automatic annotations are not suitable in their current form.** Automatic JSON/traceability checks should be a gate, followed by claim-coverage and semantic review that explicitly audits deciding rules, false factual premises, chronology and unavailable outcomes. Preserve separate raw and reviewed layers and adjudicate the listed ambiguities before accepting labels. These six diagnostics and agent-assisted corrections do not validate the annotator or establish reliability on 100 cases. No larger experiment was launched.']
(OUT/'audit.md').write_text('\n'.join(report)+'\n')
print('\n'.join(report[:24]));print('Saved',sum(len(r['proposed_claims']) for r in review.values()),'proposed scoped claims across six records. No original files changed.')
