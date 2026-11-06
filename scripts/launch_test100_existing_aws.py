"""Remote-only, explicit launch/restart helper for the frozen test-100 stage.

Run this on the existing Linux host after the new continuation has been copied
and hash checked. ``--inspect`` reads only. ``--launch`` may gracefully replace
the one existing model-server process and launch one detached study runner.
The existing server credential is passed privately in inherited environments;
it is never serialized, printed, or placed in a command argument.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from urllib.request import Request, urlopen


SERVER_SESSION = "choice-model-test100"
RUNNER_SESSION = "choice-test-100-night"
APP = "choice_trust.test100_server:app"
MODEL_ID = "Qwen/Qwen3-1.7B"
REVISION = "70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
BASE_URL = "http://127.0.0.1:8000"
MODEL_ENV_ALLOWLIST = (
    "MODEL_ID", "MODEL_REVISION", "MODEL_DEVICE", "ALLOW_CPU",
    "MAX_INPUT_TOKENS", "MAX_EXPLANATION_TOKENS",
)
RUNNER_SCRIPTS = {
    "aws_queue.py", "run_resumed_study.py", "run_cpu_real_v2.py",
    "check_development_workflow.py", "run_counterfactual_pilot.py",
    "run_test100.py", "experiment.py",
}


def now():
    return datetime.now(timezone.utc).isoformat()


def processes():
    """Read Linux process identities without printing arbitrary command lines."""
    result = []
    for path in Path("/proc").glob("[0-9]*"):
        try:
            args = [x.decode(errors="replace") for x in
                    (path / "cmdline").read_bytes().split(b"\0") if x]
            if not args:
                continue
            result.append({"pid": int(path.name), "args": args,
                           "cwd": str((path / "cwd").resolve()),
                           "exe": str((path / "exe").resolve())})
        except (FileNotFoundError, PermissionError, ProcessLookupError):
            continue
    return result


def server_processes(rows):
    # A detached screen supervisor retains its child's entire argument vector.
    # Count the Python process that owns the model, not that supervisor.
    return [row for row in rows if Path(row["exe"]).name.startswith("python")
            and any(Path(arg).name == "uvicorn" for arg in row["args"])
            and any(app in row["args"] for app in ("server:app", APP))]


def competing_workloads(rows):
    result = []
    for row in rows:
        if row["pid"] == os.getpid():
            continue
        scripts = sorted({Path(arg).name for arg in row["args"]} & RUNNER_SCRIPTS)
        if scripts or ("-m" in row["args"] and "choice_trust" in row["args"]):
            result.append({"pid": row["pid"], "cwd": row["cwd"],
                           "scripts": scripts or ["choice_trust"]})
    return result


def environment(pid):
    # Never expose the returned dictionary in diagnostics or serialized output.
    return {key.decode(): value.decode() for item in
            Path(f"/proc/{pid}/environ").read_bytes().split(b"\0") if b"=" in item
            for key, value in [item.split(b"=", 1)]}


def server_description(row):
    env = environment(row["pid"])
    return {"pid": row["pid"], "cwd": row["cwd"], "executable": row["exe"],
            "app": APP if APP in row["args"] else "server:app",
            "model_environment": {key: env[key] for key in MODEL_ENV_ALLOWLIST if key in env},
            "credential_available": bool(env.get("MODEL_API_KEY"))}


def session_names():
    # screen output includes socket names only; do not print unfiltered output.
    completed = subprocess.run(["screen", "-ls"], capture_output=True, text=True)
    names = []
    for line in completed.stdout.splitlines():
        value = line.strip().split()
        if value and "." in value[0] and value[0].split(".", 1)[0].isdigit():
            names.append(value[0])
    return sorted(names)


def request(route, key=None, timeout=5):
    headers = {"Authorization": "Bearer " + key} if key else {}
    with urlopen(Request(BASE_URL + route, headers=headers), timeout=timeout) as response:
        return json.load(response)


def verify_runtime(key, manifest):
    health = request("/health", timeout=10)
    runtime = request("/test100/runtime", key, timeout=120)
    verify_health(health)
    if runtime.get("plan_id") != manifest["plan_id"]:
        raise RuntimeError("Existing joint server loaded a different study manifest")
    for key_name, value in manifest["joint_settings"].items():
        if runtime.get("effective_settings", {}).get(key_name) != value:
            raise RuntimeError("Existing joint server generation settings differ")
    return {"plan_id": runtime["plan_id"], "model": runtime.get("model"),
            "effective_settings": runtime.get("effective_settings"),
            "health": {key_name: health.get(key_name) for key_name in
                       ("status", "model_id", "revision", "device", "dtype", "max_input_tokens")}}


def verify_health(health):
    if (health.get("model_id") != MODEL_ID or health.get("revision") != REVISION
            or health.get("device") != "cpu" or health.get("dtype") != "torch.float32"
            or health.get("max_input_tokens") != 4096
            or health.get("enable_thinking") is not False):
        raise RuntimeError("Existing server model identity, precision, or input policy differs")


def inspect(root, out):
    rows = processes()
    result = {"utc": now(), "mode": "read_only_inspection", "root": str(root),
              "out": str(out), "servers": [server_description(row) for row in server_processes(rows)],
              "competing_workloads": competing_workloads(rows), "sessions": session_names(),
              "server_session": SERVER_SESSION, "runner_session": RUNNER_SESSION}
    if (out / "manifest.json").exists():
        from choice_trust.test100_plan import verify_manifest
        manifest = verify_manifest(out)
        result["manifest"] = {key: manifest[key] for key in
                              ("plan_id", "selection_count", "planned_originals",
                               "planned_interventions", "not_applicable_interventions",
                               "planned_total_responses")}
    return result


@contextmanager
def launch_lock(out):
    with (out / ".launcher.lock").open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another launcher holds this study's launch lock") from None
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def record(directory, **fields):
    with (directory / "launch_events.jsonl").open("a") as handle:
        handle.write(json.dumps({"utc": now(), **fields}, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def existing_python(server):
    """Retain the existing venv interpreter, not just /proc's resolved binary."""
    first = Path(server["args"][0])
    candidates = [first, Path("/home/ubuntu/customer-choice-trust/.venv/bin/python")]
    for candidate in candidates:
        if (candidate.is_absolute() and candidate.is_file()
                and str(candidate.resolve()) == server["exe"]):
            return str(candidate)
    raise RuntimeError("Could not establish the existing model-server Python environment")


