import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """사용자 데이터 폴더(설정·사전·캐시)를 테스트마다 격리."""
    home = tmp_path / "home"
    monkeypatch.setenv("LECTURE_TTS_HOME", str(home))
    yield home


@pytest.fixture
def cfg():
    from lecture_tts.config import load_config
    c = load_config(use_user_settings=False)
    c.engine.name = "fake"
    c.audio.format = "wav"
    return c


@pytest.fixture
def sample_md(tmp_path):
    p = tmp_path / "lec 강의.md"  # 한글·공백 경로
    p.write_text(
        "# Lecture 3\n\n"
        "## Slide 1: Welcome\n"
        "Hello everyone, and welcome to lecture three. [pause 1s]\n"
        "Today we'll talk about *neural networks*.\n\n"
        "## Slide 2: What is a Perceptron?\n"
        "A perceptron computes a weighted sum. [pause 500ms]\n"
        "We use {ReLU|R-E-L-U} as the activation function.\n",
        encoding="utf-8",
    )
    return p


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
