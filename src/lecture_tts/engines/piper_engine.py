"""Piper (MIT) 경량 로컬 엔진 — 빠른 초안·저사양 PC용. `pip install piper-tts` 필요."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from .. import paths
from .base import EngineNotReady, TTSEngine

HF_REPO = "rhasspy/piper-voices"
KNOWN_VOICES = [
    "en_US-lessac-high", "en_US-lessac-medium", "en_US-amy-medium", "en_US-ryan-high",
    "en_US-libritts-high", "en_GB-alba-medium", "en_GB-northern_english_male-medium",
]


def piper_dir() -> Path:
    p = paths.models_dir() / "piper"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _hf_path(voice: str) -> str:
    lang, name, quality = voice.split("-", 2)
    return f"{lang.split('_')[0]}/{lang}/{name}/{quality}/{voice}"


def download_voice(voice: str) -> Path:
    from huggingface_hub import hf_hub_download
    import shutil

    base = _hf_path(voice)
    for ext in (".onnx", ".onnx.json"):
        src = hf_hub_download(HF_REPO, base + ext)
        shutil.copyfile(src, piper_dir() / f"{voice}{ext}")
    return piper_dir() / f"{voice}.onnx"


class PiperEngine(TTSEngine):
    name = "piper"

    def __init__(self, cfg):
        super().__init__(cfg)
        pc = cfg.engines.piper
        self.max_chars = pc.max_chars
        self.voice_name = pc.voice
        self.model_path = Path(pc.model_path) if pc.model_path else piper_dir() / f"{pc.voice}.onnx"
        self._voice = None
        self._lock = threading.Lock()
        cfg_json = self.model_path.with_suffix(".onnx.json")
        if cfg_json.exists():
            try:
                self.sample_rate = json.loads(cfg_json.read_text(encoding="utf-8"))["audio"]["sample_rate"]
            except (KeyError, ValueError):
                pass

    @property
    def version(self) -> str:
        return f"piper-{self.model_path.stem}"

    def problems(self) -> list[str]:
        out = []
        try:
            import piper  # noqa: F401
        except ImportError:
            out.append("piper-tts 패키지가 설치되지 않았습니다 (pip install piper-tts).")
        if not self.model_path.exists():
            out.append(f"Piper 음성 모델이 없습니다: {self.model_path} (`lecture-tts setup piper`)")
        return out

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                from piper import PiperVoice
            except ImportError as e:
                raise EngineNotReady("piper-tts 패키지가 설치되지 않았습니다.") from e
            if not self.model_path.exists():
                raise EngineNotReady(f"Piper 음성 모델이 없습니다: {self.model_path}")
            self._voice = PiperVoice.load(str(self.model_path))
            self.sample_rate = self._voice.config.sample_rate
            self._loaded = True

    def synthesize_array(self, text: str, voice: str, rate: float) -> np.ndarray:
        if not self._loaded:
            self.load()
        with self._lock:
            try:  # piper-tts >= 1.3
                from piper import SynthesisConfig
                syn = SynthesisConfig(length_scale=1.0 / max(rate, 0.1))
                parts = [c.audio_float_array for c in self._voice.synthesize(text, syn_config=syn)]
            except ImportError:  # 구버전: int16 바이트 스트림
                raw = b"".join(self._voice.synthesize_stream_raw(text, length_scale=1.0 / max(rate, 0.1)))
                parts = [np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0]
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, dtype=np.float32)

    def list_voices(self) -> list[str]:
        local = sorted(p.stem for p in piper_dir().glob("*.onnx"))
        return sorted(set(local) | set(KNOWN_VOICES))
