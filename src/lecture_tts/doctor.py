"""환경 점검 (초기 설정 마법사·진단 정보 내보내기 공통)."""
from __future__ import annotations

import importlib.util
import platform
import shutil
import sys
from collections.abc import Callable
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


CHECK_STEPS = ["ffmpeg 확인", "espeak-ng 확인", "Kokoro 엔진 불러오기", "Kokoro 모델 확인", "GPU 확인"]


def check_environment(repo_id: str = "hexgrad/Kokoro-82M",
                      progress: Callable[[int, int, str], None] | None = None) -> list[Check]:
    """구성 요소를 차례로 점검한다. 엔진 import(torch 포함)는 처음에 수십 초 걸릴 수 있으므로
    GUI에서는 작업 스레드에서 호출하고 progress(i, n, 단계 이름)로 진행 상황을 보여 준다."""
    from .engines.kokoro_engine import model_cached

    def step(i: int) -> None:
        if progress:
            progress(i, len(CHECK_STEPS), CHECK_STEPS[i])

    out = []
    step(0)
    ff = paths.find_ffmpeg()
    out.append(Check("ffmpeg", "ffmpeg (mp3 출력)", bool(ff), ff or "찾을 수 없음 — wav 출력만 가능",
                     True, "https://www.gyan.dev/ffmpeg/builds/"))
    step(1)
    if _has("espeakng_loader"):
        out.append(Check("espeak", "espeak-ng (사전 외 단어 발음)", True, "내장 라이브러리(espeakng-loader)", False))
    else:
        exe = shutil.which("espeak-ng")
        out.append(Check("espeak", "espeak-ng (사전 외 단어 발음)", bool(exe), exe or "없음 — 일부 단어 발음 품질 저하 가능",
                         False, "https://github.com/espeak-ng/espeak-ng/releases"))
    step(2)
    has_kokoro = _has("kokoro")
    detail = "설치됨" if has_kokoro else "pip install kokoro"
    if has_kokoro:
        try:  # 실제로 불러와 본다 (한 번 불러오면 이후 생성 시작이 빨라진다)
            import kokoro  # noqa: F401
        except Exception as e:
            has_kokoro, detail = False, f"불러오기 실패: {e}"
    out.append(Check("kokoro_pkg", "Kokoro 엔진", has_kokoro, detail))
    step(3)
    cached = has_kokoro and model_cached(repo_id)
    out.append(Check("kokoro_model", "Kokoro 모델 (약 330MB)", cached,
                     "다운로드됨" if cached else "아직 없음 — '모델 다운로드'를 누르세요"))
    step(4)
    gpu = "확인 안 됨"
    if has_kokoro:
        try:
            import torch
            gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "없음 (CPU로 실행)"
        except Exception:
            pass
    out.append(Check("gpu", "GPU 가속", True, gpu, False))
    if progress:
        progress(len(CHECK_STEPS), len(CHECK_STEPS), "완료")
    return out


def environment_report() -> dict:
    return {
        "app_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "frozen": paths.is_frozen(),
        "checks": [asdict(c) for c in check_environment()],
    }
