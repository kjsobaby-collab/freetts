"""엔진 입력 한도에 맞춰 문장 단위로 청크를 묶는다.

규칙
 1. 섹션 경계에서는 항상 끊는다.
 2. 화자/속도 변경(= 문단 분리)에서 끊는다.
 3. 문단 경계에서 끊고, 문단 간 쉼(paragraph_pause_ms)을 trailing_pause_ms로 기록한다.
 4. [pause]가 있으면 그 자리에서 끊는다 (SSML 미지원 엔진은 무음 삽입으로 처리).
 5. 한 문장이 max_chars를 넘으면 쉼표·세미콜론 → 공백 기준으로 재분할한다.
 6. min_chars 미만의 짧은 청크는 다음 문장과 합친다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import AppConfig
from .models import Chunk, LectureDocument, Segment


@dataclass
class _Group:
    segs: list[Segment] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(s.spoken_text for s in self.segs if s.spoken_text)

    @property
    def display(self) -> str:
        return " ".join(s.display_text for s in self.segs if s.display_text)


def split_long(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    parts = [p.strip() for p in re.split(r"(?<=[,;:])\s+", text) if p.strip()]
    out: list[str] = []
    cur = ""
    for p in parts:
        if len(p) > max_chars:  # 쉼표로도 안 되면 공백 기준
            words, p = p.split(), ""
            for w in words:
                if cur and len(cur) + len(w) + 1 > max_chars:
                    out.append(cur)
                    cur = w
                else:
                    cur = f"{cur} {w}".strip()
            continue
        if cur and len(cur) + len(p) + 1 > max_chars:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def split_display(display: str, n: int, weights: list[int]) -> list[str]:
    """표시용 텍스트를 n조각으로 단어 수 비율에 맞춰 나눈다 (자막용)."""
    words = display.split()
    total = sum(weights) or 1
    out, pos = [], 0
    for i, w in enumerate(weights):
        take = len(words) - pos if i == n - 1 else max(1, round(len(words) * w / total))
        out.append(" ".join(words[pos:pos + take]))
        pos += take
    return out


class Chunker:
    def __init__(self, cfg: AppConfig, engine_max_chars: int, voices: set[str] | None = None):
        self.cfg = cfg
        self.max_chars = cfg.chunking.max_chars or engine_max_chars
        self.min_chars = cfg.chunking.min_chars
        self.strategy = cfg.chunking.strategy
        self.voices = voices  # 엔진이 지원하는 음성 (None이면 검사 안 함)

    def resolve_voice(self, speaker: str, para_rate: float) -> tuple[str, float]:
        sp = self.cfg.speakers.get(speaker) or self.cfg.speakers.get("default")
        voice = self.cfg.voice
        rate = self.cfg.engine.rate * para_rate
        if sp is not None:
            if sp.voice and (self.voices is None or sp.voice in self.voices):
                voice = sp.voice
            rate *= sp.rate
        return voice, round(rate, 3)

    def split(self, doc: LectureDocument) -> list[Chunk]:
        chunks: list[Chunk] = []
        for sec in doc.sections:
            seq = 0
            sec_chunks: list[Chunk] = []
            for pi, para in enumerate(sec.paragraphs):
                voice, rate = self.resolve_voice(para.speaker, para.rate)
                for g in self._groups(para.segments):
                    pause = g.segs[-1].pause_after_ms
                    text = g.text
                    if not text:  # 문단 맨 앞 [pause] 등 텍스트 없는 쉼
                        if sec_chunks:
                            sec_chunks[-1].trailing_pause_ms += pause
                            continue
                    parts = split_long(text, self.max_chars) if text else [""]
                    displays = split_display(g.display, len(parts), [len(p) for p in parts]) \
                        if len(parts) > 1 else [g.display]
                    for i, (p, d) in enumerate(zip(parts, displays)):
                        seq += 1
                        sec_chunks.append(Chunk(
                            id=f"{sec.index:03d}-{seq:04d}", section_index=sec.index,
                            text=p, display_text=d, voice=voice, rate=rate,
                            trailing_pause_ms=pause if i == len(parts) - 1 else 0,
                            speaker=para.speaker,
                            src_start=g.segs[0].src_start, src_end=g.segs[-1].src_end,
                        ))
                if sec_chunks and pi < len(sec.paragraphs) - 1:
                    sec_chunks[-1].trailing_pause_ms += self.cfg.audio.paragraph_pause_ms
            chunks.extend(sec_chunks)
        return chunks

    def _groups(self, segs: list[Segment]) -> list[_Group]:
        groups: list[_Group] = []
        cur = _Group()
        for seg in segs:
            if cur.segs:
                combined = len(cur.text) + 1 + len(seg.spoken_text)
                too_long = combined > self.max_chars
                if self.strategy == "sentence":
                    should_close = too_long or len(cur.text) >= self.min_chars
                else:
                    should_close = too_long
                if should_close:
                    groups.append(cur)
                    cur = _Group()
            cur.segs.append(seg)
            if seg.pause_after_ms > 0:
                groups.append(cur)
                cur = _Group()
        if cur.segs:
            groups.append(cur)
        return groups
