"""Drives the voice pipeline from the HUD instead of a terminal.

The microphone, GPU transcription, and speaker all stay server-side — this is
the same capture -> stt -> router -> tts chain voice/loop.py runs, just started
and stopped over HTTP rather than by keypress.

State is mirrored into hud/status.json in the shape the dashboard already
polls, so the orb and transcript work without any change to the status
plumbing.

Do not run this and `python -m voice.loop` at the same time: both would fight
over the same input device and the same status file.
"""

import asyncio
import json
import threading
import time
from pathlib import Path

STATUS_PATH = Path(__file__).parent / "status.json"

_state = {
    "state": "idle",        # idle | listening | processing | speaking | error
    "transcript": "",
    "response": "",
    "error": None,
    "stt_device": "idle",
    "last_command": "",
    "started_at": None,
}
_lock = threading.Lock()
_worker: threading.Thread | None = None


def _write_status():
    """Mirror state into the file the HUD already polls."""
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            payload = {
                "state": _state["state"],
                "transcript": _state["transcript"],
                "response": _state["response"],
                "stt_device": _state["stt_device"],
                "last_command": _state["last_command"],
            }
        STATUS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        pass


def _set(**kwargs):
    with _lock:
        _state.update(kwargs)
    _write_status()


def get_state() -> dict:
    with _lock:
        state = dict(_state)
    state["elapsed"] = (
        round(time.time() - state["started_at"], 1) if state["started_at"] else 0
    )
    return state


def is_busy() -> bool:
    return _state["state"] in ("listening", "processing", "speaking")


def start() -> dict:
    """Begin recording. Returns the new state."""
    from voice import capture

    if is_busy():
        return {**get_state(), "error": f"Already {_state['state']}"}

    if not capture.start_recording():
        _set(state="error", error="Could not open the microphone. "
                                  "Check Windows sound input settings.")
        return get_state()

    _set(state="listening", transcript="", response="", error=None,
         started_at=time.time())
    return get_state()


def stop() -> dict:
    """Stop recording and process in the background.

    Returns immediately — transcription plus a possible Haiku call can take
    several seconds, and the HTTP request should not hold that open. The
    frontend polls get_state() for the result.
    """
    global _worker

    from voice import capture

    if _state["state"] != "listening":
        return {**get_state(), "error": "Not currently recording"}

    audio_path = capture.stop_recording()
    if audio_path is None:
        _set(state="error", error="Nothing was captured - the mic may be muted.",
             started_at=None)
        return get_state()

    _set(state="processing", started_at=time.time())
    _worker = threading.Thread(target=_process, args=(audio_path,), daemon=True)
    _worker.start()
    return get_state()


def cancel() -> dict:
    """Discard an in-progress recording without transcribing it."""
    from voice import capture

    if _state["state"] == "listening":
        capture.stop_recording()
    _set(state="idle", transcript="", response="", error=None, started_at=None)
    return get_state()


def _process(audio_path: Path):
    """Transcribe, route, reply, speak. Runs off the request thread."""
    from voice import router, stt, tts

    try:
        text = stt.transcribe(audio_path)
        device = stt.get_device() if stt.is_loaded() else "idle"

        if not text or text.startswith("[STT"):
            _set(state="idle", transcript="", stt_device=device,
                 error="Nothing was transcribed - try speaking for longer.",
                 started_at=None)
            return

        _set(transcript=text, stt_device=device)

        route_type, value = router.route(text)
        command = value if route_type in ("local", "skill") else "haiku"

        if route_type == "local":
            response = router.handle_local(value)
        elif route_type == "skill":
            response = (f"Firing the {value} skill. "
                        f"Run it from the command deck to see full output.")
        else:
            # handle_haiku is async; this thread has no running loop of its own.
            response = asyncio.run(router.handle_haiku(value))

        _set(state="speaking", response=response, last_command=command)

        # Blocking on purpose: state should stay "speaking" until audio ends,
        # so the orb matches what the user hears.
        tts.play(response)

        _set(state="idle", started_at=None)

    except Exception as e:
        _set(state="error", error=f"{type(e).__name__}: {e}", started_at=None)


def preload() -> dict:
    """Load the Whisper model up front.

    Without this the first recording pays several seconds of model load after
    the user has already stopped talking, which reads as a hang.
    """
    from voice import stt

    def _load():
        try:
            device = stt.get_device()
            _set(stt_device=device)
        except Exception as e:
            _set(error=f"Model preload failed: {e}")

    if not stt.is_loaded():
        threading.Thread(target=_load, daemon=True).start()
        return {"status": "loading"}
    return {"status": "ready", "device": stt.get_device()}
