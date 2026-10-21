# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 설정 (--onedir). 빌드: packaging\build.ps1 (CPU용 torch 가상환경에서 실행)
#   onefile은 torch 압축 해제 때문에 시작이 매우 느려 사용하지 않는다.
#   Qt(LGPL)는 onedir 기본 동작대로 동적 링크 DLL로 남겨 사용자가 교체할 수 있게 한다.
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = Path(SPECPATH).parent
SRC = ROOT / "src"

datas, binaries, hiddenimports = [], [], []
# Kokoro·misaki(G2P)·spaCy 영어 모델·espeak-ng 라이브러리는 데이터 파일까지 통째로 수집
for pkg in ("kokoro", "misaki", "espeakng_loader", "en_core_web_sm", "spacy", "thinc", "language_tags",
            "num2words", "phonemizer"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
for pkg in ("kokoro", "misaki", "spacy", "en_core_web_sm", "torch", "huggingface_hub", "tqdm", "regex",
            "requests", "packaging", "filelock", "numpy", "tokenizers", "safetensors"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass
datas += [(str(SRC / "lecture_tts" / "data"), "lecture_tts/data")]
hiddenimports += ["lecture_tts.gui.app", "PySide6.QtMultimedia"]

a = Analysis(
    [str(ROOT / "packaging" / "launch_gui.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard"],
    noarchive=False,
)

# Qt 6(PySide6)는 MSVC 런타임 14.40 이상이 필요하다. 다른 패키지가 끌고 온 구버전 msvcp140.dll(14.27 등)이
# 앱 최상위(_internal\)에 들어가면 QtCore 로드가 "지정된 프로시저를 찾을 수 없습니다"로 실패하므로,
# 최상위 런타임 DLL은 PySide6에 동봉된 최신본으로 교체한다.
import PySide6

QT_DIR = Path(PySide6.__file__).parent
VCRT = {"msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "vcruntime140.dll", "vcruntime140_1.dll"}


def _newer_vcrt(entry):
    dest, src, typecode = entry
    name = Path(dest).name
    if Path(dest).parent == Path(".") and name.lower() in VCRT and (QT_DIR / name).is_file():
        return (dest, str(QT_DIR / name), typecode)
    return entry


a.binaries = [_newer_vcrt(e) for e in a.binaries]
# Qt 6는 Windows 10/11 시스템 ICU(System32\icuuc.dll)를 쓴다. 빌드 PC의 PATH(예: Anaconda)에서 딸려 온
# 구버전 ICU가 앱 최상위에 들어가면 QtCore 로드가 실패하므로 제외한다.
a.binaries = [e for e in a.binaries
              if not (Path(e[0]).parent == Path(".") and Path(e[0]).name.lower().startswith("icu"))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="LectureTTS",
    console=False,
    icon=str(ROOT / "packaging" / "icon.ico") if (ROOT / "packaging" / "icon.ico").exists() else None,
    version=str(ROOT / "packaging" / "version_info.txt") if (ROOT / "packaging" / "version_info.txt").exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="LectureTTS", upx=False)
