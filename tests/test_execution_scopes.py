import copy
import unittest
from choice_trust.interventions import planned_specs
from test_framework import fixtures
from choice_trust.model import MockBackend,parse_explanation
from choice_trust.schema import visible_evidence
from experiment import digest

class ScopeTests(unittest.TestCase):
    def test_scopes_union_matches_all_and_preserves_specs(self):
        cases,_=fixtures();c=cases[0]
        e=parse_explanation(MockBackend().explain(c,'full','device-1'),visible_evidence(c))
        def specs(scope):return planned_specs(c,'full',e,5,42,2,scope)
        all_specs={digest(s) for s in specs('all')}
        self.assertEqual(all_specs,{digest(s) for s in specs('explanation')+specs('systematic')})
        self.assertTrue(all(s['kind'] not in ('attribute_sweep','categorical_toggle','history_mask') for s in specs('explanation')))
        self.assertTrue(any(s['kind']=='presentation' for s in specs('explanation')))
        self.assertTrue(all(s['kind'] not in ('cited_remove','cited_retain','explicit_claim') for s in specs('systematic')))
    def test_invalid_explanation_still_gets_presentation_tests(self):
        c=fixtures()[0][0]
        specs=planned_specs(c,'full',None,5,42,2,'explanation')
        self.assertTrue(any(s['kind']=='presentation' and not s.get('skip_reason') for s in specs))
        self.assertTrue(any(s['kind']=='cited_remove' and s.get('skip_reason') for s in specs))
