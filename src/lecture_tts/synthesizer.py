"""병렬 합성 오케스트레이션: 캐시 확인 → 동시성 제한 → 재시도 → 캐시 저장."""
from __future__ import annotations

import asyncio
import logging
import time

from .cache import TTSCache
from .config import RuntimeConfig
from .engines.base import EngineNotReady, TTSEngine
from .models import AudioClip, Chunk
from .progress import BuildCancelled, CancelToken, ProgressReporter

log = logging.getLogger("lecture_tts")


class ChunkFailed(Exception):
    def __init__(self, chunk: Chunk, error: Exception):
        super().__init__(f"{chunk.id}: {error}")
        self.chunk, self.error = chunk, error


async def retry_async(fn, *args, retries: int = 3, base_delay: float = 1.0):
    for attempt in range(retries + 1):
        try:
            return await fn(*args)
        except (EngineNotReady, BuildCancelled):
            raise
        except Exception as e:
            non_retryable = type(e).__name__ in ("QuotaExceeded", "ValueError")
            if attempt >= retries or non_retryable:
                raise
            delay = base_delay * (2 ** attempt)
            log.warning("합성 실패, %.0fs 후 재시도 (%d/%d): %s", delay, attempt + 1, retries, e)
            await asyncio.sleep(delay)


class Synthesizer:
    def __init__(self, engine: TTSEngine, cache: TTSCache, runtime: RuntimeConfig,
                 reporter: ProgressReporter | None = None, cancel: CancelToken | None = None):
        self.engine, self.cache, self.runtime = engine, cache, runtime
        self.reporter = reporter or ProgressReporter()
        self.cancel = cancel
        self.sem = asyncio.Semaphore(runtime.concurrency)
        self.synthesized = 0
        self.cached = 0

    async def _one(self, chunk: Chunk) -> AudioClip:
        if not chunk.text:
            return AudioClip(chunk.id, "", 0)
        if hit := self.cache.get(chunk.cache_key, chunk.id):
            self.cached += 1
            self.reporter.chunk_done(chunk.section_index, chunk.id, True, len(chunk.text), 0.0)
            return hit
        async with self.sem:
            if self.cancel and self.cancel.cancelled:   # 중지 요청 확인
                raise BuildCancelled()
            t0 = time.perf_counter()
            try:
                clip = await retry_async(self.engine.synthesize, chunk, self.cache.path_for(chunk.cache_key),
                                         retries=self.runtime.max_retries)
            except (EngineNotReady, BuildCancelled):
                raise
            except Exception as e:
                log.error("청크 실패 %s (%s…): %s", chunk.id, chunk.text[:40], e)
                self.reporter.error(chunk.id, str(e))
                raise ChunkFailed(chunk, e) from e
            elapsed = time.perf_counter() - t0
        clip.chunk_id = chunk.id
        self.cache.put(chunk.cache_key, clip)            # 완료분은 캐시에 남김
        self.synthesized += 1
        self.reporter.chunk_done(chunk.section_index, chunk.id, False, len(chunk.text), elapsed)
        return clip

    async def run(self, chunks: list[Chunk]) -> tuple[dict[str, AudioClip], list[ChunkFailed]]:
        results = await asyncio.gather(*(self._one(c) for c in chunks), return_exceptions=True)
        clips: dict[str, AudioClip] = {}
        failures: list[ChunkFailed] = []
        for c, r in zip(chunks, results):
            if isinstance(r, AudioClip):
                clips[c.id] = r
            elif isinstance(r, ChunkFailed):
                failures.append(r)
            elif isinstance(r, BaseException):
                raise r
        return clips, failures
