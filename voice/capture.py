"""Microphone capture.

Three entry points:
  record_blocking(seconds) — fixed-length recording
  start_recording() / stop_recording() — toggle-style, for push-to-talk
  mic_check(seconds) — live level meter, to verify the mic actually works

Run `python -m voice.capture` for an interactive mic check.
"""

import tempfile
import threading
import time
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1
DEVICE_INDEX = None  # None = system default; set to an int to pin a device

_frames: list[np.ndarray] = []
_recording = False
_stream = None  # must be retained: a GC'd InputStream stops capturing
_lock = threading.Lock()


def _audio_callback(indata, frames, time_info, status):
    if _recording:
        with _lock:
            _frames.append(indata.copy())


def list_devices() -> str:
    """Return a printable list of audio devices."""
    try:
        import sounddevice as sd
    except ImportError:
        return "[capture] sounddevice not installed - run: pip install sounddevice"
    return str(sd.query_devices())


def default_input_name() -> str:
    """Name of the input device that will actually be used."""
    try:
        import sounddevice as sd

        idx = DEVICE_INDEX if DEVICE_INDEX is not None else sd.default.device[0]
        return f"[{idx}] {sd.query_devices(idx)['name']}"
    except Exception as e:
        return f"(could not resolve input device: {e})"


def start_recording() -> bool:
    """Begin recording. Returns True if the stream started."""
    global _recording, _stream
    try:
        import sounddevice as sd
    except ImportError:
        print("[capture] sounddevice not installed - run: pip install sounddevice")
        return False

    if _stream is not None:
        return True  # already recording

    with _lock:
        _frames.clear()
    _recording = True

    try:
        _stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            device=DEVICE_INDEX,
            dtype="float32",
            callback=_audio_callback,
        )
        _stream.start()
        return True
    except Exception as e:
        print(f"[capture] Could not open input stream: {e}")
        _recording = False
        _stream = None
        return False


def stop_recording() -> Path | None:
    """Stop recording and save to a temp WAV. Returns the path, or None."""
    global _recording, _stream
    try:
        import soundfile as sf
    except ImportError:
        print("[capture] soundfile not installed - run: pip install soundfile")
        return None

    _recording = False

    if _stream is not None:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None

    with _lock:
        if not _frames:
            return None
        audio = np.concatenate(_frames, axis=0)
        _frames.clear()

    path = Path(tempfile.gettempdir()) / "jarvis_capture.wav"
    sf.write(str(path), audio, SAMPLE_RATE)
    return path


def record_blocking(duration_seconds: float = 5.0) -> Path | None:
    """Record for a fixed duration."""
    try:
        import sounddevice as sd
        import soundfile as sf
    except ImportError:
        print("[capture] sounddevice/soundfile not installed")
        return None

    print(f"[capture] Recording for {duration_seconds}s...")
    try:
        audio = sd.rec(
            int(SAMPLE_RATE * duration_seconds),
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            device=DEVICE_INDEX,
            dtype="float32",
        )
        sd.wait()
    except Exception as e:
        print(f"[capture] Recording failed: {e}")
        return None

    path = Path(tempfile.gettempdir()) / "jarvis_capture.wav"
    sf.write(str(path), audio, SAMPLE_RATE)
    return path


def mic_check(duration_seconds: float = 8.0):
    """Live input-level meter. Verifies the mic is actually picking up sound.

    Prints a bar that moves with your voice. If the bar never leaves 0 while
    you're talking, the mic is muted, the wrong device is selected, or the app
    lacks microphone permission.
    """
    try:
        import sounddevice as sd
    except ImportError:
        print("[capture] sounddevice not installed - run: pip install sounddevice")
        return

    print(f"Input device: {default_input_name()}")
    print(f"Talk for {duration_seconds:.0f}s - the bar should move.\n")

    peak_seen = 0.0

    def cb(indata, frames, time_info, status):
        nonlocal peak_seen
        level = float(np.abs(indata).max())
        peak_seen = max(peak_seen, level)
        bars = int(level * 60)
        meter = "#" * bars + "-" * (60 - bars)
        print(f"\r[{meter}] {level:.3f}", end="", flush=True)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            device=DEVICE_INDEX,
            dtype="float32",
            callback=cb,
        ):
            time.sleep(duration_seconds)
    except Exception as e:
        print(f"\n[capture] Could not open input stream: {e}")
        return

    print("\n")
    if peak_seen < 0.01:
        print(f"FAIL - peak level {peak_seen:.4f}. The mic heard nothing.")
        print("  - Check Windows Settings > System > Sound > Input")
        print("  - Make sure the right device is set as default, and not muted")
        print("  - Run `python -m voice.capture --devices` to pick another index")
    elif peak_seen < 0.05:
        print(f"WEAK - peak level {peak_seen:.4f}. Audible but quiet.")
        print("  Raise the input volume in Windows sound settings, or move closer.")
    else:
        print(f"OK - peak level {peak_seen:.4f}. Mic is working.")


if __name__ == "__main__":
    import sys

    if "--devices" in sys.argv:
        print(list_devices())
    else:
        mic_check(8.0)
