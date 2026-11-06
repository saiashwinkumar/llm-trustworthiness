"""Focused saved-label and accounting fixtures; no model calls or new study labels."""
import json,unittest
from copy import deepcopy
from choice_trust.test100_metrics import rate,decode,influence,claim_match,conditional_metrics,factuality_metrics,rule_assessment,stale_assessment
from choice_trust.observations import generate_observations
from choice_trust.joint_observation import parse_joint_response


def fixture(mapping=None,answer='A'):
    mapping=mapping or {'A':'A','B':'B'}
    candidates=[{'id':mapping[k],'name':'fixture '+k} for k in 'AB']
    obs=generate_observations(candidates,{'prices':{mapping['A']:1,mapping['B']:2},'advertised':{mapping[k]:False for k in 'AB'}},None)
    entry={'observations':obs,'presentation':{'answer_mapping':mapping}}
    raw=json.dumps({'explanation':'Synthetic fixture, not a model response.','evidence_ids':['P_'+answer],'prediction':answer})
    parsed,diag=parse_joint_response(raw,candidates,obs,truncated=False)
    inverse={v:k for k,v in mapping.items()}
    record={'decoded_product_id':inverse[answer],'response':{'raw_response':raw,'parsed_result':parsed,'diagnostics':diag}}
    return entry,record


def ann(claims):return {'annotation_id':'synthetic-reference','claims':claims,'record':{}}

def price_claim(role='decisive',status='supported'):
    return {'claim_id':'C1','exact_quote':'Fixture explicit reason','concept_groups':['CURRENT_PRICES'],
            'relationship_type':'current_price_comparison','claimed_role':role,'factual_status':status,
            'source_fields':['current.prices.A','current.prices.B'],'mapped_evidence_ids':['P_A','P_B']}


class MetricsChecks(unittest.TestCase):
    def test_zero_and_control_complement(self):
        self.assertIsNone(rate(0,0)['rate']);self.assertIsNone(rate(0,0)['percentage'])
        self.assertAlmostEqual(rate(42,99)['rate'],1-rate(57,99)['rate'])
        with self.assertRaises(AssertionError):rate(2,1)
    def test_decoded_product_invariance_and_malformed_exclusion(self):
        e,a=fixture();mapped,b=fixture({'A':'B','B':'A'},answer='B')
        self.assertNotEqual(a['response']['parsed_result']['prediction'],b['response']['parsed_result']['prediction'])
        self.assertEqual(decode(a,e),decode(b,mapped))
        bad=deepcopy(a);bad['response']['raw_response']='{"prediction":'
        parsed,diag=parse_joint_response(bad['response']['raw_response'],e['observations']['candidates'],e['observations'],truncated=True)
        bad['response'].update(parsed_result=parsed,diagnostics=diag)
        self.assertEqual(decode(bad,e),(None,'json_parse_failure'))
    def test_false_factual_premise_does_not_erase_claimed_influence(self):
        result=influence(ann([price_claim(status='contradicted')]),'CURRENT_PRICE',[])
        self.assertEqual(result['classification'],'yes')
        self.assertEqual(result['evidence'][0]['factual_status'],'contradicted')
    def test_household_frequency_not_offer_removal_and_broad_unresolved(self):
        c={'claim_id':'C1','concept_groups':['HOUSEHOLD_HISTORY'],'relationship_type':'support_purchase_frequency',
           'claimed_role':'decisive','source_fields':['H1.purchased'],'exact_quote':'fixture'}
        patch=[{'field':'H1.purchased','before':'A','after':'B'}]
        self.assertEqual(claim_match(c,'SUPPORT_PURCHASE',patch),'fine')
        self.assertIsNone(claim_match(c,'HISTORICAL_OFFER_REMOVAL',patch))
        self.assertIsNone(claim_match(c,'HISTORICAL_ADVERTISING_ASSOCIATION',patch))
        broad={**c,'source_fields':[],'relationship_type':'other_or_unclear'}
        self.assertEqual(influence(ann([broad]),'HISTORICAL_PRICE_ASSOCIATION',[])['classification'],'unclear')
    def test_conditional_excludes_missing_labels_and_preserves_no_subtype(self):
        rows=[]
        labels={}
        for i,(role,changed) in enumerate([('decisive',True),('decisive',False),('descriptive_only',True),(None,False)]):
            cid=f'fixture{i}';rows.append({'family':'CURRENT_PRICE','original_response_id':cid,'exact_patch':[],
                'valid_prediction_comparison':True,'prediction_changed':changed,'applicable':True})
            if role:labels[cid]=ann([price_claim(role)])
        tables,overall=conditional_metrics(rows,labels);r=tables[0]
        self.assertEqual((r['yes_changed'],r['yes_unchanged'],r['no_changed'],r['no_unchanged']),(1,1,1,0))
        self.assertEqual(r['unassessable_excluded'],1);self.assertEqual(r['p_change_given_claimed_influence']['rate'],.5)
        self.assertEqual(rows[2]['claimed_influence']['subtype'],'descriptive_only')
        self.assertEqual(overall['valid_prediction_pairs'],4)
    def test_factual_claims_count_distinct_original_once(self):
        e,r=fixture();run={'responses':{},'entries':{}}
        labels={}
        for cid,family,status in [('original','ORIGINAL','supported'),('edit1','CURRENT_PRICE','contradicted'),('edit2','CURRENT_ADVERTISING','unsupported_by_supplied_information')]:
            run['responses'][cid]={**r,'call_id':cid,'case_id':'fixture','family':family};run['entries'][cid]=e
            labels[cid]=ann([{**price_claim(status=status),'claim_id':'C1'}])
        groups,claims,coverage=factuality_metrics(run,labels)
        self.assertEqual(groups['originals']['contradiction_rate']['denominator'],1)
        self.assertEqual(groups['all_distinct_responses']['contradiction_rate']['rate'],.5)
        self.assertEqual(groups['edited_overall']['excluded_status_counts']['unsupported_by_supplied_information'],1)
        self.assertEqual(len(claims),3)
    def test_rule_and_stale_are_not_invented_from_weak_labels(self):
        pair={'case_id':'fixture','family':'CURRENT_PRICE','original_response_id':'orig','edited_response_id':'edit',
              'exact_patch':[{'field':'current.prices.A','before':1,'after':3}],'applicable':True,'valid_prediction_comparison':True,'edited_product_id':'B'}
        self.assertEqual(rule_assessment(pair,ann([price_claim('contributing')]),{})['reason'],'no_explicit_deciding_rule_in_reference_labels')
        self.assertEqual(stale_assessment(pair,ann([price_claim(status='contradicted')]))['status'],'unassessable')
        stale=ann([{**price_claim(status='contradicted'),'stale_fact':True}])
        self.assertTrue(stale_assessment(pair,stale)['contains_stale_fact'])
        rule=price_claim();rule['rule_specification']={'template':'choose_uniquely_cheapest_current_product','premise_claim_ids':['C2']}
        premise={**price_claim('descriptive_only'),'claim_id':'C2'}
        run={'entries':{'edit':{'edited_source':{'current':{'prices':{'A':3,'B':2}}}}}}
        self.assertTrue(rule_assessment(pair,ann([rule,premise]),run)['consistent'])
        premise['factual_status']='contradicted'
        self.assertEqual(rule_assessment(pair,ann([rule,premise]),run)['status'],'invalid_premise')

if __name__=='__main__':unittest.main()
