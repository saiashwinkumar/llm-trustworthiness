"""Offline continuation checks; use saved records, never call the model."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiment import read_jsonl
from choice_trust.storage import load_run
from scripts import run_resumed_study as resume


class ResumedStudyTests(unittest.TestCase):
    def test_real_phase_dispatch_builds_resumable_stage_without_inference(self):
        manifest,_,_=load_run(resume.ROOT/'outputs_resumed_v1')
        with patch.object(resume.sys, 'argv', ['run_resumed_study.py','development']), \
             patch.object(resume,'RemoteBackend',return_value=SimpleNamespace(
                 metadata=manifest['backend'],health=manifest['backend']['server_health'])), \
             patch.object(resume,'run_stage') as stage, patch.object(resume,'report'):
            resume.main()
        self.assertEqual(stage.call_count,1)
        definition,args,_,plan,_=stage.call_args.args
        self.assertEqual(definition['name'],'development_predictions')
        self.assertFalse(args.mock)
        self.assertEqual(len(definition['case_ids']),804)
        self.assertEqual(plan['random_controls'],5)

    def test_migration_preserves_provenance_and_is_idempotent(self):
        cases_path=resume.ROOT/'data_v2/yogurt/cases.jsonl'
        cases=read_jsonl(cases_path)
        sources, hashes=resume.source_data()
        predictions, explanations, effects, backend=resume.select_sources(cases,sources)
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(out=Path(directory)/'out',control=Path(directory)/'control',cases=cases_path)
            plan=resume.prepare(args,cases)
            _,_,data=load_run(args.out)
            self.assertEqual(len(data['predictions']),len(predictions))
            self.assertEqual(len(data['explanations']),len(explanations))
            self.assertEqual(len(data['interventions']),len(effects))
            for row in data['explanations']:
                self.assertEqual(row['raw'],row['original_record']['raw'])
                self.assertEqual(row['prompt'],row['original_record']['prompt'])
                self.assertEqual(row['reuse_origin']['source_record_hash'],row['original_record']['record_hash'])
            before={p.name:p.read_bytes() for p in args.out.glob('*') if p.is_file()}
            resume.prepare(args,cases)
            self.assertEqual(before,{p.name:p.read_bytes() for p in args.out.glob('*') if p.is_file()})
            old=json.loads((resume.ROOT/'execution_cpu_real_v3/study_plan.json').read_text())
            self.assertEqual(plan['stages'][1:],old['stages'])
            self.assertEqual(len(plan['citation_recovery_tasks']),12)
            self.assertTrue(all(t['source_run']=='outputs_cpu_real_v3_smoke' for t in plan['citation_recovery_tasks']))
            self.assertEqual(plan,resume.verify_plan(args,cases))
        for path,h in hashes.items():self.assertEqual(resume.sha(resume.ROOT/path),h)

    def test_prediction_reuse_checks_prompt_case_and_scoring(self):
        sources,_=resume.source_data()
        manifest,cases,data=sources['outputs_cpu_real_v3']
        p=data['predictions'][0];case=next(c for c in cases if c['case_id']==p['case_id'])
        self.assertTrue(resume.compatible_prediction(p,case,manifest['backend']))
        for key,value in [('prompt','changed'),('case_hash','changed'),('score_method','other')]:
            changed=copy.deepcopy(p);changed[key]=value
            self.assertFalse(resume.compatible_prediction(changed,case,manifest['backend']))


if __name__=='__main__':unittest.main()
