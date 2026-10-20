"""스크립트 텍스트 → LectureDocument.

줄 단위 상태 기계: 주석 제거 → 섹션 헤더 감지 → 빈 줄로 문단 분리 → 인라인 지시어 토큰화 → 문장 분리.
모든 Segment는 원문 내 위치(src_start/src_end)를 가진다 (GUI 하이라이트용).
주석은 같은 길이의 공백으로 바꿔 오프셋을 보존한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import ParsingConfig
from .models import LectureDocument, Paragraph, ParseWarning, Section, Segment

# 지시어 정규식 — GUI 구문 강조도 이 정의를 재사용한다.
PAUSE_RE = re.compile(r"\[pause(?:\s+(\d+(?:\.\d+)?)\s*(ms|s))?\]", re.I)  # [pause] = 기본 길이
RATE_RE = re.compile(r"\[rate\s+(\d+(?:\.\d+)?)\]", re.I)
SPEAKER_RE = re.compile(r"\[speaker\s*:\s*([\w\- ]+?)\s*\]", re.I)
OVERRIDE_RE = re.compile(r"\{([^{}|\n]+)\|([^{}\n]+)\}")
EMPHASIS_RE = re.compile(r"(?<![\w*])\*{1,2}([^*\n]+?)\*{1,2}(?![\w*])")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DIRECTIVE_LIKE_RE = re.compile(r"\[(pause|rate|speaker)\b[^\]\n]*\]?", re.I)
BRACE_RE = re.compile(r"\{[^{}\n]*\}?")
TOKEN_RE = re.compile("|".join(f"(?:{r.pattern})" for r in (PAUSE_RE, RATE_RE, SPEAKER_RE)), re.I)
BULLET_RE = re.compile(r"^(\s*)([-*+]\s+|#{3,6}\s+|>\s?)")

# 정규화 단계에서 보호할 구간 표시 (발음 지정 {표기|읽기}의 읽기 부분)
PROTECT_START = ""
PROTECT_END = ""

ABBREVIATIONS = {
    "e.g", "i.e", "etc", "vs", "mr", "mrs", "ms", "dr", "prof", "fig", "eq", "no",
    "st", "approx", "cf", "al", "jr", "sr", "inc", "ltd", "co", "dept", "est", "vol",
}
_SENT_END_RE = re.compile(r"[.!?…]+[\"'”’)\]]*(?=\s)")


@dataclass
class _ParaState:
    speaker: str = "default"
    rate: float = 1.0


def _blank_comments(text: str) -> str:
    return COMMENT_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def strip_markup(text: str, *, spoken: bool) -> str:
    """{표기|읽기}, *강조* 를 표시용/읽기용 텍스트로 변환."""
    if spoken:
        text = OVERRIDE_RE.sub(lambda m: PROTECT_START + m.group(2).strip() + PROTECT_END, text)
    else:
        text = OVERRIDE_RE.sub(lambda m: m.group(1).strip(), text)
    text = EMPHASIS_RE.sub(lambda m: m.group(1), text)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str) -> list[tuple[int, int]]:
    """문장 (start, end) 오프셋 목록. 약어·이니셜·소문자 시작 문장은 끊지 않는다."""
    masked = OVERRIDE_RE.sub(lambda m: "X" * len(m.group(0)), text)
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _SENT_END_RE.finditer(masked):
        end = m.end()
        before = masked[start:m.start()]
        word = re.findall(r"[\w.]+$", before)
        last = word[0].lower().rstrip(".") if word else ""
        if masked[m.start()] == "." and (last in ABBREVIATIONS or re.fullmatch(r"[a-z]", last)):
            continue
        nxt = re.match(r"\s+(\S)", masked[end:])
        if nxt and nxt.group(1).islower():
            continue
        spans.append((start, end))
        start = end
    spans.append((start, len(text)))
    out = []
    for s, e in spans:
        seg = text[s:e]
        ls = len(seg) - len(seg.lstrip())
        rs = len(seg.rstrip())
        if seg.strip():
            out.append((s + ls, s + rs))
    return out


class Parser:
    def __init__(self, cfg: ParsingConfig | None = None):
        self.cfg = cfg or ParsingConfig()
        self.section_res = [re.compile(p, re.I) for p in self.cfg.section_patterns]
        self.title_re = re.compile(self.cfg.title_pattern)

    # ------------------------------------------------------------------
    def match_section(self, line: str) -> tuple[str | None, str | None] | None:
        s = line.strip()
        for rx in self.section_res:
            m = rx.match(s)
            if m:
                groups = [g for g in m.groups()]
                if len(groups) >= 2:
                    return groups[0], (groups[1] or "").strip() or None
                return None, (groups[0] or "").strip() or None
        return None

    def parse(self, raw: str, source_path: str = "") -> LectureDocument:
        text = _blank_comments(raw.replace("\r\n", "\n"))
        warnings: list[ParseWarning] = []
        title: str | None = None
        preamble = Section(index=0, title=None, paragraphs=[], src_start=0)
        sections: list[Section] = []
        current = preamble
        state = _ParaState()
        buf: list[tuple[int, int]] = []

        def flush() -> None:
            if buf:
                self._paragraph(text, buf[0][0], buf[-1][1], current, state, warnings)
                buf.clear()

        pos = 0
        for line in text.split("\n"):
            start, end = pos, pos + len(line)
            pos = end + 1
            stripped = line.strip()
            if not stripped:
                flush()
                continue
            sec = self.match_section(line)
            if sec is None and title is None and not sections and (tm := self.title_re.match(stripped)):
                flush()
                title = tm.group(1).strip()
                if self.cfg.read_title:
                    self._paragraph(text, start, end, current, state, warnings, override=title)
                continue
            if sec is not None:
                flush()
                current.src_end = start
                number, sec_title = sec
                current = Section(index=len(sections) + 1, title=sec_title, paragraphs=[],
                                  number=number, src_start=start)
                sections.append(current)
                if self.cfg.read_section_titles and sec_title:
                    self._paragraph(text, start, end, current, state, warnings, override=sec_title)
                continue
            bm = BULLET_RE.match(line)
            if bm:  # 목록 기호·하위 제목 기호는 위치만 건너뛴다
                flush()
                start += bm.end()
            buf.append((start, end))
        flush()
        current.src_end = len(text)

        if not sections:
            preamble.index = 1
            sections = [preamble]
        elif preamble.paragraphs and self.cfg.read_preamble:
            preamble.title = preamble.title or "Intro"
            sections.insert(0, preamble)
            for i, s in enumerate(sections, 1):
                s.index = i
        if title is None and preamble.paragraphs and not self.cfg.read_preamble and len(sections) > 0 \
                and sections[0] is not preamble:
            first = preamble.paragraphs[0].segments
            title = first[0].display_text if first else None
        return LectureDocument(title=title, sections=sections, source_path=source_path, warnings=warnings)

    # ------------------------------------------------------------------
    def _paragraph(self, text: str, start: int, end: int, section: Section, state: _ParaState,
                   warnings: list[ParseWarning], override: str | None = None) -> None:
        if override is not None:
            seg = Segment(override, override, start, end)
            section.paragraphs.append(Paragraph([seg], state.speaker, state.rate))
            return
        chunk = text[start:end]
        self._validate(chunk, start, warnings)
        para = Paragraph([], state.speaker, state.rate)

        def close_para() -> None:
            nonlocal para
            if para.segments:
                section.paragraphs.append(para)
            para = Paragraph([], state.speaker, state.rate)

        cursor = 0
        for m in TOKEN_RE.finditer(chunk):
            self._add_text(chunk[cursor:m.start()], start + cursor, para)
            cursor = m.end()
            tok = m.group(0)
            if pm := PAUSE_RE.fullmatch(tok):
                if pm.group(1) is None:
                    ms = self.cfg.default_pause_ms
                else:
                    val = float(pm.group(1))
                    ms = int(val * 1000) if pm.group(2).lower() == "s" else int(val)
                if para.segments:
                    para.segments[-1].pause_after_ms += ms
                else:
                    para.segments.append(Segment("", "", start + m.start(), start + m.end(), ms))
            elif rm := RATE_RE.fullmatch(tok):
                close_para()
                state.rate = float(rm.group(1))
                para.rate = state.rate
            elif sm := SPEAKER_RE.fullmatch(tok):
                close_para()
                state.speaker = sm.group(1).strip()
                para.speaker = state.speaker
        self._add_text(chunk[cursor:], start + cursor, para)
        close_para()

    def _add_text(self, piece: str, offset: int, para: Paragraph) -> None:
        if not piece.strip():
            return
        for s, e in split_sentences(piece):
            raw = piece[s:e]
            if self.cfg.on_invalid_directive != "keep_text":
                raw = DIRECTIVE_LIKE_RE.sub(" ", raw)
            display = strip_markup(raw, spoken=False)
            spoken = strip_markup(raw, spoken=True)
            if display or spoken:
                para.segments.append(Segment(display, spoken, offset + s, offset + e))

    def _validate(self, chunk: str, offset: int, warnings: list[ParseWarning]) -> None:
        for m in DIRECTIVE_LIKE_RE.finditer(chunk):
            if not TOKEN_RE.fullmatch(m.group(0)):
                msg = f"잘못된 지시어: {m.group(0)!r} (예: [pause 1s], [rate 0.9], [speaker: student])"
                if self.cfg.on_invalid_directive == "error":
                    raise ValueError(msg)
                warnings.append(ParseWarning(offset + m.start(), offset + m.end(), msg))
        for m in BRACE_RE.finditer(chunk):
            if not OVERRIDE_RE.fullmatch(m.group(0)):
                warnings.append(ParseWarning(offset + m.start(), offset + m.end(),
                                             f"발음 지정 형식 오류: {m.group(0)!r} (예: {{SQL|sequel}})"))
