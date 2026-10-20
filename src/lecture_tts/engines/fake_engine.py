"""테스트용 엔진: 글자 수에 비례한 길이의 낮은 사인파를 반환한다 (모델 불필요)."""
from __future__ import annotations

import numpy as np

from .base import TTSEngine


class FakeEngine(TTSEngine):
    name = "fake"
    sample_rate = 24000

    def __init__(self, cfg):
        super().__init__(cfg)
        self.max_chars = cfg.engines.fake.max_chars
        self.calls: list[str] = []

    def synthesize_array(self, text: str, voice: str, rate: float) -> np.ndarray:
        self.calls.append(text)
        dur = max(0.05, len(text) * self.cfg.engines.fake.ms_per_char / 1000 / max(rate, 0.1))
        t = np.arange(int(dur * self.sample_rate)) / self.sample_rate
        freq = 220 + (sum(map(ord, voice)) % 5) * 40
        return (0.2 * np.sin(2 * np.pi * freq * t)).astype(np.float32)

    def list_voices(self) -> list[str]:
        return ["sine"]
