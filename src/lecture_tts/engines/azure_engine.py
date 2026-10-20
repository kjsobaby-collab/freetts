"""Azure Speech F0 (무료 티어) 클라우드 엔진 — 선택 사항.

키는 환경변수(AZURE_SPEECH_KEY/REGION) 또는 Windows 자격 증명 관리자(keyring)에서 읽는다.
SSML 태그 문자도 사용량에 포함되므로 SSML 글자 수로 월 사용량을 누적 기록한다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from xml.sax.saxutils import escape

import numpy as np

from .. import paths
from .base import EngineNotReady, TTSEngine

KEYRING_SERVICE = "LectureTTS-Azure"


class QuotaExceeded(RuntimeError):
    pass


def get_credentials(cfg) -> tuple[str | None, str | None]:
    ac = cfg.engines.azure
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    key, region = os.environ.get(ac.key_env), os.environ.get(ac.region_env)
    if not key:
        try:
            import keyring
            key = keyring.get_password(KEYRING_SERVICE, "key")
            region = region or keyring.get_password(KEYRING_SERVICE, "region")
        except Exception:
            pass
    return key, region


def save_credentials(key: str, region: str) -> None:
    import keyring
    keyring.set_password(KEYRING_SERVICE, "key", key)
    keyring.set_password(KEYRING_SERVICE, "region", region)


class UsageTracker:
    def __init__(self):
        self.path = paths.user_data_dir() / "usage.json"
        self._lock = threading.Lock()

    def _month(self) -> str:
        return dt.date.today().strftime("%Y-%m")

    def _data(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def used(self) -> int:
        return int(self._data().get(self._month(), 0))

    def add(self, chars: int) -> None:
        with self._lock:
            d = self._data()
            d[self._month()] = int(d.get(self._month(), 0)) + chars
            self.path.write_text(json.dumps(d), encoding="utf-8")


def build_ssml(text: str, voice: str, rate: float) -> str:
    pct = int(round((rate - 1.0) * 100))
    return (f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f'<voice name="{voice}"><prosody rate="{pct:+d}%">{escape(text)}</prosody></voice></speak>')


class AzureEngine(TTSEngine):
    name = "azure"
    supports_ssml = True
    supports_word_timestamps = True
    is_local = False
    sample_rate = 24000

    def __init__(self, cfg):
        super().__init__(cfg)
        self.max_chars = cfg.engines.azure.max_chars
        self.usage = UsageTracker()
        self._synth = None

    @property
    def version(self) -> str:
        return "azure-neural"

    def problems(self) -> list[str]:
        out = []
        try:
            import azure.cognitiveservices.speech  # noqa: F401
        except ImportError:
            out.append("azure-cognitiveservices-speech 패키지가 없습니다 (pip install azure-cognitiveservices-speech).")
        key, region = get_credentials(self.cfg)
        if not key or not region:
            out.append("Azure Speech 키/지역이 설정되지 않았습니다 (환경설정 또는 환경변수).")
        return out

    def load(self) -> None:
        if self._loaded:
            return
        try:
            import azure.cognitiveservices.speech as speechsdk
        except ImportError as e:
            raise EngineNotReady("azure-cognitiveservices-speech 패키지가 없습니다.") from e
        key, region = get_credentials(self.cfg)
        if not key or not region:
            raise EngineNotReady("Azure Speech 키/지역이 설정되지 않았습니다.")
        sc = speechsdk.SpeechConfig(subscription=key, region=region)
        sc.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Raw24Khz16BitMonoPcm)
        self._synth = speechsdk.SpeechSynthesizer(speech_config=sc, audio_config=None)
        self._sdk = speechsdk
        self._loaded = True

    def remaining_chars(self) -> int:
        return self.cfg.engines.azure.monthly_char_limit - self.usage.used()

    def estimate_cost(self, chars: int) -> float | None:
        return 0.0  # 무료 티어: 한도 내 0원, 한도 초과 시 중단

    def synthesize_array(self, text: str, voice: str, rate: float) -> np.ndarray:
        if not self._loaded:
            self.load()
        ssml = build_ssml(text, voice, rate)
        if len(ssml) > self.remaining_chars():
            raise QuotaExceeded("Azure 무료 티어 월 한도를 초과합니다.")
        result = self._synth.speak_ssml_async(ssml).get()
        if result.reason != self._sdk.ResultReason.SynthesizingAudioCompleted:
            details = getattr(result, "cancellation_details", None)
            raise RuntimeError(f"Azure 합성 실패: {getattr(details, 'error_details', result.reason)}")
        self.usage.add(len(ssml))
        return np.frombuffer(result.audio_data, dtype=np.int16).astype(np.float32) / 32768.0

    def list_voices(self) -> list[str]:
        return ["en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-DavisNeural",
                "en-GB-SoniaNeural", "en-GB-RyanNeural"]
