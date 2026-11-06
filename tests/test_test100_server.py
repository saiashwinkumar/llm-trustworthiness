"""Synthetic transport/journal checks; no model loading or real inference.

Handlers are called directly to avoid entering the base server lifespan. The
FastAPI auth dependency is therefore outside these tests' scope. All inputs and
responses below are explicitly synthetic fixtures, never experimental records.
"""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from choice_trust import test100_server as server


class FakeTokenizer:
    name_or_path = "synthetic-tokenizer-fixture"
    eos_token_id = 151645
    chat_template = "SYNTHETIC TEMPLATE; NOT THE MODEL TEMPLATE"

    def __init__(self):
        self.calls = []

    def apply_chat_template(self, messages, **kwargs):
        self.calls.append(kwargs)
        return "SYNTHETIC RENDERED INPUT\n" + json.dumps(messages, sort_keys=True)

    def encode(self, rendered, **kwargs):
        return [1] * 12


class FakeModel:
    generation_config = SimpleNamespace(eos_token_id=[151645, 151643])

    def generate(self, *args, **kwargs):
        raise AssertionError("No model inference is permitted in these tests")


class Test100ServerChecks(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        self.cid = "synthetic-case__with_history__ORIGINAL"
        self.entry = {
            "call_id": self.cid, "case_id": "synthetic-case", "condition": "with_history",
            "family": "ORIGINAL", "skip_reason": None,
            "messages": [{"role": "user", "content": "SYNTHETIC TEST FACTS; no target"}],
            "observations": {"version": "synthetic-fixture", "candidates": [{"id": "A", "name": "fixture brand"}], "text": "SYNTHETIC FACTS"},
        }
        self.manifest = {"plan_id": "synthetic-frozen-plan", "development_price_bounds_cents": [1, 1000], "entries": [self.entry]}
        self.tokenizer = FakeTokenizer()
        self.engine = SimpleNamespace(
            settings=SimpleNamespace(model_id=server.MODEL), revision=server.REVISION,
            tokenizer=self.tokenizer, model=FakeModel(), device="cpu", dtype="torch.float32", lock=Lock(),
        )
        self.request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(engine=self.engine)))
        self.raw = ' \n{\n  "explanation": "SYNTHETIC FIXTURE; NOT A MODEL RESULT.",\n  "evidence_ids": [],\n  "prediction": "A"\n}\t\n'
        self.result = {
            "messages": self.entry["messages"], "rendered_prompt": "SYNTHETIC RENDERED INPUT",
            "raw_response": self.raw,
            "parsed_result": {"explanation": "SYNTHETIC FIXTURE; NOT A MODEL RESULT.", "evidence_ids": [], "prediction": "A"},
            "diagnostics": {"parse_ok": True, "prediction_valid": True, "generation_truncated": False},
        }
        for name, value in (("OUT", self.out), ("CACHE", {})):
            patcher = patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        verifier_patch = patch.object(server, "verify_manifest", return_value=self.manifest)
        self.verify_manifest = verifier_patch.start()
        self.addCleanup(verifier_patch.stop)
        edit_patch = patch.object(server, "verify_edit", return_value={"regenerated": True})
        self.verify_edit = edit_patch.start()
        self.addCleanup(edit_patch.stop)
        generator_patch = patch.object(server, "generate_joint_response", side_effect=lambda *a, **k: deepcopy(self.result))
        self.generator = generator_patch.start()
        self.addCleanup(generator_patch.stop)

    def prepared(self):
        context = server.context(self.request)
        expected = server.signature(self.manifest, self.entry, context["runtime"], context["prompts"][self.cid]["rendered_prompt"])
        payload = server.GenerateRequest(plan_id=self.manifest["plan_id"], call_id=self.cid, input_signature=expected)
        return context, payload

    def assert_http(self, status, callback):
        with self.assertRaises(HTTPException) as caught:
            callback()
        self.assertEqual(caught.exception.status_code, status)

    def test_runtime_is_explicit_frozen_512_without_model_loading(self):
        context, _ = self.prepared()
        runtime = server.runtime(self.request)
        self.verify_manifest.assert_called_once_with(self.out)
        self.verify_edit.assert_called_once_with(self.entry, [1, 1000])
        self.generator.assert_not_called()
        self.assertEqual(runtime["plan_id"], self.manifest["plan_id"])
        self.assertEqual(runtime["model"]["revision"], server.REVISION)
        self.assertEqual(runtime["model"]["dtype"], "torch.float32")
        self.assertEqual(runtime["model"]["device"], "cpu")
        self.assertEqual(runtime["effective_settings"]["max_new_tokens"], 512)
        self.assertEqual(runtime["generation_config"]["max_new_tokens"], 512)
        self.assertFalse(runtime["effective_settings"]["do_sample"])
        self.assertFalse(runtime["effective_settings"]["enable_thinking"])
        self.assertEqual(runtime["effective_settings"]["num_beams"], 1)
        self.assertEqual(runtime["effective_settings"]["max_input_tokens"], 4096)
        self.assertEqual(context["config"].max_new_tokens, 512)
        self.assertEqual(self.tokenizer.calls, [{"tokenize": False, "add_generation_prompt": True, "enable_thinking": False}])
        self.assertFalse((self.out / "server_attempts").exists())
        self.assertEqual(json.loads((self.out / "rendered_prompts.json").read_text()), context["prompts"])

    def test_wrong_plan_call_or_signature_never_starts_request(self):
        _, good = self.prepared()
        invalid = [
            good.model_copy(update={"plan_id": "wrong-plan"}),
            good.model_copy(update={"call_id": "unknown-call"}),
            good.model_copy(update={"input_signature": "wrong-signature"}),
        ]
        for payload in invalid:
            with self.subTest(payload=payload.model_dump()):
                self.assert_http(400, lambda: server.generate(payload, self.request))
        self.generator.assert_not_called()
        self.assertFalse((self.out / "server_attempts").exists())

    def test_applicability_is_enforced_before_inference(self):
        _, payload = self.prepared()
        self.entry["skip_reason"] = "SYNTHETIC not-applicable decision"
        self.assert_http(400, lambda: server.generate(payload, self.request))
        self.generator.assert_not_called()
        self.assertFalse((self.out / "server_attempts").exists())

    def test_duplicate_post_blocked_and_exact_raw_whitespace_preserved(self):
        _, payload = self.prepared()
        def synthetic_after_journal(*args, **kwargs):
            journal = json.loads((self.out / "server_attempts" / f"{self.cid}.json").read_text())
            self.assertEqual(journal["status"], "running")
            self.assertEqual(journal["input_signature"], payload.input_signature)
            return deepcopy(self.result)
        self.generator.side_effect = synthetic_after_journal
        record = server.generate(payload, self.request)
        self.generator.assert_called_once()
        self.assertIs(self.generator.call_args.kwargs["model"], self.engine.model)
        self.assertEqual(self.generator.call_args.kwargs["generation_config"].max_new_tokens, 512)
        self.assertEqual(record["response"]["raw_response"], self.raw)
        path = self.out / "server_responses" / f"{self.cid}.json"
        original_bytes = path.read_bytes()
        self.assertEqual(json.loads(original_bytes)["response"]["raw_response"], self.raw)
        recovered = server.attempt(self.cid)
        self.assertEqual(recovered["status"], "completed")
        self.assertEqual(recovered["record"], record)
        self.assert_http(409, lambda: server.generate(payload, self.request))
        self.assertEqual(self.generator.call_count, 1)
        self.assertEqual(path.read_bytes(), original_bytes)
        state = json.loads((self.out / "server_attempts" / f"{self.cid}.json").read_text())
        self.assertEqual(state["status"], "completed")

    def test_failed_attempt_is_journaled_and_never_retried(self):
        _, payload = self.prepared()
        self.generator.side_effect = RuntimeError("SYNTHETIC infrastructure failure")
        self.assert_http(500, lambda: server.generate(payload, self.request))
        state = server.attempt(self.cid)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["error_type"], "RuntimeError")
        self.assertIn("no automatic retry", state["error"])
        self.assertFalse((self.out / "server_responses" / f"{self.cid}.json").exists())
        self.assert_http(409, lambda: server.generate(payload, self.request))
        self.assertEqual(self.generator.call_count, 1)

    def test_running_or_uncertain_attempts_block_automatic_retry(self):
        _, payload = self.prepared()
        path = self.out / "server_attempts" / f"{self.cid}.json"
        for state in ("running", "uncertain"):
            with self.subTest(state=state):
                journal = {"status": state, "call_id": self.cid, "input_signature": payload.input_signature}
                server.write_json(path, journal)
                original_bytes = path.read_bytes()
                self.assertEqual(server.attempt(self.cid), journal)
                self.assert_http(409, lambda: server.generate(payload, self.request))
                self.assertEqual(path.read_bytes(), original_bytes)
        self.generator.assert_not_called()

    def test_runtime_rejects_incompatible_engine_and_changed_prompt_cache(self):
        self.engine.dtype = "torch.float16"
        self.assert_http(409, lambda: server.context(self.request))
        self.generator.assert_not_called()
        self.engine.dtype = "torch.float32"
        self.prepared()
        cache = self.out / "rendered_prompts.json"
        cache.write_text(json.dumps({"wrong": "SYNTHETIC TAMPER"}))
        server.CACHE.clear()
        self.assert_http(409, lambda: server.context(self.request))
        self.generator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
