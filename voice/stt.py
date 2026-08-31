"""Speech-to-text wrapper around faster-whisper.

Auto-detects CUDA (RTX 3050) and falls back to CPU if unavailable.
Model is auto-downloaded on first run by faster-whisper - no manual download.

GPU acceleration needs cuBLAS + cuDNN, installed as pip packages:
    pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
The full CUDA Toolkit is NOT required. _register_cuda_dlls() below puts those
pip-installed DLLs on the search path so GPU mode works without touching PATH.
"""

import os
import sys
from pathlib import Path

_model = None
_device = None
_dlls_registered = False

MODEL_SIZE = "base"  # base is fast; upgrade to "small" or "medium" for accuracy


def _register_cuda_dlls():
    """Make pip-installed NVIDIA DLLs discoverable on Windows.

    The nvidia-* wheels drop their DLLs in site-packages/nvidia/<lib>/bin,
    which Windows does not search by default.

    Both mechanisms are needed, and it is not belt-and-braces:

    * os.add_dll_directory() covers loads that use LOAD_LIBRARY_SEARCH_*
      flags — enough for CTranslate2 to construct a CUDA model.
    * Prepending PATH covers plain LoadLibrary calls, which ignore the
      added-directory list entirely. CTranslate2 pulls in cuBLAS this way, and
      lazily — at the first encode, not at model load. With only the first
      mechanism, constructing the model succeeds and transcription then dies
      with "cublas64_12.dll is not found".

    No-op on non-Windows, where the wheels handle their own rpaths.
    """
    global _dlls_registered
    if _dlls_registered or sys.platform != "win32":
        return
    _dlls_registered = True

    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return

    bin_dirs = [str(p) for p in nvidia_root.glob("*/bin") if p.is_dir()]
    if not bin_dirs:
        return

    for bin_dir in bin_dirs:
        try:
            os.add_dll_directory(bin_dir)
        except (OSError, AttributeError):
            pass

    existing = os.environ.get("PATH", "")
    missing = [d for d in bin_dirs if d.lower() not in existing.lower()]
    if missing:
        os.environ["PATH"] = os.pathsep.join(missing) + os.pathsep + existing


def _get_model():
    global _model, _device
    if _model is not None:
        return _model

    _register_cuda_dlls()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[stt] faster-whisper not installed - run: pip install faster-whisper")
        return None

    for device, compute in [("cuda", "float16"), ("cpu", "int8")]:
        try:
            _model = WhisperModel(MODEL_SIZE, device=device, compute_type=compute)
            _device = device
            print(f"[stt] Loaded {MODEL_SIZE} model on {device} ({compute})")
            return _model
        except Exception:
            continue

    print("[stt] Failed to load whisper model on any device")
    return None


def transcribe(audio_path: str | Path) -> str:
    """Transcribe a WAV file and return the text."""
    model = _get_model()
    if model is None:
        return "[STT unavailable — model not loaded]"

    path = Path(audio_path)
    if not path.exists():
        return f"[STT error — file not found: {path}]"

    segments, info = model.transcribe(str(path), language="en")
    text = " ".join(seg.text for seg in segments).strip()
    return text


def is_loaded() -> bool:
    """True if the model is already in memory.

    Lets callers check the device without triggering a load — get_device()
    would otherwise pull the model into VRAM as a side effect.
    """
    return _model is not None


def get_device() -> str:
    """Return which device STT is running on. Loads the model if needed."""
    _get_model()
    return _device or "none"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python stt.py <audio.wav>")
    else:
        result = transcribe(sys.argv[1])
        print(f"[{get_device()}] {result}")
