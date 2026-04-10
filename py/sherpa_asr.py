# sherpa_asr.py
import os
import asyncio
from pathlib import Path
from io import BytesIO
from py.get_setting import DEFAULT_ASR_DIR
import platform

# ---------- Placeholders and global variables ----------
_recognizer = None
_last_model_name = None

# ---------- Lazy loading utilities ----------
def _detect_device() -> str:
    """Detect optimal inference device"""
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        if count > 0:
            return 'cuda'
    except Exception:
        pass
        
    return 'cpu'

# Key fix: rename function back to _get_recognizer and add default parameter
def _get_recognizer(model_name: str = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue"):
    """Initialize/get recognizer (lazy loads heavy dependencies)"""
    global _recognizer, _last_model_name

    # If already loaded and model unchanged, return directly
    if _recognizer is not None and model_name == _last_model_name:
        return _recognizer

    # --- Lazy import heavy dependencies ---
    try:
        import sherpa_onnx
    except ImportError as e:
        print("sherpa_onnx library not installed:", e)
        return None

    model_dir = Path(DEFAULT_ASR_DIR) / model_name
    model_path = model_dir / "model.int8.onnx"
    tokens_path = model_dir / "tokens.txt"

    # Check if files exist; if not, return None without raising exception (prevents server.py lifespan crash)
    if not model_path.is_file() or not tokens_path.is_file():
        print(f"Note: Sherpa model files not yet downloaded, ASR feature unavailable. Path: {model_dir}")
        return None

    device = _detect_device()
    print(f"Loading Sherpa-ONNX model [{model_name}] on device [{device}]...")

    try:
        recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=str(model_path),
            tokens=str(tokens_path),
            num_threads=4,
            provider=device,
            use_itn=True,
            debug=False,
        )
        _recognizer = recognizer
        _last_model_name = model_name
        return _recognizer
    except Exception as e:
        print(f"Error loading Sherpa model: {e}")
        return None

# ---------- Core synchronous logic (runs in thread pool) ----------
def _process_audio_sync(recognizer, audio_bytes: bytes) -> str:
    """
    CPU-intensive task executed in thread pool: decode audio + neural network inference
    """
    import soundfile as sf
    import numpy as np

    with BytesIO(audio_bytes) as audio_file:
        audio, sample_rate = sf.read(audio_file, dtype="float32", always_2d=True)
        audio = audio[:, 0]  # Convert to mono
        
        stream = recognizer.create_stream()
        stream.accept_waveform(sample_rate, audio)
        recognizer.decode_stream(stream)
        return stream.result.text

# ---------- Public asynchronous interface ----------
async def sherpa_recognize(audio_bytes: bytes, model_name: str = "sherpa-onnx-sense-voice-zh-en-ja-ko-yue"):
    """
    Async wrapper: offloads heavy inference to thread pool
    """
    try:
        recognizer = _get_recognizer(model_name)
        if recognizer is None:
            raise RuntimeError("ASR model not ready (may not be downloaded or failed to load)")

        text = await asyncio.to_thread(_process_audio_sync, recognizer, audio_bytes)
        return text
    except Exception as e:
        raise RuntimeError(f"Sherpa ASR processing failed: {e}")