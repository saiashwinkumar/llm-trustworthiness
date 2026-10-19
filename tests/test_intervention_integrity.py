"""Scientific regression checks for the fresh CPU protocol; no model/API calls."""
import copy
import csv
import math
from pathlib import Path
import tempfile
import unittest

from choice_trust.interventions import (apply, edit, explanation_tests,
                                        measurements, planned_specs, systematic)
from choice_trust.evaluation import (audit_metrics, estimate, explanation_metrics,
                                    metric_rows, monotonicity, temperature_fit)


def case_fixture():
    facts=[]
    for cid,price in [('a',4.0),('b',6.0)]:
        facts.extend([
            dict(id='P_'+cid,value=price,type='price',source='current offer',candidate_id=cid,
                 units='dataset units',editable=True,pre_decision=True,
                 policy=dict(kind='numeric',multipliers=[.8,1.2],development_bounds=[3.,12.])),
            dict(id='F_'+cid,value=False,type='advertised',source='current offer',candidate_id=cid,
                 units='boolean',editable=True,pre_decision=True,
                 policy=dict(kind='categorical',values=[False,True]))])
    facts.append(dict(id='H1',value={'choice':'a'},type='history',source='separate purchase',
                      observation_id='support-1',units='observation',editable=False,pre_decision=True))
    return dict(schema_version=2,case_id='held-out',dataset_id='integrity-fixture',task='purchase',
                candidates=[dict(id=cid,name=cid,attributes={'price':'P_'+cid,'advertised':'F_'+cid}) for cid in ('a','b')],
                evidence=facts,outcome='b',group_id='household-1',split='test',synthetic=True,constraints=[])


def explanation(ids=None,**changes):
    row=dict(record_id='explanation-1',record_hash='explanation-hash-1',prediction_id='p1',
             parse_ok=True,citation_valid=True,abstained=False,truncated=False,group_id='household-1',
             parsed={'evidence_ids':ids or ['P_a'],'explanation':'A checkable test explanation.',
                     'counterfactual':{'evidence_id':'P_a','value':4.4,'expected_direction':'decrease'}},
             claim_error=None)
    row.update(changes)
    return row


