"""Text-to-speech wrapper around Kokoro-ONNX.

Requires two model files in the project root (or voice/ dir):
  - kokoro-v1.0.onnx
  - voices-v1.0.bin

If the model files are missing, falls back to printing text (no audio).

TODO (HANDOFF): Download model files — see HANDOFF.md for URLs.
TODO (HANDOFF): Install espeak-ng system binary for phoneme generation.
"""

import os
from pathlib import Path

VOICE = "af_bella"
SAMPLE_RATE = 24000

_kokoro = None
_available = None

MODEL_PATHS = [
    "kokoro-v1.0.onnx",
    "voice/kokoro-v1.0.onnx",
    os.environ.get("KOKORO_MODEL_PATH", ""),
]

VOICE_PATHS = [
    "voices-v1.0.bin",
    "voice/voices-v1.0.bin",
    os.environ.get("KOKORO_VOICES_PATH", ""),
]


def _find_file(candidates: list[str]) -> Path | None:
    """Return the first candidate that is an existing file.

    Empty strings are skipped — Path("") resolves to the cwd, which exists
    and would otherwise be handed to the model loader as a bogus path.
    """
    for raw in candidates:
        if not raw or not raw.strip():
            continue
        p = Path(raw)
        if p.is_file():
            return p
    return None


def _get_kokoro():
    global _kokoro, _available
    if _available is not None:
        return _kokoro

    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        print("[tts] kokoro-onnx not installed - run: pip install kokoro-onnx")
        _available = False
        return None

    model_path = _find_file(MODEL_PATHS)
    voice_path = _find_file(VOICE_PATHS)

    if not model_path or not voice_path:
        print("[tts] Model files not found - running in stub mode (text only)")
        print("[tts] Download kokoro-v1.0.onnx and voices-v1.0.bin (see HANDOFF.md)")
        _available = False
        return None

    try:
        _kokoro = Kokoro(str(model_path), str(voice_path))
        _available = True
        print(f"[tts] Loaded Kokoro from {model_path}")
        return _kokoro
    except Exception as e:
        print(f"[tts] Failed to load Kokoro: {e}")
        _available = False
        return None


def speak(text: str, output_path: str | None = None) -> Path | None:
    """Synthesize speech from text. Returns path to WAV or None in stub mode."""
    kokoro = _get_kokoro()

    if kokoro is None:
        print(f"[tts-stub] {text}")
        return None

    try:
        import soundfile as sf

        samples, sr = kokoro.create(text, voice=VOICE, speed=1.0)
        out = Path(output_path or "jarvis_reply.wav")
        sf.write(str(out), samples, sr)
        return out
    except Exception as e:
        print(f"[tts] Synthesis failed: {e}")
        print(f"[tts-stub] {text}")
        return None


def play(text: str):
    """Synthesize and play audio. Falls back to print in stub mode."""
    wav = speak(text)
    if wav is None:
        return

    try:
        import sounddevice as sd
        import soundfile as sf

        data, sr = sf.read(str(wav))
        sd.play(data, sr)
        sd.wait()
    except Exception:
        print(f"[tts] Playback failed - WAV saved to {wav}")


if __name__ == "__main__":
    play("Good morning. V.A.U.L.T. is online.")
