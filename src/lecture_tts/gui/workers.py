"""작업 스레드: EngineHost(엔진 상주 + 빌드/즉시 듣기), TaskThread(일반 장시간 작업)."""
from __future__ import annotations

import asyncio
import logging
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot

from ..config import AppConfig
from ..engines import TTSEngine, create_engine
from ..progress import CancelToken, ProgressReporter

log = logging.getLogger("lecture_tts")


class QtProgressReporter(ProgressReporter):
    def __init__(self, host: "EngineHost"):
        self.h = host

    def plan_ready(self, total_chunks, total_chars, cached_chunks):
        self.h.planReady.emit(total_chunks, total_chars, cached_chunks)

    def section_started(self, index, total_chunks):
        self.h.sectionStarted.emit(index, total_chunks)

    def chunk_done(self, section, chunk_id, cached, chars, seconds):
        self.h.chunkDone.emit(section, chunk_id, cached, chars, seconds)

    def section_done(self, index, audio_path):
        self.h.sectionDone.emit(index, audio_path)

    def message(self, level, text):
        self.h.message.emit(level, text)

    def error(self, where, message):
        self.h.chunkFailed.emit(where, message)


def _engine_key(cfg: AppConfig) -> str:
    ec = cfg.engine_cfg().model_dump(exclude={"voice", "lang_code"})
    return f"{cfg.engine.name}:{sorted(ec.items())}"


class EngineHost(QObject):
    """엔진(모델)을 작업 스레드에 1회 로드해 상주시키고, 요청을 순서대로 처리한다.
    엔진 종류나 엔진 설정이 바뀔 때만 다시 로드한다."""

    engineLoading = Signal(str)
    engineReady = Signal(str)
    planReady = Signal(int, int, int)
    sectionStarted = Signal(int, int)
    chunkDone = Signal(int, str, bool, int, float)
    chunkFailed = Signal(str, str)
    sectionDone = Signal(int, str)
    message = Signal(str, str)
    buildFinished = Signal(object)          # BuildResult
    buildFailed = Signal(str, str)          # 요약, 상세
    speakReady = Signal(str, str)           # tag, wav 경로
    speakFailed = Signal(str, str)          # tag, 메시지

    def __init__(self):
        super().__init__()
        self.engine: TTSEngine | None = None
        self._key = ""
        self.cancel_token = CancelToken()
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="lecture_tts_"))

    def _ensure_engine(self, cfg: AppConfig) -> TTSEngine:
        key = _engine_key(cfg)
        if self.engine is None or key != self._key:
            self.engine = create_engine(cfg)
            self._key = key
        if not self.engine.loaded:
            problems = self.engine.problems()
            if problems:
                from ..engines import EngineNotReady
                raise EngineNotReady("\n".join(problems))
            self.engineLoading.emit(cfg.engine.name)
            self.engine.load()
            self.engineReady.emit(cfg.engine.name)
        return self.engine

    @Slot(object, str, object, bool)
    def build(self, cfg: AppConfig, script_path: str, sections, use_cache: bool) -> None:
        from ..pipeline import run_pipeline

        self.cancel_token.reset()
        try:
            engine = self._ensure_engine(cfg)
            result = asyncio.run(run_pipeline(Path(script_path), cfg, sections=sections or None,
                                              reporter=QtProgressReporter(self), cancel=self.cancel_token,
                                              engine=engine, use_cache=use_cache))
            self.buildFinished.emit(result)
        except Exception as e:
            log.exception("빌드 실패")
            self.buildFailed.emit(str(e), traceback.format_exc())

    @Slot(object, str, str)
    def speak(self, cfg: AppConfig, text: str, tag: str) -> None:
        from ..assembler import export_audio
        from ..pipeline import synthesize_text

        try:
            engine = self._ensure_engine(cfg)
            audio, sr = asyncio.run(synthesize_text(text, cfg, engine))
            safe = "".join(ch if ch.isalnum() else "_" for ch in tag)[:60]
            path = export_audio(audio, sr, self.tmp_dir / f"{safe}_{abs(hash((text, tag))) % 10**8}", "wav")
            self.speakReady.emit(tag, str(path))
        except Exception as e:
            log.exception("즉시 합성 실패")
            self.speakFailed.emit(tag, str(e))


class TaskThread(QThread):
    """함수 하나를 백그라운드에서 실행. fn(progress)에 진행률 콜백을 넘긴다."""

    progressed = Signal(int, int, str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self.fn(lambda i, n, msg: self.progressed.emit(i, n, msg)))
        except Exception as e:
            log.exception("작업 실패")
            self.failed.emit(str(e))
