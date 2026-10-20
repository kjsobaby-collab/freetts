"""TTS 엔진 추상 클래스.

엔진 객체 생성은 가볍게(설정만 보관), 모델 로딩은 load()에서 1회만 한다.
그래서 GUI는 모델을 올리지 않고도 청크 계획·캐시 키 계산을 할 수 있다.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path

import numpy as np
import soundfile as sf

from ..config import AppConfig
from ..models import AudioClip, Chunk


class EngineNotReady(RuntimeError):
    """모델 미다운로드·키 누락 등으로 엔진을 쓸 수 없음."""


class TTSEngine(ABC):
    name: str = "base"
    max_chars: int = 400
    supports_ssml: bool = False
    supports_word_timestamps: bool = False
    sample_rate: int = 24000
    is_local: bool = True

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self._loaded = False

    # --- 수명 주기 ---------------------------------------------------------
    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """무거운 초기화(모델 로드). 여러 번 호출해도 1회만 수행."""
        self._loaded = True

    def problems(self) -> list[str]:
        """실행 전 점검: 비어 있으면 사용 가능."""
        return []

    @property
    def version(self) -> str:
        return "1"

    # --- 합성 --------------------------------------------------------------
    @abstractmethod
    def synthesize_array(self, text: str, voice: str, rate: float) -> np.ndarray:
        """float32 mono, self.sample_rate."""

    async def synthesize(self, chunk: Chunk, out_path: Path) -> AudioClip:
        if not self._loaded:
            await asyncio.to_thread(self.load)
        audio = await asyncio.to_thread(self.synthesize_array, chunk.text, chunk.voice, chunk.rate)
        write_wav_atomic(out_path, audio, self.sample_rate)
        return AudioClip(chunk.id, str(out_path), int(round(len(audio) / self.sample_rate * 1000)))

    def list_voices(self) -> list[str]:
        return []

    def default_voice(self) -> str:
        return self.cfg.engine_cfg(self.name).voice  # type: ignore[attr-defined]

    def estimate_cost(self, chars: int) -> float | None:
        return None


def write_wav_atomic(path: Path, audio: np.ndarray, sr: int) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".wav", dir=path.parent)
    os.close(fd)
    try:
        sf.write(tmp, np.asarray(audio, dtype=np.float32), sr, subtype="PCM_16")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
