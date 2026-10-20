"""TTS 엔진이 잘못 읽기 쉬운 요소를 읽기 좋은 영어로 변환한다.

display_text는 그대로 두고 spoken_text만 바꾼다. 규칙 순서:
    {표기|읽기} 보호 → lexicon(사용자 사전) → symbols → abbreviations → numbers → acronyms → cleanup
(`No. 5` 같은 약어가 숫자 변환 전에 처리되도록 abbreviations를 numbers 앞에 둔다.)
"""
from __future__ import annotations

import re

from ..config import NormalizationConfig
from ..models import LectureDocument
from ..parser import PROTECT_END, PROTECT_START
from .abbreviations import expand_abbreviations, spell_acronyms
from .lexicon import Lexicon
from .numbers import normalize_numbers
from .symbols import normalize_symbols

_PROTECTED = re.compile(f"{PROTECT_START}(.*?){PROTECT_END}", re.S)


class Normalizer:
    def __init__(self, cfg: NormalizationConfig | None = None, lexicon: dict[str, str] | None = None):
        self.cfg = cfg or NormalizationConfig()
        self.lexicon = Lexicon(lexicon)

    def _rules(self, text: str) -> str:
        text = normalize_symbols(text, read_urls=self.cfg.read_urls)
        text = expand_abbreviations(text)
        text = normalize_numbers(text)
        if self.cfg.spell_out_acronyms:
            text = spell_acronyms(text)
        return text

    def normalize(self, text: str) -> str:
        pieces: list[tuple[str, bool]] = []
        pos = 0
        for m in _PROTECTED.finditer(text):
            if m.start() > pos:
                pieces.extend(self.lexicon.split(text[pos:m.start()]))
            pieces.append((m.group(1), True))
            pos = m.end()
        if pos < len(text):
            pieces.extend(self.lexicon.split(text[pos:]))
        out = "".join(p if protected else self._rules(p) for p, protected in pieces)
        return cleanup(out)

    def apply(self, doc: LectureDocument) -> LectureDocument:
        for sec in doc.sections:
            for para in sec.paragraphs:
                for seg in para.segments:
                    seg.spoken_text = self.normalize(seg.spoken_text)
        return doc


def cleanup(text: str) -> str:
    text = text.replace(PROTECT_START, "").replace(PROTECT_END, "")
    text = re.sub(r"[`#_~]+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
