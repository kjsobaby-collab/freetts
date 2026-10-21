"""Kokoro (82M, Apache 2.0) 로컬 엔진 — 기본 엔진.

- 모델(KModel)은 1회만 로드하고, 언어(a=미국, b=영국)별 KPipeline이 이를 공유한다.
- 첫 실행 시 Hugging Face에서 가중치를 받으므로 `lecture-tts setup kokoro`로 미리 받아 둔다.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from .base import EngineNotReady, TTSEngine

log = logging.getLogger("lecture_tts")

MODEL_FILE = "kokoro-v1_0.pth"
CONFIG_FILE = "config.json"

VOICES = [
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole",
    "af_nova", "af_river", "af_sarah", "af_sky",
    "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa",
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


def describe_voice(v: str) -> str:
    accent = {"a": "미국", "b": "영국"}.get(v[:1], "?")
    gender = {"f": "여성", "m": "남성"}.get(v[1:2], "?")
    return f"{v} ({accent} {gender})"


def model_cached(repo_id: str = "hexgrad/Kokoro-82M") -> bool:
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    return all(isinstance(try_to_load_from_cache(repo_id, f), str) for f in (MODEL_FILE, CONFIG_FILE))


def download_model(repo_id: str = "hexgrad/Kokoro-82M", voices: list[str] | None = None,
                   progress: Callable[[int, int, str], None] | None = None) -> None:
    """모델·음성 파일을 내려받는다 (huggingface_hub가 이어받기·재시도 처리)."""
    from huggingface_hub import hf_hub_download

    files = [CONFIG_FILE, MODEL_FILE] + [f"voices/{v}.pt" for v in (voices or VOICES)]
    for i, f in enumerate(files):
        if progress:
            progress(i, len(files), f)
        for attempt in range(3):
            try:
                hf_hub_download(repo_id, f)
                break
            except Exception as e:  # 네트워크 오류 → 재시도
                if attempt == 2:
                    raise
                log.warning("다운로드 재시도 %s: %s", f, e)
    if progress:
        progress(len(files), len(files), "완료")


class KokoroEngine(TTSEngine):
    name = "kokoro"
    supports_ssml = False

    def __init__(self, cfg):
        super().__init__(cfg)
        kc = cfg.engines.kokoro
        self.max_chars = kc.max_chars
        self.repo_id = kc.repo_id
        self.device_pref = kc.device
        self.model = None
        self.pipelines: dict[str, object] = {}
        self._lock = threading.Lock()

    @property
    def version(self) -> str:
        try:
            from importlib.metadata import version
            return f"kokoro-{version('kokoro')}-v1_0"
        except Exception:
            return "kokoro-v1_0"

    def problems(self) -> list[str]:
        out = []
        import importlib.util

        # 실제 import(torch 포함, 수십 초)는 하지 않는다 — GUI 메인 스레드에서 불려도 멈추지 않게
        if importlib.util.find_spec("kokoro") is None:
            out.append("kokoro 패키지가 설치되지 않았습니다 (pip install kokoro).")
            return out
        if not model_cached(self.repo_id):
            out.append("Kokoro 모델이 없습니다. 초기 설정 마법사 또는 `lecture-tts setup kokoro`로 내려받으세요.")
        return out

    def _device(self) -> str:
        if self.device_pref != "auto":
            return self.device_pref
        import torch
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def load(self) -> None:
        with self._lock:
            if self._loaded:
                return
            try:
                from kokoro import KModel
            except ImportError as e:
                raise EngineNotReady("kokoro 패키지가 설치되지 않았습니다.") from e
            device = self._device()
            log.info("Kokoro 모델 로드 중 (device=%s)", device)
            self.model = KModel(repo_id=self.repo_id).to(device).eval()
            self._loaded = True

    def _pipeline(self, lang: str):
        if lang not in self.pipelines:
            from kokoro import KPipeline
            self.pipelines[lang] = KPipeline(lang_code=lang, repo_id=self.repo_id, model=self.model)
        return self.pipelines[lang]

    def synthesize_array(self, text: str, voice: str, rate: float) -> np.ndarray:
        if not self._loaded:
            self.load()
        lang = voice[0] if voice[:1] in ("a", "b") else self.cfg.engines.kokoro.lang_code
        with self._lock:  # 모델 1개를 순차 실행
            pipe = self._pipeline(lang)
            parts = []
            for result in pipe(text, voice=voice, speed=rate, split_pattern=None):
                audio = result.audio
                if audio is None:
                    continue
                parts.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, dtype=np.float32)

    def list_voices(self) -> list[str]:
        return list(VOICES)
