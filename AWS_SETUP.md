# Existing CPU model server

For the inspected instance at `54.252.237.68`, use the **[exact LOCAL/AWS deployment commands](docs/AWS_CPU_DEPLOY.md)**. The existing environment is `~/customer-choice-trust/.venv`; all required dependencies are installed. The current remote failure is the missing `choice_trust` package required by `server.py`.

The working saved runs identify Qwen3-1.7B, CPU float32, revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`. The expected instance is your existing m7i.xlarge; its instance type was not independently verified. **No new instance or GPU is needed.** The earlier GPU guide is archived at [docs/AWS_GPU_LEGACY.md](docs/AWS_GPU_LEGACY.md).

The laptop's `.env` and API key are unchanged. Keep your existing SSH access, server environment and key. Do not publish `.env`, SSH private keys, or server credentials. The server binds to loopback and is reached through your existing SSH tunnel.

## Update code on your existing server

The legacy `/score`, `/explain`, `/health` routes remain. `/score_candidates` adds variable candidate sets and sequence scoring. Transfer `server.py` and the `choice_trust/` directory together. The server imports only `choice_trust/__init__.py` and `choice_trust/scoring.py`; it does not need the analysis client or its data.

Activate the existing remote Python environment. Preserve its working packages; do not recreate it or reinstall Torch just for this upgrade. The recorded Transformers 4.57.6 supports Qwen3 and last-position logits. For a **fresh CPU environment only**, install CPU Torch separately, then the server dependencies:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-server.txt
```

No packages were installed or changed on your EC2 instance by this upgrade. Dependency ranges are not a newly validated lockfile; retain the working environment lock.

## Start or restart the model

In the existing remote server terminal, with `MODEL_API_KEY` already securely exported:

```bash
export MODEL_ID=Qwen/Qwen3-1.7B
export MODEL_REVISION=70d244cc86ccca08cf5af4e1e306ecf908b1ad5e
export MODEL_DEVICE=cpu
export ALLOW_CPU=1
export MAX_INPUT_TOKENS=4096
export MAX_EXPLANATION_TOKENS=600
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1
```

These are now the defaults, including the pinned revision for this model. `MODEL_API_KEY` must contain at least 24 characters and is never logged. `server.py` does not automatically read a `.env`; preserve the environment-loading method already used on your server. Do not paste your key into source files or commands shared publicly.

On the laptop, recreate your usual tunnel, substituting your existing key and host:

```bash
ssh -i /path/to/existing-key.pem -N -L 8000:127.0.0.1:8000 ubuntu@YOUR_EXISTING_EC2_HOST
```

In another local VS Code terminal:

```bash
source .venv/bin/activate
python -m choice_trust health
```

Expect CPU, float32, the pinned model revision and `capabilities.variable_candidates: true`. A legacy server omits that capability and can still run four-candidate v2 cases through `/score`. No server accepts silent input truncation; oversized inputs return HTTP 413. Generic label boundary/tokenization failures return HTTP 422. Authentication remains bearer-token based.

Single-token labels share one scoring forward pass. Multi-token labels sum conditional log probabilities and require extra sequential forward passes; this can be slow on CPU. The server keeps only final-position vocabulary logits and never silently changes precision or offloads to a GPU. Explicit opt-in `MODEL_DEVICE=cuda` retains optional GPU support, but is not part of the default protocol.

Changing server code/settings changes the run identity. Start a new output folder after updating. Record a fresh `python -m pip freeze > server-environment-lock-v2.txt` only after the real smoke test succeeds.

The health request during implementation returned connection refused. Start the existing server/tunnel before running the bounded smoke commands in the README. No live upgraded inference has been verified yet.
