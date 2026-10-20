"""진행 상황 보고와 중지 토큰 (CLI·GUI 공통)."""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("lecture_tts")


class BuildCancelled(Exception):
    """사용자가 중지를 요청함."""


class ProgressReporter:
    """기본 구현은 아무것도 하지 않는다. CLI는 Rich, GUI는 Qt 시그널로 구현."""

    def plan_ready(self, total_chunks: int, total_chars: int, cached_chunks: int) -> None: ...
    def section_started(self, index: int, total_chunks: int) -> None: ...
    def chunk_done(self, section: int, chunk_id: str, cached: bool, chars: int, seconds: float) -> None: ...
    def section_done(self, index: int, audio_path: str) -> None: ...
    def message(self, level: str, text: str) -> None: ...
    def error(self, where: str, message: str) -> None: ...


NullReporter = ProgressReporter


class LoggingReporter(ProgressReporter):
    def message(self, level: str, text: str) -> None:
        log.log(logging.WARNING if level == "warning" else logging.INFO, text)

    def error(self, where: str, message: str) -> None:
        log.error("%s: %s", where, message)


class CancelToken:
    def __init__(self) -> None:
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def reset(self) -> None:
        self._cancelled.clear()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise BuildCancelled()
