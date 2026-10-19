"""Private CPU-default Transformers API with legacy and variable-candidate scoring.

Start ONE process: python -m uvicorn server:app --host 127.0.0.1 --port 8000
Keep the service on localhost and reach it through an SSH tunnel. The model is
loaded at application startup, never when this module is merely imported.

/score returns next-token scores normalized across A, B, C, and D. These are
conditional label scores, NOT calibrated customer-choice probabilities.
"""

from __future__ import annotations

import inspect
import hashlib
import importlib.metadata
import logging
import os
from pathlib import Path
import re
import secrets
import threading
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Annotated, Any

import torch
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from huggingface_hub import HfApi, snapshot_download
from pydantic import BaseModel, ConfigDict, Field
from transformers import AutoModelForCausalLM, AutoTokenizer, GenerationConfig
from choice_trust.scoring import contextual_tokens, normalize_log_scores, autoregressive_log_score


LOGGER = logging.getLogger("choice_model")
LABELS = ("A", "B", "C", "D")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def positive_integer_env(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer.") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


@dataclass(frozen=True)
class Settings:
    model_id: str
    requested_revision: str
    api_key: str
    max_input_tokens: int
    explanation_tokens: int
    allow_cpu: bool
    device: str = "cpu"

    @classmethod
    def from_environment(cls) -> "Settings":
        api_key = os.environ.get("MODEL_API_KEY", "")
        if len(api_key) < 24:
            raise RuntimeError(
                "Set MODEL_API_KEY to a random secret of at least 24 characters "
                "before starting the server. Do not put it in source code."
            )
        return cls(
            model_id=os.environ.get("MODEL_ID", "Qwen/Qwen3-1.7B"),
            requested_revision=os.environ.get("MODEL_REVISION",
                "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
                if os.environ.get("MODEL_ID", "Qwen/Qwen3-1.7B") == "Qwen/Qwen3-1.7B" else "main"),
            api_key=api_key,
            max_input_tokens=positive_integer_env("MAX_INPUT_TOKENS", 4096),
            explanation_tokens=positive_integer_env("MAX_EXPLANATION_TOKENS", 600),
            allow_cpu=os.environ.get("ALLOW_CPU", "1") == "1",
            device=os.environ.get("MODEL_DEVICE", "cpu"),
        )


class PromptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=200_000)


class CandidateRequest(PromptRequest):
    answers: dict[str, str] = Field(min_length=2, max_length=256)


class ModelEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = threading.Lock()
        if settings.device not in ("cpu", "cuda"):
            raise RuntimeError("MODEL_DEVICE must be cpu or cuda")
        if settings.device == "cuda" and torch.cuda.is_available():
            self.device = torch.device("cuda:0")
            self.dtype = (
                torch.bfloat16
                if torch.cuda.is_bf16_supported()
                else torch.float16
            )
        elif settings.allow_cpu and settings.device == "cpu":
            # Default deployment: Qwen3-1.7B on CPU, float32; no GPU required.
            self.device = torch.device("cpu")
            self.dtype = torch.float32
        else:
            raise RuntimeError(
                "Requested device unavailable. Default deployment uses MODEL_DEVICE=cpu and ALLOW_CPU=1."
            )

        # Resolve mutable main/tag references exactly once. A provided commit can
        # also use an already cached snapshot when Hugging Face is offline.
        if COMMIT_PATTERN.fullmatch(settings.requested_revision):
            self.revision = settings.requested_revision
        else:
            info = HfApi().model_info(
                settings.model_id, revision=settings.requested_revision
            )
            self.revision = info.sha
            if not self.revision or not COMMIT_PATTERN.fullmatch(self.revision):
                raise RuntimeError("Could not resolve the model to an immutable commit.")

        snapshot = snapshot_download(
            repo_id=settings.model_id,
            revision=self.revision,
            allow_patterns=[
                "*.json", "*.safetensors", "*.model", "*.txt", "*.jinja", "*.tiktoken"
            ],
        )
        self.tokenizer = AutoTokenizer.from_pretrained(
            snapshot, local_files_only=True, trust_remote_code=False
        )
        # A single device avoids silently offloading part of an 8B model to CPU.
        self.model = AutoModelForCausalLM.from_pretrained(
            snapshot,
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            torch_dtype=self.dtype,
            device_map={"": str(self.device)},
            low_cpu_mem_usage=True,
            attn_implementation="sdpa",
        ).eval()

        self.context_limit = int(
            getattr(self.model.config, "max_position_embeddings", 32768)
        )
        if settings.max_input_tokens + settings.explanation_tokens > self.context_limit:
            raise RuntimeError(
                "MAX_INPUT_TOKENS + MAX_EXPLANATION_TOKENS exceeds the model's "
                f"context limit ({self.context_limit})."
            )

        self.label_ids: dict[str, int] = {}
        for label in LABELS:
            ids = self.tokenizer.encode(label, add_special_tokens=False)
            if len(ids) != 1:
                raise RuntimeError(
                    f"Label {label!r} is not a single token for this tokenizer. "
                    "Use Qwen3 with the supplied experiment."
                )
            self.label_ids[label] = ids[0]
        if len(set(self.label_ids.values())) != len(LABELS):
            raise RuntimeError("Choice labels do not map to distinct tokens.")

        # Qwen3 supports logits_to_keep: calculate only final-position vocabulary
        # logits, avoiding a large [prompt_length, vocabulary_size] allocation.
        parameters = inspect.signature(self.model.forward).parameters
        if "logits_to_keep" in parameters:
            self.last_logit_kwargs = {"logits_to_keep": 1}
        elif "num_logits_to_keep" in parameters:
            self.last_logit_kwargs = {"num_logits_to_keep": 1}
        else:
            raise RuntimeError(
                "This model does not support last-position-only logits. "
                "Use Qwen3 and the documented Transformers version range."
            )

        self._prepare_input("Return exactly one letter: A, B, C, or D.", reserve=1)
        LOGGER.info(
            "Ready: %s at revision %s on %s (%s)",
            settings.model_id, self.revision, self.device, self.dtype,
        )

    def metadata(self) -> dict[str, str]:
        return {"model_id": self.settings.model_id, "revision": self.revision}

    def _prepare_input(
        self, prompt: str, *, reserve: int
    ) -> tuple[str, dict[str, torch.Tensor]]:
        rendered = self.tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = self.tokenizer(
            rendered, add_special_tokens=False, return_tensors="pt", truncation=False
        )
        length = inputs["input_ids"].shape[-1]
        if length > self.settings.max_input_tokens or length + reserve > self.context_limit:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Prompt has {length} tokens; maximum input is "
                    f"{self.settings.max_input_tokens}. Nothing was truncated. "
                    "Shorten the prompt or increase MAX_INPUT_TOKENS if memory allows."
                ),
            )
        return rendered, {key: value.to(self.device) for key, value in inputs.items()}

    def score(self, prompt: str) -> dict[str, Any]:
        with self.lock, torch.inference_mode():
            rendered, inputs = self._prepare_input(prompt, reserve=1)
            prefix_ids = inputs["input_ids"][0].tolist()
            # Check in the actual context, not just label.encode(): BPE merges can
            # otherwise invalidate a next-token comparison for some templates.
            for label, token_id in self.label_ids.items():
                extended = self.tokenizer.encode(
                    rendered + label, add_special_tokens=False
                )
                if extended != prefix_ids + [token_id]:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Label {label} is not one next token in this context.",
                    )

            output = self.model(**inputs, use_cache=False, **self.last_logit_kwargs)
            logits = output.logits[0, -1].float()
            label_logits = logits[[self.label_ids[label] for label in LABELS]]
            probabilities = torch.softmax(label_logits, dim=-1).cpu().tolist()
            # This diagnostic reveals how much unconditioned next-token mass was
            # assigned to the four permitted labels before renormalization.
            label_mass = torch.exp(
                torch.logsumexp(label_logits, dim=-1)
                - torch.logsumexp(logits, dim=-1)
            ).item()
            result = dict(zip(LABELS, probabilities))
            return {
                "probabilities": result,
                "prediction": max(result, key=result.get),
                "raw_label_probability_mass": label_mass,
                "input_tokens": len(prefix_ids),
                "score_method": "next_token_softmax_conditioned_on_A_B_C_D",
                **self.metadata(),
            }

    def score_candidates(self, prompt: str, answers: dict[str, str]) -> dict[str, Any]:
        """Exact teacher-forced answer sequence likelihoods; no length averaging.

        Fast path uses one forward pass for single-token labels. Multi-token labels
        reuse prefix evaluations and sum conditional token log probabilities. This
        intentionally trades CPU latency for bounded last-position logits memory.
        """
        with self.lock, torch.inference_mode():
            rendered, inputs = self._prepare_input(prompt, reserve=1)
            prefix = inputs["input_ids"][0].tolist()
            try:
                tokens = contextual_tokens(self.tokenizer, rendered, prefix, answers)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=str(error)) from error
            longest = max(map(len, tokens.values()))
            if len(prefix) + longest > self.context_limit:
                raise HTTPException(status_code=413, detail="Answer sequence exceeds context limit")
            # Collect only required next tokens for every prefix, then one forward
            # per distinct prefix. Do not retain vocabulary logits across prefixes.
            needed = {}
            for suffix in tokens.values():
                for i, token in enumerate(suffix):
                    needed.setdefault(tuple(suffix[:i]), set()).add(token)
            log_values = {}
            for suffix_prefix, next_tokens in needed.items():
                ids = torch.tensor([prefix + list(suffix_prefix)], device=self.device)
                output = self.model(input_ids=ids, attention_mask=torch.ones_like(ids),
                                    use_cache=False, **self.last_logit_kwargs)
                logp = torch.log_softmax(output.logits[0, -1].float(), dim=-1)
                for token in next_tokens:
                    log_values[(tuple(prefix) + suffix_prefix, token)] = logp[token].item()
            logs = {cid: autoregressive_log_score(prefix, suffix,
                        lambda context, token: log_values[(tuple(context), token)])
                    for cid, suffix in tokens.items()}
            scores = normalize_log_scores(logs)
            return {"scores": scores, "prediction": max(sorted(scores), key=scores.get),
                    "answer_log_likelihoods": logs, "answer_token_ids": tokens,
                    "answer_token_counts": {k: len(v) for k, v in tokens.items()},
                    "input_tokens": len(prefix), "normalization": "sum_token_logp_then_softmax_across_answers; no length averaging",
                    "score_method": "candidate_sequence_conditional_likelihood_v2", **self.metadata()}

    def explain(self, prompt: str) -> dict[str, Any]:
        with self.lock, torch.inference_mode():
            _, inputs = self._prepare_input(
                prompt, reserve=self.settings.explanation_tokens
            )
            input_length = inputs["input_ids"].shape[-1]
            # Explicit config avoids inheriting sampling defaults from the model.
            # Greedy decoding is a fixed experimental protocol, not a claim that
            # it is the manufacturer's best-quality sampling configuration.
            generation = GenerationConfig(
                max_new_tokens=self.settings.explanation_tokens,
                do_sample=False,
                num_beams=1,
                use_cache=True,
                eos_token_id=self.model.generation_config.eos_token_id,
                pad_token_id=(
                    self.tokenizer.pad_token_id
                    if self.tokenizer.pad_token_id is not None
                    else self.tokenizer.eos_token_id
                ),
                bos_token_id=self.tokenizer.bos_token_id,
            )
            generated = self.model.generate(
                **inputs,
                generation_config=generation,
                **self.last_logit_kwargs,
            )
            new_ids = generated[0, input_length:]
            text = self.tokenizer.decode(new_ids, skip_special_tokens=True).strip()
            # No repair or invented JSON is performed here. The client retains
            # invalid/truncated responses as measurable explanation failures.
            eos = generation.eos_token_id
            eos_ids = {eos} if isinstance(eos, int) else set(eos or [])
            stopped = bool(len(new_ids) and new_ids[-1].item() in eos_ids)
            return {
                "text": text,
                "input_tokens": input_length,
                "output_tokens": len(new_ids),
                "finish_reason": "stop" if stopped else "length",
                **self.metadata(),
            }


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_environment()
    app.state.settings = settings
    app.state.engine = ModelEngine(settings)
    yield
    del app.state.engine
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


