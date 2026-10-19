# Prepare the existing AWS CPU instance

Read-only SSH inspection on 17 October 2026 verified `ubuntu@54.252.237.68` and:

- Project: `/home/ubuntu/customer-choice-trust`
- Existing environment: `/home/ubuntu/customer-choice-trust/.venv`, Python 3.12.3
- Installed packages: torch 2.14.1+cpu, transformers 4.57.6, accelerate 1.15.0, huggingface-hub 0.36.2, safetensors 0.8.0, fastapi 0.143.3, pydantic 2.14.1, uvicorn 0.54.0
- `python -m pip check`: no broken requirements; dependency imports succeeded
- Nothing listening on TCP port 8000 at inspection time
- **Current remote import failure:** `server.py` imports `choice_trust.scoring`, but `choice_trust` is missing. Uploading `server.py` alone is insufficient.

No deployment, package installation, server start, or experiment was performed during preparation. The following commands are for you to execute. They do not copy or overwrite `.env`, `.venv`, prepared datasets, or pilot outputs.

## 1. LOCAL — upload the required code

Run in your Mac's VS Code terminal:

```bash
cd /Users/saiashwin/llm-trustworthiness
CPU_IP=54.252.237.68
SSH_KEY="$HOME/Downloads/llm-experiment.pem"

ssh -i "$SSH_KEY" "ubuntu@$CPU_IP" 'bash -s' <<'AWS'
set -e
cd "$HOME/customer-choice-trust"
backup_dir="server-code-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$backup_dir"
for file in server.py requirements-server.txt choice_trust/__init__.py choice_trust/scoring.py scripts/check_cpu_environment.py scripts/verify_cpu_server.py; do
    if [ -f "$file" ]; then
        mkdir -p "$backup_dir/$(dirname "$file")"
        cp -p "$file" "$backup_dir/$file"
    fi
done
mkdir -p choice_trust scripts
AWS

scp -i "$SSH_KEY" server.py requirements-server.txt "ubuntu@$CPU_IP:~/customer-choice-trust/"
scp -i "$SSH_KEY" choice_trust/__init__.py choice_trust/scoring.py "ubuntu@$CPU_IP:~/customer-choice-trust/choice_trust/"
scp -i "$SSH_KEY" scripts/check_cpu_environment.py scripts/verify_cpu_server.py "ubuntu@$CPU_IP:~/customer-choice-trust/scripts/"

ssh -i "$SSH_KEY" "ubuntu@$CPU_IP"
```

`server:app` is the FastAPI entry point. Its only project-local imported modules are `choice_trust/__init__.py` and `choice_trust/scoring.py`; the rest of the analysis package is not needed on AWS. The two scripts are deployment/verification helpers. The key file already has owner-read-only permissions; it is neither printed nor uploaded.

If you repeat this later and a server is running, stop that server with Ctrl+C in its original terminal before restarting. Do not launch a second copy or kill unrelated Python processes. This upload preserves a timestamped backup of replaced source files only.

## 2. AWS — activate the existing environment and check dependencies

In the SSH terminal:

```bash
cd ~/customer-choice-trust
source .venv/bin/activate
python --version
python scripts/check_cpu_environment.py --install-missing
```

Expected interpreter: `/home/ubuntu/customer-choice-trust/.venv/bin/python`, Python 3.12.3. All dependencies were present at inspection, so the helper should print **“All required dependencies are installed; no installation performed.”** It then runs `pip check` and imports the entry point and scoring helper without loading model weights or starting the service.

If a required package really is missing, the helper pins every currently installed distribution in a fresh constraints file and installs only the missing requirements plus absent transitive dependencies. It refuses incompatible installed versions, does not create an environment, and never installs/replaces Torch automatically. Resolver conflicts stop rather than upgrade working packages. Do not run a blanket `pip install --upgrade`, create another venv, or replace the existing CPU Torch build.

## 3. AWS — reuse the existing key and start one CPU worker

In the same AWS Bash terminal:

```bash
set +x
export MODEL_ID=Qwen/Qwen3-1.7B
export MODEL_REVISION=70d244cc86ccca08cf5af4e1e306ecf908b1ad5e
export MODEL_DEVICE=cpu
export ALLOW_CPU=1
export MAX_INPUT_TOKENS=4096
export MAX_EXPLANATION_TOKENS=600

if [ -z "${MODEL_API_KEY:-}" ]; then
    IFS= read -r -s -p "Paste your EXISTING MODEL_API_KEY (hidden): " MODEL_API_KEY
    printf '\n'
fi
export MODEL_API_KEY
python -c 'import os; assert len(os.environ.get("MODEL_API_KEY", "")) >= 24, "Existing API key is missing or too short"'

python -m uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1
```

Retrieve the existing API-key value privately from the local project `.env` in your editor, and paste it only into the hidden AWS prompt if requested. Do not paste it into chat or a command containing its literal value. Do not run `init_env.py` or generate a new key. No remote project `.env` file was present at inspection; the prompt does not write one. If the key is already exported, it is reused without prompting.

The revision and limits above come from both saved CPU manifests (`outputs_cpu_pilot/run_manifest.json` and `outputs_cpu_smoke/run_manifest.json`). CPU precision remains float32; thinking is disabled by the server's existing chat-template setting. Leave this terminal running. Wait for Uvicorn's application-startup-complete message before verification.

## 4. LOCAL — open the SSH tunnel in a second terminal

```bash
ssh -i ~/Downloads/llm-experiment.pem \
  -N -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L 127.0.0.1:8000:127.0.0.1:8000 \
  ubuntu@54.252.237.68
```

Leave this terminal running. If local port 8000 already has your working tunnel, reuse it rather than launching another one. The server stays bound to remote loopback; no public model-service port is opened.

## 5. LOCAL — verify health and the upgraded interfaces

In a third local VS Code terminal:

```bash
cd /Users/saiashwin/llm-trustworthiness
source .venv/bin/activate
MODEL_BASE_URL=http://127.0.0.1:8000 python scripts/verify_cpu_server.py
MODEL_BASE_URL=http://127.0.0.1:8000 python scripts/verify_cpu_server.py --inference --timeout 600
```

The verifier reads the existing local `.env` key without printing or changing it. Health checks verify:

- Exact model/revision, CPU float32, 4096 input / 600 explanation limits, thinking disabled.
- Scoring, variable candidates, multi-token labels and explanations advertised in `/health`.
- Running server and scoring-helper hashes match the files you uploaded.

`--inference` makes exactly **four small synthetic interface calls**: 2-candidate scoring, 7-candidate scoring, multi-token sequence scoring, and one explanation. It verifies authenticated `/score_candidates` and `/explain` responses, stable candidate-ID keys, normalized numerical scores, model identity, and explanation finish metadata. No dataset is loaded, no research run is created, and no pilot file is modified. Explanation interface success is not evidence of explanation quality or factual grounding. A token-limit finish is reported separately.

Expected final line: **“Completed four synthetic interface calls. No datasets or experiment outputs were modified.”**

The legacy `/score` endpoint remains available for four-choice clients. Do not launch the full experiment yet. When later authorized, use a fresh v2 output directory because the upgraded server code/prompt protocol differs from historical runs.
