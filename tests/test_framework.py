"""Integrity regressions for the v2 framework; standard library only."""
import copy
import csv
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from choice_trust.adapters import generic,prepare,assign_splits,fit_policies,yogurt
from choice_trust.schema import validate_cases,masked
from choice_trust.model import prompt,MockBackend,RemoteBackend,parse_explanation
from choice_trust.scoring import answer_labels,contextual_tokens,autoregressive_log_score,normalize_log_scores,validate_prediction
from choice_trust.interventions import edit,systematic,explanation_tests,apply,measurements
from choice_trust.storage import digest,append,atomic_json,load_run,records,seal,writer_lock
from choice_trust.runner import run
from choice_trust.evaluation import metric_rows,estimate,temperature_fit,analyze
from choice_trust.dashboard import build,safe_json,scrub
from choice_trust.legacy import import_legacy

ROOT=Path(__file__).resolve().parents[1]

def fixtures():
    cfg=json.loads((ROOT/'examples/products.config.json').read_text())
    return fit_policies(generic(ROOT/'examples/products.jsonl',cfg)),cfg


class SchemaTests(unittest.TestCase):
    def setUp(self): self.cases,self.cfg=fixtures();self.case=self.cases[0]
    def test_outcome_and_post_decision_fields_cannot_enter_prompt(self):
        changed=copy.deepcopy(self.case);changed.update(outcome='LEAK',post_decision='LEAK',target='LEAK')
        self.assertEqual(prompt(changed),prompt(self.case));self.assertNotIn('LEAK',prompt(changed))
        changed['evidence'][0]['pre_decision']=False
        with self.assertRaises(ValueError):validate_cases([changed])
    def test_outcome_column_not_allowed_as_attribute(self):
        self.cfg['attributes'][0]['column']='outcome'
        with self.assertRaisesRegex(ValueError,'Outcome column'):generic(ROOT/'examples/products.jsonl',self.cfg)
    def test_variable_counts_and_csv_jsonl_equivalence(self):
        self.assertEqual({len(c['candidates']) for c in self.cases},{2,5,7})
        self.assertEqual(self.cases,fit_policies(generic(ROOT/'examples/products.csv',self.cfg)))
    def test_yogurt_legacy_adapter_preserves_ids_and_splits(self):
        from prepare_data import build_cases
        source=[dict(source_row=h*8+i+1,household_id=str(h),
                     prices={label:4+j+i/10 for j,label in enumerate('ABCD')},
                     ads={label:label=='A' for label in 'ABCD'},choice='ABCD'[h%4])
                for h in range(10) for i in range(8)]
        rows,_=build_cases(source,seed=42)
        new=yogurt(rows)
        self.assertEqual([c['case_id'] for c in new],[c['case_id'] for c in rows])
        self.assertEqual([c['split'] for c in new],[c['split'] for c in rows])
        self.assertEqual(set(answer_labels([x['id'] for x in new[0]['candidates']]).values()),set('ABCD'))
        self.assertEqual(new[0]['outcome'],rows[0]['target'])
    def test_group_splits_and_no_query_history(self):
        changed=copy.deepcopy(self.cases);changed[-1]['group_id']=changed[0]['group_id']
        with self.assertRaisesRegex(ValueError,'Group overlap'):validate_cases(changed)
        changed=copy.deepcopy(self.cases);changed[0]['evidence'][-1]['observation_id']=changed[1]['case_id']
        with self.assertRaisesRegex(ValueError,'Query observations'):validate_cases(changed)
    def test_auto_group_splits_and_temporal_absence(self):
        changed=copy.deepcopy(self.cases)
        for c in changed:c['split']=None
        with self.assertRaisesRegex(ValueError,'explicit ISO'):assign_splits(changed,{'split_strategy':'temporal'})
        assign_splits(changed,{'seed':42});validate_cases(changed)
        self.assertEqual(set(c['split'] for c in changed),{'development','validation','test'})
    def test_preprocessing_only_development(self):
        original=copy.deepcopy(self.cases[0]['evidence'][0]['policy']['development_bounds'])
        changed=copy.deepcopy(self.cases);changed[-1]['evidence'][0]['value']=1e8
        fit_policies(changed)
        self.assertEqual(changed[0]['evidence'][0]['policy']['development_bounds'],original)
    def test_text_adapter_reuses_prediction_without_outcome(self):
        cfg=json.loads((ROOT/'examples/text.config.json').read_text())
        cases=generic(ROOT/'examples/text.jsonl',cfg)
        self.assertEqual(cases[0]['task'],'classification')
        result=MockBackend().predict(cases[0]);validate_prediction(result,['positive','negative'])
        changed=copy.deepcopy(cases[0]);changed['outcome']='HIDDEN_QUERY_OUTCOME'
        self.assertEqual(prompt(changed),prompt(cases[0]))


