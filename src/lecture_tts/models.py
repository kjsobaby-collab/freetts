"""파이프라인 전반에서 쓰는 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParseWarning:
    start: int          # 원문 내 문자 오프셋
    end: int
    message: str


@dataclass
class Segment:
    """문장(또는 [pause]로 잘린 문장 조각). 원문 위치를 기억해 GUI 하이라이트에 쓴다."""
    display_text: str          # 자막에 표시될 원문
    spoken_text: str           # 실제로 읽힐 텍스트 (정규화 후)
    src_start: int = 0
    src_end: int = 0
    pause_after_ms: int = 0


@dataclass
class Paragraph:
    segments: list[Segment]
    speaker: str = "default"
    rate: float = 1.0


@dataclass
class Section:
    index: int                 # 1부터 순차 번호 (파일명·상태 관리 키)
    title: str | None
    paragraphs: list[Paragraph]
    number: str | None = None  # 마커에 적힌 번호 (예: Slide 3 → "3")
    src_start: int = 0
    src_end: int = 0

    @property
    def label(self) -> str:
        num = self.number or str(self.index)
        return f"{num} {self.title}" if self.title else num


@dataclass
class LectureDocument:
    title: str | None
    sections: list[Section]
    source_path: str = ""
    warnings: list[ParseWarning] = field(default_factory=list)


@dataclass
class Chunk:
    """TTS 엔진 1회 호출 단위."""
    id: str                    # f"{section:03d}-{seq:04d}"
    section_index: int
    text: str                  # 엔진에 보낼 텍스트 (정규화 후)
    display_text: str
    voice: str
    rate: float
    trailing_pause_ms: int = 0
    cache_key: str = ""
    speaker: str = "default"
    src_start: int = 0
    src_end: int = 0


@dataclass
class AudioClip:
    chunk_id: str
    path: str
    duration_ms: int
