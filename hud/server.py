"""HUD backend — serves the dashboard and exposes API endpoints.

Run with: uvicorn hud.server:app --reload --port 8550

Endpoints:
  GET  /                    → dashboard (static/index.html)
  GET  /api/status          → voice loop state
  GET  /api/metrics         → channel/project metrics
  POST /api/run-command     → fire a skill or command
"""

import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="V.A.U.L.T. HUD")

HUD_DIR = Path(__file__).parent
PROJECT_ROOT = HUD_DIR.parent
STATIC_DIR = HUD_DIR / "static"
STATUS_FILE = HUD_DIR / "status.json"
METRICS_FILE = HUD_DIR / "metrics.json"

VAULT_DIR = PROJECT_ROOT / "vault"
SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"

DEFAULT_STATUS = {
    "state": "offline",
    "transcript": "",
    "response": "",
    "stt_device": "unknown",
    "last_command": "",
}

# Social metrics stay in the schema but dormant until API keys exist.
# See HANDOFF.md step 5. The HUD only renders keys with real values.
DORMANT_METRICS = {
    "yt_subscribers": None,
    "yt_latest_views": None,
    "ig_followers": None,
}


def _count_files(root: Path, pattern: str) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for _ in root.rglob(pattern))


def _tts_status() -> str:
    """Ready if both Kokoro model files are present, else stub."""
    model = any((PROJECT_ROOT / n).is_file() for n in ("kokoro-v1.0.onnx", "voice/kokoro-v1.0.onnx"))
    voices = any((PROJECT_ROOT / n).is_file() for n in ("voices-v1.0.bin", "voice/voices-v1.0.bin"))
    return "ready" if (model and voices) else "stub"


def _live_metrics() -> dict:
    """Compute metrics from the local filesystem.

    Deliberately cheap — this endpoint is polled every few seconds, so it must
    not load models or hit the network. The STT device is reported by the voice
    loop into status.json rather than probed here, since probing would pull
    Whisper into VRAM on every poll.
    """
    status = _read_json(STATUS_FILE, DEFAULT_STATUS)

    metrics = {
        "vault_notes": _count_files(VAULT_DIR, "*.md"),
        "reports": _count_files(VAULT_DIR / "30-Reports", "*.md"),
        "skills_loaded": _count_files(SKILLS_DIR, "SKILL.md"),
        "stt_device": status.get("stt_device", "unknown"),
        "tts_status": _tts_status(),
        "last_command": status.get("last_command", "") or "none",
    }
    metrics.update(DORMANT_METRICS)
    return metrics


def _read_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# Seed status if absent. metrics.json is no longer seeded — metrics are
# computed live by _live_metrics(); the file is only an optional override.
if not STATUS_FILE.exists():
    _write_json(STATUS_FILE, DEFAULT_STATUS)


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
async def get_status():
    return JSONResponse(_read_json(STATUS_FILE, DEFAULT_STATUS))


@app.get("/api/metrics")
async def get_metrics():
    """Live local metrics, overlaid with metrics.json if that file exists.

    The override file is where real social-media numbers will land once a
    fetcher script is writing them (see HANDOFF.md step 5).
    """
    metrics = _live_metrics()
    metrics.update(_read_json(METRICS_FILE, {}))
    return JSONResponse(metrics)


@app.post("/api/voice/{action}")
async def voice_control(action: str):
    """Drive the server-side voice pipeline: start | stop | cancel | preload.

    The mic, GPU transcription, and speaker are all on this machine — the
    browser is a remote control, not the audio device.
    """
    from hud import voice_bridge

    handlers = {
        "start": voice_bridge.start,
        "stop": voice_bridge.stop,
        "cancel": voice_bridge.cancel,
        "preload": voice_bridge.preload,
    }
    handler = handlers.get(action)
    if not handler:
        return JSONResponse(
            {"error": f"Unknown action: {action}", "allowed": sorted(handlers)},
            status_code=400,
        )

    try:
        return JSONResponse(handler())
    except ImportError as e:
        # sounddevice / faster-whisper missing, or no venv.
        return JSONResponse({"error": str(e)}, status_code=503)


@app.get("/api/voice/state")
async def voice_state():
    from hud import voice_bridge
    return JSONResponse(voice_bridge.get_state())