class ScoringTests(unittest.TestCase):
    def test_mapping_not_changed_by_order_and_more_than_26(self):
        ids=['id-'+str(i) for i in range(40)]
        self.assertEqual(answer_labels(ids),answer_labels(list(reversed(ids))))
        self.assertEqual(len(set(answer_labels(ids).values())),40)
        self.assertIn('AA',answer_labels(ids).values())
    def test_sequence_scoring_conditions_on_prior_answer_tokens(self):
        calls=[]
        def next_log(context,token):
            calls.append((context[:],token));return math.log(.8 if token==2 else .25)
        value=autoregressive_log_score([0],[2,3],next_log)
        self.assertAlmostEqual(value,math.log(.8*.25))
        self.assertEqual(calls,[([0],2),([0,2],3)])
        scores=normalize_log_scores({'x':value,'y':math.log(.1)})
        self.assertAlmostEqual(scores['x'],2/3)
    def test_context_tokenization_and_prefix_collision(self):
        class Tok:
            def encode(self,s,**kw):return list(s.encode())
        t=Tok();prefix=list(b'prompt:')
        self.assertEqual(contextual_tokens(t,'prompt:',prefix,{'a':'A','b':'BB'})['b'],[66,66])
        with self.assertRaisesRegex(ValueError,'prefix-free'):contextual_tokens(t,'prompt:',prefix,{'a':'A','b':'AA'})
        self.assertEqual(len(contextual_tokens(t,'prompt:',prefix,{'a':'A\n','b':'AA\n'})),2)
        with self.assertRaisesRegex(ValueError,'boundary'):contextual_tokens(t,'prompt:',[0],{'a':'A','b':'B'})
    def test_missing_scores_allowed_invalid_or_invented_scores_rejected(self):
        validate_prediction({'prediction':'x','scores':None},['x','y'])
        for scores in ({'x':.7,'y':.7},{'x':float('nan'),'y':.2},{'x':.5,'z':.5}):
            with self.assertRaises(ValueError):validate_prediction({'prediction':'x','scores':scores},['x','y'])
    def test_prediction_only_backend_ignores_self_reported_confidence(self):
        b=RemoteBackend.__new__(RemoteBackend)
        b.capabilities={'scores':False,'variable_candidates':True}
        b.check_identity=lambda r:None
        cases,_=fixtures(); cid=cases[0]['candidates'][0]['id']
        b.request=lambda route,payload:dict(prediction=cid,scores={cid:1},confidence=.99)
        self.assertIsNone(b.predict(cases[0])['scores'])


