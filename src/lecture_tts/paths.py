"""앱/사용자 데이터 경로와 외부 프로그램(ffmpeg) 위치 관리.

앱 폴더(설치 위치)와 사용자 데이터 폴더(%LOCALAPPDATA%\\LectureTTS)를 분리해
업데이트 설치 시에도 설정·발음 사전·캐시·모델이 유지되게 한다.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import APP_NAME

DATA_DIR = Path(__file__).resolve().parent / "data"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """설치된 앱 폴더(배포판) 또는 저장소 루트(개발 환경)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def data_file(name: str) -> Path:
    """패키지에 포함된 리소스 파일 (기본 설정, 예제, 도움말 등)."""
    return DATA_DIR / name


def user_data_dir() -> Path:
    base = os.environ.get("LECTURE_TTS_HOME")
    if base:
        p = Path(base)
    elif sys.platform == "win32":
        p = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif sys.platform == "darwin":
        p = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        p = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = user_data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def models_dir() -> Path:
    p = user_data_dir() / "models"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_cache_dir() -> Path:
    return user_data_dir() / "cache" / "tts"


def user_settings_path() -> Path:
    return user_data_dir() / "settings.yaml"


def user_lexicon_path() -> Path:
    """사용자 발음 사전. 없으면 패키지 기본 사전을 복사해 만든다."""
    p = user_data_dir() / "lexicon.yaml"
    if not p.exists():
        shutil.copyfile(data_file("lexicon.yaml"), p)
    return p


def bundled_bin_dirs() -> list[Path]:
    root = app_root()
    return [root / "bin", root / "packaging" / "bin"]


def find_ffmpeg() -> str | None:
    exe = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    for d in bundled_bin_dirs():
        if (d / exe).is_file():
            return str(d / exe)
    return shutil.which("ffmpeg")


def setup_runtime_env() -> None:
    """프로세스 시작 시 1회 호출: 동봉 bin을 PATH 앞에 두고, 배포판은 모델 위치를 사용자 폴더로 지정."""
    for d in bundled_bin_dirs():
        if d.is_dir():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
    if is_frozen() or os.environ.get("LECTURE_TTS_MODELS"):
        bundled = app_root() / "models"  # 오프라인 설치 패키지는 모델을 앱 폴더에 포함
        target = os.environ.get("LECTURE_TTS_MODELS") or (str(bundled) if bundled.is_dir() else str(models_dir()))
        os.environ.setdefault("HF_HOME", target)
    # 콘솔 없는 Windows GUI에서 tqdm 등이 sys.stderr=None 때문에 죽지 않도록
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
