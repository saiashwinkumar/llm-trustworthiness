"""Deployment helpers never need real credentials, network, or model weights."""
import hashlib
from pathlib import Path
import unittest
from scripts.check_cpu_environment import plan
from scripts.verify_cpu_server import validate_health, validate_scores, MODEL, REVISION

ROOT = Path(__file__).resolve().parents[1]

class DeploymentTests(unittest.TestCase):
    def test_missing_only_plan_and_incompatible_versions(self):
        missing, incompatible = plan('transformers>=4.51,<5\nuvicorn>=0.30,<1\n# comment', {'transformers': '4.57.6'})
        self.assertEqual(missing, ['uvicorn>=0.30,<1'])
        self.assertFalse(incompatible)
        missing, incompatible = plan('transformers>=4.51,<5', {'transformers': '4.20.0'})
        self.assertFalse(missing)
        self.assertEqual(len(incompatible), 1)
    def test_health_requires_cpu_protocol_and_uploaded_helpers(self):
        health = dict(model_id=MODEL, revision=REVISION, device='cpu', dtype='torch.float32',
            max_input_tokens=4096, max_explanation_tokens=600, enable_thinking=False,
            capabilities=dict(scores=True, variable_candidates=True, multi_token_labels=True, explanations=True),
            server_code_sha256=hashlib.sha256((ROOT/'server.py').read_bytes()).hexdigest(),
            scoring_helper_sha256=hashlib.sha256((ROOT/'choice_trust/scoring.py').read_bytes()).hexdigest())
        validate_health(health)
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate_health(dict(health, scoring_helper_sha256='old'))
        with self.assertRaisesRegex(ValueError, 'device'):
            validate_health(dict(health, device='cuda:0'))
    def test_scoring_checks_candidate_ids_and_normalization(self):
        response = dict(model_id=MODEL, revision=REVISION, scores={'sku1': .7, 'sku9': .3}, prediction='sku1')
        validate_scores(response, {'sku1':'A', 'sku9':'B'})
        with self.assertRaisesRegex(ValueError, 'candidate IDs'):
            validate_scores(response, {'sku2':'A', 'sku9':'B'})
        with self.assertRaisesRegex(ValueError, 'normalized'):
            validate_scores(dict(response, scores={'sku1': .7, 'sku9': .5}), {'sku1':'A', 'sku9':'B'})

if __name__ == '__main__': unittest.main()