def start_session(name, command, *, cwd, env, log_variable, log_path):
    if any(value.split(".", 1)[-1] == name for value in session_names()):
        raise RuntimeError("The intended detached session name already exists")
    child_env = dict(env)
    child_env[log_variable] = str(log_path)
    # Only a fixed variable name is inserted into shell code. Paths and commands
    # are positional arguments. Credentials exist only in inherited environment.
    shell_code = 'exec "$@" >> "$' + log_variable + '" 2>&1'
    completed = subprocess.run(["screen", "-dmS", name, "/bin/bash", "-c", shell_code,
                                "bash", *command], cwd=cwd, env=child_env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError("Detached session creation failed; inspect the fixed session/log paths")


def wait_for_server(root, key, manifest, timeout):
    deadline = time.monotonic() + timeout
    last_notice = 0
    while time.monotonic() < deadline:
        matches = [row for row in server_processes(processes())
                   if row["cwd"] == str(root) and APP in row["args"]]
        if len(matches) > 1:
            raise RuntimeError("More than one replacement model-server process was found")
        try:
            if len(matches) == 1:
                runtime = verify_runtime(key, manifest)
                return matches[0], runtime
        except Exception:
            # Model startup/health connection failures are not inference calls.
            # Do not print transport error text, which can contain request data.
            pass
        if not any(value.split(".", 1)[-1] == SERVER_SESSION for value in session_names()):
            raise RuntimeError("Replacement server session exited before readiness; inspect server.log")
        if time.monotonic() - last_notice >= 30:
            print(json.dumps({"utc": now(), "status": "waiting_for_existing_model_startup",
                              "session": SERVER_SESSION}), flush=True)
            last_notice = time.monotonic()
        time.sleep(1)
    raise RuntimeError("Replacement server readiness timeout; no study runner was launched")


def launch(root, out, startup_timeout):
    from choice_trust.test100_plan import verify_manifest
    # Full source/patch/manifest checks precede stopping any model process.
    manifest = verify_manifest(out)
    for relative in ("choice_trust/test100_server.py", "scripts/run_test100.py", "server.py"):
        path = root / relative
        if not path.is_file():
            raise RuntimeError("A required deployed runtime file is missing")
        compile(path.read_text(), str(path), "exec")
    with launch_lock(out):
        rows = processes()
        competing = competing_workloads(rows)
        if competing:
            print(json.dumps({"competing_workloads": competing}), flush=True)
            raise RuntimeError("An experiment workload is active; refusing a competing launch")
        servers = server_processes(rows)
        if len(servers) != 1:
            raise RuntimeError("Exactly one existing model server is required; none will be created from scratch")
        server = servers[0]
        env = environment(server["pid"])
        key = env.get("MODEL_API_KEY")
        if not key:
            raise RuntimeError("The existing model-server credential is unavailable")
        python = existing_python(server)
        if (env.get("MODEL_ID", MODEL_ID) != MODEL_ID
                or env.get("MODEL_REVISION", REVISION) != REVISION
                or env.get("MODEL_DEVICE", "cpu") != "cpu"):
            raise RuntimeError("The existing server environment differs from the pinned CPU model")
        old_health = request("/health", timeout=10)
        verify_health(old_health)
        for key_name, relative in (("server_code_sha256", "server.py"),
                                   ("scoring_helper_sha256", "choice_trust/scoring.py")):
            if old_health.get(key_name) != sha256((root / relative).read_bytes()).hexdigest():
                raise RuntimeError("Deployed base server/helper differs from the existing model server")
        if APP in server["args"] and env.get("TEST100_OUT") != str(out):
            raise RuntimeError("Existing joint wrapper uses a different study directory")
        env.update(TEST100_OUT=str(out), MODEL_BASE_URL=BASE_URL,
                   PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
        env["TEST100_REUSE_ROOTS"] = json.dumps(list(dict.fromkeys([
            str(root), server["cwd"], "/home/ubuntu/customer-choice-trust",
            "/home/ubuntu/customer-choice-trust/continuations/resumed_v1",
        ])))
        # Importing the wrapper registers routes but does not enter the app's
        # lifespan or load weights. Catch missing/incompatible dependencies
        # while the existing server and private credential are still available.
        with (out / "launch_preflight.log").open("ab") as log:
            preflight = subprocess.run([python, "-B", "-c", "import choice_trust.test100_server"],
                                       cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        if preflight.returncode:
            raise RuntimeError("Joint wrapper import preflight failed; existing server was not stopped")
        prior = server_description(server)
        if APP in server["args"]:
            if server["cwd"] != str(root):
                raise RuntimeError("Existing joint wrapper belongs to a different deployed root")
            runtime = verify_runtime(key, manifest)
            mode = "reused_existing_joint_server"
        else:
            # A single graceful stop; no escalation to force-kill or replacement
            # while the old process is alive. Credentials remain private in RAM.
            if any(value.split(".", 1)[-1] == SERVER_SESSION for value in session_names()):
                raise RuntimeError("Replacement server session already exists; inspect it before restarting")
            record(out, event="graceful_server_replacement_started", plan_id=manifest["plan_id"],
                   prior_server=prior, credential="Reused privately from existing server environment")
            current = next((row for row in processes() if row["pid"] == server["pid"]), None)
            if current is None or current["args"] != server["args"] or current["cwd"] != server["cwd"]:
                raise RuntimeError("Existing model-server identity changed during preflight")
            if competing_workloads(processes()):
                raise RuntimeError("An experiment workload appeared during preflight; server not stopped")
            os.kill(server["pid"], signal.SIGINT)
            deadline = time.monotonic() + 120
            while Path(f'/proc/{server["pid"]}').exists() and time.monotonic() < deadline:
                time.sleep(1)
            if Path(f'/proc/{server["pid"]}').exists():
                raise RuntimeError("Old model server did not exit gracefully; no replacement was started")
            if server_processes(processes()):
                raise RuntimeError("A model server appeared during replacement; no duplicate was started")
            start_session(SERVER_SESSION,
                          [python, "-B", "-u", "-m", "uvicorn", APP, "--host", "127.0.0.1",
                           "--port", "8000", "--workers", "1"],
                          cwd=root, env=env, log_variable="TEST100_SERVER_LOG",
                          log_path=out / "server.log")
            server, runtime = wait_for_server(root, key, manifest, startup_timeout)
            mode = "replaced_legacy_transport_with_exact_joint_wrapper"
        # Do not launch if a workload appeared while model startup was pending.
        competing = competing_workloads(processes())
        if competing:
            raise RuntimeError("An experiment workload appeared during startup; runner not launched")
        start_session(RUNNER_SESSION,
                      [python, "-B", "-u", str(root / "scripts/run_test100.py"),
                       "run", "--out", str(out)], cwd=root, env=env,
                      log_variable="TEST100_RUNNER_LOG", log_path=out / "runner.log")
        deadline = time.monotonic() + 20
        runner = None
        while time.monotonic() < deadline:
            candidates = [row for row in processes()
                          if Path(row["exe"]).name.startswith("python")
                          and row["cwd"] == str(root)
                          and any(Path(arg).name == "run_test100.py" for arg in row["args"])
                          and "run" in row["args"] and str(out) in row["args"]]
            if len(candidates) > 1:
                raise RuntimeError("Duplicate study runners detected; inspect the run lock")
            if candidates:
                runner = candidates[0]
                break
            time.sleep(1)
        metadata = {"utc": now(), "plan_id": manifest["plan_id"], "root": str(root),
                    "out": str(out), "server_mode": mode, "server_pid": server["pid"],
                    "server_session": SERVER_SESSION, "runner_pid": runner["pid"] if runner else None,
                    "runner_session": RUNNER_SESSION, "runtime": runtime,
                    "credential": "Inherited privately; never printed or written",
                    "completion_policy": "Runner exits after this frozen stage; model server and EC2 remain running",
                    "progress_log": str(out / "runner.log")}
        record(out, event="detached_launch", **metadata)
        if runner is None:
            raise RuntimeError("Runner not active after launch; inspect runner.log and completion state")
        return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Hash-verified deployed continuation root")
    parser.add_argument("--out", type=Path, default=Path("choice_study/test_with_history_100_v1"))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true", help="Read-only remote process/manifest inspection")
    mode.add_argument("--launch", action="store_true", help="Gracefully replace legacy transport if needed, then detach runner")
    parser.add_argument("--startup-timeout", type=int, default=1800)
    args = parser.parse_args()
    if sys.platform != "linux" or not Path("/proc/self/environ").exists():
        parser.error("This helper runs only on the existing Linux AWS host")
    if not shutil.which("screen"):
        parser.error("Existing screen is unavailable; no packages will be installed")
    root = args.root.resolve()
    out = (args.out if args.out.is_absolute() else root / args.out).resolve()
    if not root.is_dir() or not out.is_dir() or not out.is_relative_to(root):
        parser.error("Root and frozen study directory must already exist, with study directory inside root")
    if args.startup_timeout < 1:
        parser.error("Startup timeout must be positive")
    os.chdir(root)
    sys.path.insert(0, str(root))
    try:
        result = inspect(root, out) if args.inspect else launch(root, out, args.startup_timeout)
        print(json.dumps(result, indent=2), flush=True)
    except Exception as error:
        # Known messages are authored above; unexpected exceptions get a type
        # only, preventing accidental disclosure of environment/request values.
        message = str(error) if type(error) is RuntimeError else "Inspect the saved launch/server/runner records"
        print(json.dumps({"utc": now(), "status": "blocked_or_incomplete",
                          "error_type": type(error).__name__, "reason": message}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
