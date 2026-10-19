"""Execute the actual server scoring method with tiny deterministic tensor doubles.

This tests indexing, sequence accumulation and per-prefix forwards without loading
Torch or downloading model weights. Real Qwen inference still needs the endpoint.
"""
import ast
from contextlib import nullcontext
import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from choice_trust.scoring import contextual_tokens,normalize_log_scores,autoregressive_log_score

class Scalar(float):
    def item(self):return float(self)
class Vector(list):
    def float(self):return self
    def __getitem__(self,i):return Scalar(super().__getitem__(i))
class Logits:
    def __init__(self,values):self.values=values
    def __getitem__(self,i):
        assert i==(0,-1)
        return Vector(self.values)
class Row(list):
    def tolist(self):return list(self)
class Tensor(list):
    def __getitem__(self,i):return Row(super().__getitem__(i))
class FakeTorch:
    def inference_mode(self):return nullcontext()
    def tensor(self,x,device):return Tensor(x)
    def ones_like(self,x):return x
    def log_softmax(self,x,dim):
        m=max(x);z=m+math.log(sum(math.exp(v-m) for v in x))
        return Vector([v-z for v in x])
class Tokenizer:
    def encode(self,text,**kwargs):
        return {'prompt:':[1,2],'prompt:X':[1,2,3],'prompt:YZ':[1,2,2,4],'prompt:Y':[1,2,2]}[text]
class HttpError(Exception):
    def __init__(self,**kwargs):super().__init__(kwargs)

class ServerScoringTests(unittest.TestCase):
    def setUp(self):
        source=Path(__file__).resolve().parents[1]/'server.py'
        tree=ast.parse(source.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ModelEngine')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='score_candidates')
        module=ast.Module(body=[method],type_ignores=[])
        ns=dict(torch=FakeTorch(),Any=object,HTTPException=HttpError,contextual_tokens=contextual_tokens,
                normalize_log_scores=normalize_log_scores,autoregressive_log_score=autoregressive_log_score)
        exec(compile(ast.fix_missing_locations(module),str(source),'exec'),ns)
        self.method=ns['score_candidates'];self.calls=[]
        def forward(**kwargs):
            ids=kwargs['input_ids'][0];self.calls.append(list(ids))
            probs=[.05,.1,.2,.4,.25] if len(ids)==2 else [.1,.1,.1,.1,.6]
            return SimpleNamespace(logits=Logits([math.log(v) for v in probs]))
        self.engine=SimpleNamespace(lock=nullcontext(),tokenizer=Tokenizer(),device='cpu',context_limit=20,
            last_logit_kwargs={'logits_to_keep':1},model=forward,
            _prepare_input=lambda prompt,reserve:('prompt:',{'input_ids':Tensor([[1,2]])}),
            metadata=lambda:{'model_id':'tiny-test','revision':'test'})
    def test_multi_token_server_score(self):
        result=self.method(self.engine,'prompt',{'candidate-x':'X','candidate-y':'YZ'})
        self.assertAlmostEqual(result['scores']['candidate-x'],.4/(.4+.2*.6))
        self.assertEqual(result['prediction'],'candidate-x')
        self.assertEqual(result['answer_token_counts'],{'candidate-x':1,'candidate-y':2})
        self.assertEqual(self.calls,[[1,2],[1,2,2]])
    def test_single_token_server_fast_path(self):
        result=self.method(self.engine,'prompt',{'x':'X','y':'Y'})
        self.assertAlmostEqual(result['scores']['x'],2/3)
        self.assertEqual(len(self.calls),1)
    def test_input_context_limit_no_truncation(self):
        self.engine.context_limit=3
        with self.assertRaises(HttpError):self.method(self.engine,'prompt',{'x':'X','y':'YZ'})
        self.assertFalse(self.calls)

if __name__=='__main__':unittest.main()
