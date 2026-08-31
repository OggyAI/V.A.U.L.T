"""Main voice loop: capture → STT → route → TTS.

Run with: python -m voice.loop

Modes:
  --ptt       Push-to-talk (hold SPACE, release to process) [default]
  --timed N   Record for N seconds per turn (no keyboard listener needed)
  --text      Skip mic, type commands instead (for testing without audio)

The loop writes voice state to hud/status.json so the HUD can display it.
"""

import argparse
import asyncio
import json
import time
from pathlib import Path

from voice import stt, tts, router, capture

STATUS_PATH = Path("hud/status.json")


_last_command = ""


def _write_status(state: str, transcript: str = "", response: str = "", command: str = ""):
    """Write voice-loop state for the HUD to poll.

    stt_device is reported from here rather than probed by the HUD, since
    probing would load Whisper into VRAM on every metrics poll.
    """
    global _last_command
    if command:
        _last_command = command

    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(
        json.dumps(
            {
                "state": state,
                "transcript": transcript,
                "response": response,
                "stt_device": stt.get_device() if stt.is_loaded() else "idle",
                "last_command": _last_command,
            },
            indent=2,
        )
    )


async def process_text(text: str) -> str:
    """Route text and get a response string."""
    global _last_command
    route_type, value = router.route(text)

    # Record what fired so the HUD can show it.
    _last_command = value if route_type in ("local", "skill") else "haiku"

    if route_type == "local":
        return router.handle_local(value)

    if route_type == "skill":
        return f"[skill:{value}] Would fire Claude Code skill '{value}'. Run: claude '/morning' or similar."

    if route_type == "haiku":
        return await router.handle_haiku(value)

    return f"[unknown route] {route_type}: {value}"


async def run_timed(duration: float):
    """Record-process loop with fixed-duration recording."""
    print(f"[loop] Timed mode - {duration}s per recording. Ctrl+C to quit.")
    while True:
        _write_status("listening")
        audio_path = capture.record_blocking(duration)

        if audio_path is None:
            continue

        _write_status("processing")
        text = stt.transcribe(audio_path)
        print(f"[you] {text}")

        if not text or text.startswith("[STT"):
            _write_status("idle")
            continue

        response = await process_text(text)
        print(f"[jarvis] {response}")
        _write_status("speaking", transcript=text, response=response)

        tts.play(response)
        _write_status("idle")


async def run_text():
    """Text-only mode for testing without audio hardware."""
    print("[loop] Text mode - type commands. 'quit' to exit.")
    _write_status("idle")

    while True:
        try:
            text = input("\n[you] > ")
        except (EOFError, KeyboardInterrupt):
            break

        if text.strip().lower() in ("quit", "exit", "q"):
            break

        _write_status("processing", transcript=text)
        response = await process_text(text)
        print(f"[jarvis] {response}")
        _write_status("speaking", transcript=text, response=response)

        tts.play(response)
        _write_status("idle")

    _write_status("offline")
    print("[loop] Goodbye.")


def _wait_for_key_release(keyboard, key: str):
    """Block until `key` is not held.

    Without this, the press that starts recording is still down when we begin
    waiting for the stop press, and the same keystroke immediately stops it.
    """
    while keyboard.is_pressed(key):
        time.sleep(0.03)


async def run_ptt():
    """Toggle-style talk mode: SPACE starts recording, SPACE again stops it.

    Toggle rather than hold-to-talk: holding a key for the length of an
    utterance is awkward, and release events get missed if the key is tapped.
    """
    try:
        import keyboard
    except ImportError:
        print("[loop] Toggle-talk requires the 'keyboard' package.")
        print("       Run: pip install keyboard")
        print("       Falling back to timed mode (3s).")
        await run_timed(3.0)
        return

    print("[loop] Toggle-talk mode.")
    print("       SPACE  - start recording (press again to stop)")
    print("       ESC    - quit")
    print()
    _write_status("idle")

    while True:
        try:
            # Wait for either SPACE (record) or ESC (quit).
            while True:
                if keyboard.is_pressed("esc"):
                    _write_status("offline")
                    print("[loop] Goodbye.")
                    return
                if keyboard.is_pressed("space"):
                    break
                time.sleep(0.03)

            _wait_for_key_release(keyboard, "space")

            if not capture.start_recording():
                _write_status("idle")
                continue

            _write_status("listening")
            print("[recording... press SPACE again to stop]")

            # Second press ends the recording.
            keyboard.wait("space")
            _wait_for_key_release(keyboard, "space")

            audio_path = capture.stop_recording()
            print("[stopped]")

            if audio_path is None:
                print("[loop] Nothing captured - check the mic with: python -m voice.capture")
                _write_status("idle")
                continue

            _write_status("processing")
            text = stt.transcribe(audio_path)
            print(f"[you] {text}")

            if not text or text.startswith("[STT"):
                _write_status("idle")
                continue

            response = await process_text(text)
            print(f"[jarvis] {response}")
            _write_status("speaking", transcript=text, response=response)

            tts.play(response)
            _write_status("idle")

        except KeyboardInterrupt:
            break

    _write_status("offline")
    print("[loop] Goodbye.")


def main():
    parser = argparse.ArgumentParser(description="V.A.U.L.T. voice loop")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ptt", action="store_true", default=True, help="Push-to-talk (default)")
    group.add_argument("--timed", type=float, metavar="N", help="Record N seconds per turn")
    group.add_argument("--text", action="store_true", help="Text input mode (no mic)")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    if args.text:
        asyncio.run(run_text())
    elif args.timed:
        asyncio.run(run_timed(args.timed))
    else:
        asyncio.run(run_ptt())


if __name__ == "__main__":
    main()