class InterventionIntegrityTests(unittest.TestCase):
    def test_bad_explanation_never_disables_independent_interventions(self):
        case=case_fixture()
        variants=[None,explanation(parse_ok=False),explanation(citation_valid=False),
                  explanation(abstained=True),explanation(truncated=True),
                  explanation(parsed=None),explanation(ids=['P_a','P_a'])]
        original_grid=systematic(case,'with_history',42,2)
        for bad in variants:
            specs=planned_specs(case,'with_history',bad,3,42,2,'all')
            self.assertEqual(specs[:len(original_grid)],original_grid)
            dependent=[s for s in specs if s['kind'] in ('cited_remove','cited_retain','explicit_claim')]
            self.assertTrue(all(s.get('skip_reason') for s in dependent))
            presentations=[s for s in specs if s['kind']=='presentation']
            self.assertTrue(presentations)
            self.assertTrue(all(apply(case,s)[0] is not None for s in presentations))
        # Scope selection does not inspect explanations to construct independent edits.
        self.assertEqual(planned_specs(case,'with_history',None,3,42,2,'systematic'),original_grid)

    def test_unavailable_history_cannot_enter_no_history_citation_tests(self):
        checks=explanation_tests(case_fixture(),'no_history',explanation(ids=['H1']),3,42)
        self.assertTrue(all(s.get('skip_reason') for s in checks))

    def test_exact_claim_edit_is_separate_from_predefined_numeric_grid(self):
        case=case_fixture(); untouched=copy.deepcopy(case)
        specs=explanation_tests(case,'with_history',explanation(),3,42)
        claim=next(s for s in specs if s['kind']=='explicit_claim')
        self.assertEqual(claim['value'],4.4)
        changed,reason=apply(case,claim)
        self.assertIsNone(reason)
        self.assertEqual(next(e['value'] for e in changed['evidence'] if e['id']=='P_a'),4.4)
        grid=[s['value'] for s in systematic(case,'with_history')
              if s['kind']=='attribute_sweep' and s['evidence_ids']==['P_a']]
        self.assertEqual(grid,[3.2,4.8])
        self.assertNotIn(4.4,grid)
        self.assertEqual(case,untouched)
        self.assertIsNone(changed['outcome'])
        self.assertEqual(changed['candidates'],case['candidates'])
        invalid=dict(claim,value=20.)
        self.assertIsNone(apply(case,invalid)[0])
        self.assertIn('bounds',apply(case,invalid)[1])

    def test_controls_match_evidence_roles_and_histories_are_masked_not_relabelled(self):
        case=case_fixture(); ids=['P_a','F_b','H1']
        by_id={e['id']:e for e in case['evidence']}
        checks=explanation_tests(case,'with_history',explanation(ids=ids),4,42)
        controls=[s for s in checks if s['kind']=='random_remove']
        self.assertEqual(len(controls),4)
        for spec in controls:
            self.assertEqual(sorted(by_id[i]['type'] for i in spec['evidence_ids']),['advertised','history','price'])
        full=next(s for s in systematic(case,'with_history') if s['kind']=='history_mask')
        changed,reason=apply(case,full)
        self.assertIsNone(reason)
        history=next(e for e in changed['evidence'] if e['id']=='H1')
        self.assertTrue(history['masked'])
        self.assertEqual(history['value'],{'choice':'a'})
        self.assertIsNone(changed['outcome'])
        self.assertEqual(changed['candidates'],case['candidates'])
        absent=next(s for s in systematic(case,'no_history') if s['kind']=='history_mask')
        self.assertTrue(absent['skip_reason'])
        self.assertIsNone(apply(case,absent)[0])

    def test_presentation_cannot_remove_or_duplicate_candidates(self):
        case=case_fixture()
        for order in (['a'],['a','a'],['a','unknown'],None):
            changed,reason=apply(case,dict(kind='presentation',evidence_ids=[],order=order))
            self.assertIsNone(changed)
            self.assertIn('every candidate',reason)
        changed,reason=apply(case,dict(kind='presentation',evidence_ids=[],order=['b','a']))
        self.assertIsNone(reason)
        self.assertEqual(changed['candidates'],case['candidates'])

    def test_fixed_original_reference_and_removal_advantage_sign(self):
        original=dict(prediction='a',scores={'a':.7,'b':.3})
        effects=measurements(original,dict(prediction='b',scores={'a':.4,'b':.6}))
        self.assertAlmostEqual(effects['score_change'],-.3)
        self.assertAlmostEqual(effects['margin_change'],math.log(.4/.6)-math.log(.7/.3))
        self.assertEqual(effects['reference_candidate'],'a');self.assertEqual(effects['fixed_rival'],'b')
        self.assertTrue(effects['winner_changed'])
        predictions=[dict(record_id='p1',correct=True,group_id='household-1')]
        interventions=[]
        for kind,delta,margin_delta in [('cited_remove',-.3,-1.),('random_remove',-.1,-.2),
                                        ('random_remove',-.05,-.1),('cited_retain',.04,.1)]:
            interventions.append(dict(prediction_id='p1',group_id='household-1',status='measured',
                                      spec={'kind':kind},score_change=delta,margin_change=margin_delta))
        result=explanation_metrics(predictions,[explanation()],interventions,20)['all']['metrics']
        self.assertAlmostEqual(result['removal_advantage']['mean'],.225)
        self.assertAlmostEqual(result['margin_advantage']['mean'],.85)
        self.assertEqual(result['removal_advantage']['n'],1)
        self.assertIsNone(result['removal_advantage']['ci95'])
        self.assertAlmostEqual(result['retention_absolute_change']['mean'],.04)

    def test_invalid_source_effects_excluded_but_presentation_still_measured(self):
        predictions=[dict(record_id='p1',correct=False,group_id='household-1')]
        rows=[dict(prediction_id='p1',group_id='household-1',status='measured',
                   spec={'kind':kind},score_change=-.1,margin_change=-.2,winner_changed=True,
                   claim_agreement=True) for kind in ('cited_remove','random_remove','explicit_claim','presentation')]
        group=explanation_metrics(predictions,[explanation(citation_valid=False)],rows,20)['all']
        self.assertEqual(group['metrics']['removal_advantage']['n'],0)
        self.assertEqual(group['metrics']['explicit_claim_agreement']['n'],0)
        self.assertEqual(group['metrics']['presentation_flip']['n'],1)
        self.assertEqual(group['measured_interventions'],4)
        self.assertEqual(group['excluded_invalid_explanation_measurements'],3)