class InterventionTests(unittest.TestCase):
    def setUp(self):self.cases,_=fixtures();self.case=self.cases[0];self.backend=MockBackend()
    def test_candidate_preservation_and_edit_isolation(self):
        original=copy.deepcopy(self.case);e=self.case['evidence'][0]
        changed,error=edit(self.case,e['id'],12)
        self.assertIsNone(error);self.assertEqual(self.case,original)
        self.assertIsNone(changed['outcome']);self.assertEqual(changed['candidates'],self.case['candidates'])
        diffs=[(a,b) for a,b in zip(self.case['evidence'],changed['evidence']) if a!=b]
        self.assertEqual(len(diffs),1)
        masked_case=masked(self.case,{e['id']},keep=True)
        self.assertEqual(masked_case['candidates'],self.case['candidates'])
        self.assertIn('NOT_PROVIDED',prompt(masked_case))
    def test_bounds_and_cross_field_constraints(self):
        eid=self.case['evidence'][0]['id']
        self.assertIn('bounds',edit(self.case,eid,100000)[1])
        c=copy.deepcopy(self.case);c['constraints']=[{'left':'price','op':'le','right':'battery_hours'}]
        self.assertIn('constraint',edit(c,eid,12)[1])
    def test_invalid_missing_abstaining_and_truncated_explanations(self):
        facts={e['id']:e for e in self.case['evidence']}
        invalid=parse_explanation({'text':'{"evidence_ids":["imaginary"],"explanation":"wrong citation"}'},facts)
        self.assertTrue(invalid['parse_ok']);self.assertFalse(invalid['citation_valid'])
        self.assertFalse(parse_explanation({'text':''},facts)['parse_ok'])
        abstain=parse_explanation({'text':'{"evidence_ids":[],"explanation":"cannot defend"}'},facts)
        self.assertTrue(abstain['abstained'])
        self.assertTrue(all(s.get('skip_reason') for s in explanation_tests(self.case,'full',None,5,42)))
        self.assertTrue(all(s.get('skip_reason') for s in explanation_tests(self.case,'full',dict(abstain,truncated=True),5,42)))
    def test_matched_controls_and_grid_independent_of_explanation(self):
        facts={e['id']:e for e in self.case['evidence']}
        raw=self.backend.explain(self.case,'full','device-1');explanation=parse_explanation(raw,facts)
        specs=explanation_tests(self.case,'full',explanation,5,42)
        ids=explanation['parsed']['evidence_ids'];types=sorted(facts[i]['type'] for i in ids)
        controls=[s for s in specs if s['kind']=='random_remove'];self.assertEqual(len(controls),5)
        for s in controls:self.assertEqual(sorted(facts[i]['type'] for i in s['evidence_ids']),types)
        self.assertEqual(systematic(self.case,'full'),systematic(self.case,'full'))
    def test_fixed_original_reference_when_winner_changes(self):
        result=measurements({'prediction':'a','scores':{'a':.6,'b':.3,'c':.1}}, {'prediction':'c','scores':{'a':.1,'b':.2,'c':.7}})
        self.assertEqual(result['reference_candidate'],'a');self.assertEqual(result['fixed_rival'],'b')
        self.assertAlmostEqual(result['score_change'],-.5)
        self.assertAlmostEqual(result['margin_change'],math.log(.1/.2)-math.log(.6/.3))
        self.assertTrue(result['winner_changed'])
        missing=measurements({'prediction':'a','scores':None},{'prediction':'b','scores':None})
        self.assertIsNone(missing['score_change']);self.assertTrue(missing['winner_changed'])


class EvaluationTests(unittest.TestCase):
    def test_variable_count_metrics_and_unavailable_scores(self):
        rows=[dict(prediction='a',outcome='b',group_id='g1',scores={'a':.5,'b':.5}),
              dict(prediction='x',outcome='x',group_id='g2',scores=None)]
        m=metric_rows(rows,20)
        self.assertEqual(m['accuracy']['mean'],.5);self.assertEqual(m['scored_n'],1)
        self.assertAlmostEqual(m['mrr']['mean'],1/1.5)
        self.assertAlmostEqual(m['brier_sum']['mean'],.5)
        self.assertEqual(m['unavailable_scores'],1)
        self.assertEqual(m['error_vs_coverage'][0]['n'],1)
    def test_cluster_uncertainty_and_validation_only_fit(self):
        self.assertIsNone(estimate([(1,'g'),(0,'g')],20)['ci95'])
        rows=[dict(split='validation',scores={'a':.9,'b':.1},outcome='b')]
        fit=temperature_fit(rows)
        rows.append(dict(split='test',scores={'a':.99,'b':.01},outcome='a'))
        self.assertEqual(temperature_fit(rows),fit)
        self.assertIsNone(temperature_fit(rows[1:])['temperature'])


class StorageEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        _,cfg=fixtures();prepare(ROOT/'examples/products.jsonl',self.root/'data',cfg)
        self.args=SimpleNamespace(cases=self.root/'data/cases.jsonl',out=self.root/'run',mock=True,seed=42,
            random_controls=2,permutations=2,conditions=['full'],split='all',limit=0,command='predict')
    def tearDown(self):self.tmp.cleanup()
    def stages(self):
        for name in ('predict','explain','counterfactuals'):self.args.command=name;run(self.args)
    def test_complete_workflow_resume_and_safe_html(self):
        self.stages();manifest,cases,data=load_run(self.args.out)
        self.assertEqual(len(data['predictions']),18);self.assertEqual(len(data['explanations']),18)
        self.assertTrue(data['interventions'])
        before=(self.args.out/'interventions.jsonl').read_bytes();run(self.args)
        self.assertEqual(before,(self.args.out/'interventions.jsonl').read_bytes())
        metrics=analyze(self.args.out,20);self.assertTrue(metrics['synthetic'])
        self.assertEqual(set(metrics['conditions']['full']['splits']['test']['candidate_counts']),{'2','5','7'})
        build(self.args.out)
        html=(self.args.out/'dashboard.html').read_text()
        self.assertIn('Counterfactual lab',html);self.assertNotIn('__RUN_DATA__',html)
        payload='</script><img src=x onerror=alert(1)>\u2028'
        encoded=safe_json({'value':payload});self.assertNotIn('<',encoded);self.assertEqual(json.loads(encoded)['value'],payload)
        self.assertEqual(scrub({'MODEL_API_KEY':'secret','text':'abcdefghijklmn'},['abcdefghijklmn']),{'text':'[REDACTED]'})
        for r in data['interventions']:
            self.assertIsNone(r['edited_outcome'])
            if r['after']:
                self.assertNotIn('saved model prediction',r['after']['prompt'])
                self.assertNotIn('explanation',r['after']['prompt'].lower())
    def test_protocol_change_and_concurrent_writer_rejected(self):
        run(self.args);self.args.seed=99
        with self.assertRaisesRegex(ValueError,'Incompatible'):run(self.args)
        with writer_lock(self.root/'locked'):
            with self.assertRaisesRegex(ValueError,'locked'):
                with writer_lock(self.root/'locked'):pass
    def test_changed_prediction_and_explanation_links_rejected(self):
        self.stages()
        path=self.args.out/'predictions.jsonl';rows=records(path)
        rows[0]['raw']={'changed':True};rows[0]=seal(rows[0]);path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'Source prediction changed'):load_run(self.args.out)
    def test_changed_explanation_and_tail_repair(self):
        self.stages();path=self.args.out/'explanations.jsonl';rows=records(path)
        rows[0]['raw']['text']='changed';rows[0]=seal(rows[0]);path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
        with self.assertRaisesRegex(ValueError,'Source explanation changed'):load_run(self.args.out)
        path=self.root/'tail.jsonl';row=seal(dict(record_id='a',value=1));path.write_text(json.dumps(row)+'\n{"partial":')
        self.assertEqual(records(path,True),[row])
    def test_manual_audit_blank_is_not_zero_and_counts_are_checked(self):
        self.stages();path=self.args.out/'manual_audit.csv'
        with path.open(newline='') as f: rows=list(csv.DictReader(f))
        rows[0]['supported_claims']='1';rows[0]['total_factual_claims']='2'
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        metrics=analyze(self.args.out,20)
        reviewed=sum(g['grounding']['reviewed'] for g in metrics['conditions']['full']['splits'].values())
        self.assertEqual(reviewed,1)
        rows[0]['supported_claims']='3'
        with path.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,'Invalid manual'):analyze(self.args.out,20)
    def test_legacy_import_preserves_sources_and_marks_missing_vectors(self):
        source=ROOT/'outputs_cpu_pilot'
        if not source.exists():self.skipTest('Optional local historical run absent')
        import hashlib
        original=hashlib.sha256((source/'predictions.jsonl').read_bytes()).hexdigest()
        out=self.root/'legacy'
        import_legacy(source,ROOT/'data/processed/cases.jsonl',out)
        manifest,cases,data=load_run(out)
        self.assertTrue(manifest['warnings']);self.assertEqual(len(data['predictions']),40)
        self.assertTrue(all(i['after'] is None for i in data['interventions']))
        self.assertEqual(original,hashlib.sha256((source/'predictions.jsonl').read_bytes()).hexdigest())
        self.assertTrue(any(e['citation_valid'] is False for e in data['explanations']))
    def test_case_snapshot_and_unsealed_records_rejected(self):
        run(self.args)
        path=self.args.out/'cases.jsonl';path.write_text('[]\n')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):load_run(self.args.out)
        path=self.root/'record.jsonl';path.write_text('{"record_id":"unsealed"}\n')
        with self.assertRaisesRegex(ValueError,'content changed'):records(path)


if __name__=='__main__':unittest.main()
