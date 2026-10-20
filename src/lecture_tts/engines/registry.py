"""엔진 이름 → 클래스 매핑. 새 엔진은 어댑터 클래스를 만들고 여기에 등록하면 된다."""
from __future__ import annotations

from ..config import AppConfig
from .azure_engine import AzureEngine
from .base import TTSEngine
from .fake_engine import FakeEngine
from .kokoro_engine import KokoroEngine
from .piper_engine import PiperEngine

ENGINES: dict[str, type[TTSEngine]] = {
    "kokoro": KokoroEngine,
    "piper": PiperEngine,
    "azure": AzureEngine,
    "fake": FakeEngine,
}

ENGINE_LABELS = {
    "kokoro": "Kokoro (로컬, 기본)",
    "piper": "Piper (로컬, 경량)",
    "azure": "Azure Speech F0 (클라우드)",
    "fake": "Fake (테스트용)",
}


def create_engine(cfg: AppConfig, name: str | None = None) -> TTSEngine:
    name = name or cfg.engine.name
    if name not in ENGINES:
        raise ValueError(f"알 수 없는 엔진: {name} (사용 가능: {', '.join(ENGINES)})")
    return ENGINES[name](cfg)