class EvaluationIntegrityTests(unittest.TestCase):
    def test_known_metrics_and_household_not_row_bootstrap(self):
        rows=[dict(prediction='a',outcome='a',group_id='h1',scores={'a':.8,'b':.2}),
              dict(prediction='a',outcome='b',group_id='h2',scores={'a':.7,'b':.3})]
        metrics=metric_rows(rows,100)
        self.assertEqual(metrics['accuracy']['mean'],.5)
        self.assertAlmostEqual(metrics['log_loss']['mean'],(-math.log(.8)-math.log(.3))/2)
        self.assertAlmostEqual(metrics['brier_sum']['mean'],.53)
        self.assertAlmostEqual(metrics['mrr']['mean'],.75)
        self.assertAlmostEqual(metrics['ece_5'],.45)
        clustered=estimate([(1,'same-household'),(0,'same-household'),(1,'other-household')],200)
        self.assertAlmostEqual(clustered['mean'],2/3)
        self.assertEqual(clustered['groups'],2)
        self.assertEqual(clustered['ci95'],[.5,1.])
        self.assertIsNone(estimate([(1,'only-household'),(0,'only-household')],100)['ci95'])

    def test_temperature_never_uses_test_outcomes(self):
        validation=[dict(split='validation',scores={'a':.9,'b':.1},outcome='b')]
        fixed=temperature_fit(validation)
        self.assertEqual(temperature_fit(validation+[dict(split='test',scores={'a':1.,'b':0.},outcome='a')]),fixed)
        self.assertIsNone(temperature_fit([dict(split='test',scores={'a':.9,'b':.1},outcome='a')])['temperature'])

    def test_monotonicity_uses_probability_tolerance_independent_of_currency(self):
        def row(price,new_price,after_score):
            return dict(condition='full',split='test',group_id='h1',status='measured',
                        spec={'kind':'attribute_sweep','evidence_ids':['P_a'],'value':new_price},
                        original_evidence=[dict(id='P_a',type='price',candidate_id='a',value=price)],
                        before={'scores':{'a':.5,'b':.5}},after={'scores':{'a':after_score,'b':1-after_score}})
        tiny=row(.0001,.00011,.51)
        large=row(100.,110.,.51)
        for candidate in (tiny,large):
            diagnostic=monotonicity([candidate],20)['full']['test']
            self.assertEqual(diagnostic['estimate']['mean'],0.)
            self.assertIn('diagnostic',diagnostic['interpretation'])
        agrees=monotonicity([row(5.,6.,.49),row(5.,4.,.51),row(5.,6.,.50000001)],20)
        self.assertEqual(agrees['full']['test']['estimate']['mean'],1.)

    def test_manual_reviews_require_matching_hash_and_blank_is_unreviewed(self):
        predictions=[dict(record_id='p1'),dict(record_id='p3')]
        explanations=[dict(record_hash='current-test',prediction_id='p1'),
                      dict(record_hash='validation',prediction_id='p2'),
                      dict(record_hash='blank-test',prediction_id='p3')]
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)
            # Spreadsheet exports commonly add a UTF-8 BOM to the first header.
            with (out/'manual_audit.csv').open('w',newline='',encoding='utf-8-sig') as handle:
                writer=csv.DictWriter(handle,fieldnames=['explanation_hash','supported_claims','total_factual_claims'])
                writer.writeheader()
                writer.writerows([
                    dict(explanation_hash='current-test',supported_claims='1',total_factual_claims='2'),
                    dict(explanation_hash='validation',supported_claims='99',total_factual_claims='100'),
                    dict(explanation_hash='blank-test',supported_claims='',total_factual_claims=''),
                    dict(explanation_hash='stale-hash',supported_claims='9',total_factual_claims='9')])
            result=audit_metrics(out,explanations,predictions)
            self.assertEqual(result['reviewed'],1)
            self.assertEqual(result['total_factual_claims'],2)
            self.assertEqual(result['unsupported_rate'],.5)


if __name__=='__main__':unittest.main()