app = FastAPI(
    title="Customer choice research model",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)
bearer = HTTPBearer(auto_error=False)


def authenticate(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer)
    ],
) -> None:
    expected = request.app.state.settings.api_key
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(
            credentials.credentials.encode("utf-8"), expected.encode("utf-8")
        )
    ):
        raise HTTPException(
            status_code=401,
            detail="A valid MODEL_API_KEY bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def handle_model_call(engine: ModelEngine, method: str, prompt: str) -> dict[str, Any]:
    try:
        return getattr(engine, method)(prompt)
    except torch.cuda.OutOfMemoryError as error:
        torch.cuda.empty_cache()
        raise HTTPException(
            status_code=503,
            detail=(
                "GPU memory exhausted. Use a shorter prompt or reduce "
                "MAX_INPUT_TOKENS / MAX_EXPLANATION_TOKENS; run one server worker."
            ),
        ) from error


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    engine = request.app.state.engine
    return {
        "status": "ready",
        **engine.metadata(),
        "device": str(engine.device),
        "dtype": str(engine.dtype),
        "max_input_tokens": engine.settings.max_input_tokens,
        "max_explanation_tokens": engine.settings.explanation_tokens,
        "context_limit": engine.context_limit,
        "enable_thinking": False,
        "labels": list(LABELS),
        "capabilities": {"scores": True, "variable_candidates": True, "explanations": True,
                         "multi_token_labels": True, "max_candidates": 256},
        "scoring_helper_sha256": hashlib.sha256((Path(__file__).parent / "choice_trust" / "scoring.py").read_bytes()).hexdigest(),
        "server_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": sys.version.split()[0],
        "packages": {name: importlib.metadata.version(name) for name in (
            "torch", "transformers", "accelerate", "huggingface-hub", "fastapi"
        )},
    }


@app.post("/score", dependencies=[Depends(authenticate)])
def score(payload: PromptRequest, request: Request) -> dict[str, Any]:
    return handle_model_call(request.app.state.engine, "score", payload.prompt)


@app.post("/explain", dependencies=[Depends(authenticate)])
def explain(payload: PromptRequest, request: Request) -> dict[str, Any]:
    return handle_model_call(request.app.state.engine, "explain", payload.prompt)


@app.post("/score_candidates", dependencies=[Depends(authenticate)])
def score_candidates(payload: CandidateRequest, request: Request) -> dict[str, Any]:
    return request.app.state.engine.score_candidates(payload.prompt, payload.answers)
