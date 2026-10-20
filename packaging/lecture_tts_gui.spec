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
