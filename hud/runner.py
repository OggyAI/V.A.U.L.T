"""Spawns the Claude Code CLI for the HUD's command deck.

Security model — this endpoint starts a process with write access to the
project, so the controls matter:

* **Fixed allowlist.** COMMANDS maps a short key to a hardcoded prompt. No
  caller-supplied text ever reaches the command line; an unknown key is
  rejected before anything spawns.
* **No shell.** Arguments are passed as a list, never interpolated into a
  shell string.
* **Scoped tools.** --allowedTools grants only what the skills need, with Bash
  narrowed to python invocations. Anything else is denied rather than
  prompting — a prompt in headless mode would hang forever.
* **Localhost only.** The HUD binds 127.0.0.1 by default. Do not expose it on
  0.0.0.0 with this endpoint enabled.
* **Timeout.** Runaway jobs are killed.

Jobs run in background threads and are polled by the frontend, because a skill
can take minutes and an HTTP request should not hang that long.
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_TIMEOUT = 600  # seconds; a skill that runs longer than this is stuck
MAX_JOBS_RETAINED = 20

# The only prompts that can ever be executed. Keys come from the UI; values
# never do.
COMMANDS: dict[str, str] = {
    "morning": "/morning",
    "trend-scan": "Run a trend scan and write the report to the vault.",
    "plan-today": "Plan today and write the plan to the vault.",
    "weekly-status": "Write this week's status report into the vault.",
    "subs-audit": "Run a subscription audit and write the report to the vault.",
}

# Least privilege for what the skills actually do: read/write vault notes,
# search the repo, and run the project's own python scripts.
ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Glob", "Grep", "WebSearch",
    "Bash(python *)", "Bash(python3 *)",
]

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def cli_path() -> str | None:
    """Absolute path to the claude executable, or None if not installed."""
    return shutil.which("claude")


def check_cli() -> tuple[bool, str]:
    """Report CLI availability without running anything."""
    path = cli_path()
    if not path:
        return False, (
            "claude CLI not found on PATH - install with:\n"
            "  npm install -g @anthropic-ai/claude-code"
        )
    return True, path


def _argv(prompt: str) -> list[str]:
    """Build the argument list.

    On Windows the npm shim is claude.cmd, which CreateProcess cannot launch
    directly, so it goes through cmd.exe /c. Arguments stay a list either way —
    this is not shell=True and nothing is string-interpolated.
    """
    exe = cli_path()
    args = [
        exe, "-p", prompt,
        "--output-format", "json",
        "--permission-mode", "acceptEdits",
        "--allowedTools", *ALLOWED_TOOLS,
    ]
    if sys.platform == "win32" and exe and exe.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", *args]
    return args


def _prune():
    """Keep the job table bounded; drop the oldest finished jobs."""
    if len(_jobs) <= MAX_JOBS_RETAINED:
        return
    finished = sorted(
        (j for j in _jobs.values() if j["status"] != "running"),
        key=lambda j: j.get("finished_at") or 0,
    )
    for job in finished[: len(_jobs) - MAX_JOBS_RETAINED]:
        _jobs.pop(job["id"], None)


def _child_env() -> dict:
    """Environment for the spawned CLI.

    By default the child simply inherits ours, so whatever `claude /login`
    stored on disk is used — that bills your Claude subscription.

    Set VAULT_CLI_USE_API_KEY=1 to inject ANTHROPIC_API_KEY from .env instead.
    That takes precedence over the OAuth profile and bills API credits per run,
    so it is opt-in rather than the default.
    """
    env = os.environ.copy()
    if os.environ.get("VAULT_CLI_USE_API_KEY") == "1":
        try:
            from dotenv import dotenv_values
            key = dotenv_values(PROJECT_ROOT / ".env").get("ANTHROPIC_API_KEY")
            if key:
                env["ANTHROPIC_API_KEY"] = key
        except ImportError:
            pass
    return env


def _run(job_id: str, prompt: str, timeout: int):
    job = _jobs[job_id]
    try:
        proc = subprocess.Popen(
            _argv(prompt),
            cwd=str(PROJECT_ROOT),
            env=_child_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception as e:
        with _lock:
            job.update(status="error", output=f"Could not start claude: {e}",
                       finished_at=time.time())
        return

    with _lock:
        job["pid"] = proc.pid

    try:
        out, _ = proc.communicate(timeout=timeout)
        status = "done" if proc.returncode == 0 else "error"
    except subprocess.TimeoutExpired:
        proc.kill()
        out = f"Timed out after {timeout}s and was killed."
        status = "error"

    with _lock:
        job.update(status=status, output=(out or "").strip(),
                   exit_code=proc.returncode, finished_at=time.time())
        _prune()


def start(command: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Launch a command in the background. Returns the job record."""
    if command not in COMMANDS:
        raise KeyError(command)

    ok, detail = check_cli()
    if not ok:
        raise RuntimeError(detail)

    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "command": command,
        "status": "running",
        "output": "",
        "exit_code": None,
        "started_at": time.time(),
        "finished_at": None,
        "pid": None,
    }
    with _lock:
        _jobs[job_id] = job

    threading.Thread(
        target=_run, args=(job_id, COMMANDS[command], timeout), daemon=True
    ).start()
    return dict(job)


def get(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


NOT_LOGGED_IN_HINT = (
    "Claude CLI is not signed in. Open a terminal and run:  claude  "
    "then /login (uses your Claude subscription). Or set "
    "VAULT_CLI_USE_API_KEY=1 to bill API credits from .env instead."
)


def summary(job: dict) -> str:
    """One-line result for the UI.

    With --output-format json the CLI emits a JSON envelope; the human-readable
    answer is under `result`. Fall back to raw text if the shape ever changes.
    """
    if job["status"] == "running":
        return "Running..."

    out = job.get("output") or ""

    # The CLI reports this as plain text on stderr, not JSON — translate it
    # into something the user can act on instead of showing "/login".
    if "not logged in" in out.lower() or "please run /login" in out.lower():
        return NOT_LOGGED_IN_HINT

    try:
        import json
        data = json.loads(out)
        if isinstance(data, dict):
            text = data.get("result") or data.get("error") or ""
            if text:
                return str(text).strip()
    except (ValueError, TypeError):
        pass
    return out[:2000] or f"Exited with code {job.get('exit_code')}"


if __name__ == "__main__":
    ok, detail = check_cli()
    print(f"{'OK' if ok else 'NOT READY'}: {detail}")
    if ok:
        print(f"argv preview: {_argv(COMMANDS['plan-today'])}")
