"""환경 점검 (초기 설정 마법사·진단 정보 내보내기 공통)."""
from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from dataclasses import asdict, dataclass

from . import __version__, paths


@dataclass
class Check:
    key: str
    name: str
    ok: bool
    detail: str
    required: bool = True
    help_url: str = ""


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def check_environment(repo_id: str = "hexgrad/Kokoro-82M") -> list[Check]:
    from .engines.kokoro_engine import model_cached

    out = []
    ff = paths.find_ffmpeg()
    out.append(Check("ffmpeg", "ffmpeg (mp3 출력)", bool(ff), ff or "찾을 수 없음 — wav 출력만 가능",
                     True, "https://www.gyan.dev/ffmpeg/builds/"))
    if _has("espeakng_loader"):
        out.append(Check("espeak", "espeak-ng (사전 외 단어 발음)", True, "내장 라이브러리(espeakng-loader)", False))
    else:
        exe = shutil.which("espeak-ng")
        out.append(Check("espeak", "espeak-ng (사전 외 단어 발음)", bool(exe), exe or "없음 — 일부 단어 발음 품질 저하 가능",
                         False, "https://github.com/espeak-ng/espeak-ng/releases"))
    has_kokoro = _has("kokoro")
    out.append(Check("kokoro_pkg", "Kokoro 엔진", has_kokoro, "설치됨" if has_kokoro else "pip install kokoro"))
    cached = has_kokoro and model_cached(repo_id)
    out.append(Check("kokoro_model", "Kokoro 모델 (약 330MB)", cached,
                     "다운로드됨" if cached else "아직 없음 — '모델 다운로드'를 누르세요"))
    gpu = "확인 안 됨"
    if has_kokoro:
        try:
            import torch
            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "없음 (CPU로 실행)"
        except Exception:
            pass
    out.append(Check("gpu", "GPU 가속", True, gpu, False))
    return out


def environment_report() -> dict:
    return {
        "app_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "frozen": paths.is_frozen(),
        "checks": [asdict(c) for c in check_environment()],
    }