@app.get("/api/subscriptions")
async def get_subscriptions():
    """Tracked subscriptions, spend totals, renewals, and overlap groups.

    Returns an `available: false` payload rather than erroring when the
    tracker hasn't been synced yet, so the panel can render an empty state.
    """
    try:
        from subs import db as subs_db, sync as subs_sync
    except ImportError as e:
        return JSONResponse({"available": False, "reason": str(e)})

    if not subs_db.DB_PATH.exists():
        return JSONResponse({
            "available": False,
            "reason": "No subscription data yet - run: python -m subs.cli sync --source fixtures",
        })

    conn = subs_db.connect()
    totals = subs_db.totals(conn)
    stale = subs_db.stale_subscriptions(conn)
    stale_ids = {s["id"] for s in stale}

    active = subs_db.list_subscriptions(conn, status="active")
    for sub in active:
        sub["is_stale"] = sub["id"] in stale_ids

    return JSONResponse({
        "available": True,
        "totals": totals,
        "monthly_display": subs_db.format_totals(totals, "monthly"),
        "yearly_display": subs_db.format_totals(totals, "yearly"),
        "active": active,
        "needs_review": subs_db.list_subscriptions(conn, status="needs_review"),
        "renewals": subs_db.upcoming_renewals(conn, within_days=30),
        "overlap": subs_sync.find_duplicates(conn),
        "stale": stale,
    })


@app.post("/api/subscriptions/review")
async def review_subscription(body: dict):
    """Confirm or reject a low-confidence extraction.

    Body: {"id": 3, "action": "confirm" | "reject"}
    """
    try:
        from subs import db as subs_db
    except ImportError as e:
        return JSONResponse({"error": str(e)}, status_code=503)

    sub_id, action = body.get("id"), body.get("action")
    if not isinstance(sub_id, int):
        return JSONResponse({"error": "id must be an integer"}, status_code=400)
    if action not in ("confirm", "reject"):
        return JSONResponse({"error": "action must be 'confirm' or 'reject'"}, status_code=400)

    conn = subs_db.connect()
    if not conn.execute("SELECT 1 FROM subscriptions WHERE id = ?", (sub_id,)).fetchone():
        return JSONResponse({"error": f"No subscription with id {sub_id}"}, status_code=404)

    subs_db.set_status(conn, sub_id, "active" if action == "confirm" else "cancelled")
    return JSONResponse({"status": "ok", "id": sub_id, "action": action})


@app.post("/api/run-command")
async def run_command(body: dict):
    """Launch a Claude Code command in the background.

    Body: {"command": "morning"}
    Returns a job_id to poll at /api/run-command/{job_id}.

    The command key is looked up in a fixed allowlist — caller text never
    reaches the command line. See hud/runner.py for the full security model.
    """
    from hud import runner

    command = (body.get("command") or "").strip()
    if not command:
        return JSONResponse({"error": "No command provided"}, status_code=400)

    if command not in runner.COMMANDS:
        return JSONResponse(
            {"error": f"Unknown command: {command}",
             "allowed": sorted(runner.COMMANDS)},
            status_code=400,
        )

    try:
        job = runner.start(command)
    except RuntimeError as e:
        # CLI not installed — a setup problem, not a bad request.
        return JSONResponse({"error": str(e)}, status_code=503)

    return JSONResponse({
        "status": "running",
        "job_id": job["id"],
        "command": command,
        "message": f"Running /{command}...",
    })


@app.get("/api/run-command/{job_id}")
async def run_command_status(job_id: str):
    """Poll a running command. Returns status and, once finished, its output."""
    from hud import runner

    job = runner.get(job_id)
    if not job:
        return JSONResponse({"error": "Unknown job id"}, status_code=404)

    return JSONResponse({
        "job_id": job["id"],
        "command": job["command"],
        "status": job["status"],
        "exit_code": job["exit_code"],
        "elapsed": round((job["finished_at"] or time.time()) - job["started_at"], 1),
        "message": runner.summary(job),
    })


@app.get("/api/cli-status")
async def cli_status():
    """Whether the Claude CLI is available, for the UI to show up front."""
    from hud import runner

    ok, detail = runner.check_cli()
    return JSONResponse({
        "available": ok,
        "detail": detail if not ok else "claude CLI found",
        "commands": sorted(runner.COMMANDS),
    })


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("hud.server:app", host="127.0.0.1", port=8550, reload=True)
