"""약어·두문자어 읽기 변환."""
from __future__ import annotations

import re

# 문장 끝에 올 수 있는 약어 (문장 끝이면 마침표 유지)
_CAN_END = {"et cetera", "and others", "approximately"}
_ABBREV = [
    (r"\be\.g\.,?", "for example,"),
    (r"\bi\.e\.,?", "that is,"),
    (r"\betc\.", "et cetera"),
    (r"\bvs\.?(?=\s)", "versus"),
    (r"\bapprox\.", "approximately"),
    (r"\bcf\.", "compare"),
    (r"\bet al\.", "and others"),
    (r"\bDr\.(?=\s)", "Doctor"),
    (r"\bMr\.(?=\s)", "Mister"),
    (r"\bMrs\.(?=\s)", "Missus"),
    (r"\bProf\.(?=\s)", "Professor"),
    (r"\bFig\.(?=\s)", "Figure"),
    (r"\bEq\.(?=\s)", "Equation"),
    (r"\bNo\.(?=\s*\d)", "number"),
]

# 철자로 읽지 않고 단어처럼 읽는 두문자어
PRONOUNCEABLE = {
    "NASA", "UNESCO", "NATO", "UNICEF", "LASER", "RADAR", "SCUBA", "AIDS", "COVID", "FIFA",
    "OPEC", "ASEAN", "JPEG", "GIF", "PIN", "RAM", "ROM", "SIM", "OK", "TOEFL", "TOEIC", "IELTS",
    "LAN", "WAN", "SaaS", "ASCII", "CAPTCHA", "GIS", "ESPN",
}
_ROMAN = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ACRONYM = re.compile(r"\b([A-Z]{2,6})(s?)\b")
_CAPS_WORD = re.compile(r"\b[A-Z]{2,}\b")


def expand_abbreviations(text: str) -> str:
    for pat, rep in _ABBREV:
        def sub(m: re.Match, rep: str = rep) -> str:
            # 문장 중간이면 약어의 마침표를 떼고, 문장 끝이면 유지
            after = m.string[m.end():]
            if rep in _CAN_END and (not after.strip() or re.match(r"\s+[A-Z]", after)):
                return rep + "."
            return rep
        text = re.sub(pat, sub, text)
    return text


def spell_acronyms(text: str) -> str:
    """API → A P I. 전부 대문자인 문장(제목 등)이나 로마 숫자, 발음형 두문자어는 제외."""
    caps_words = len(_CAPS_WORD.findall(text))
    words = len(re.findall(r"\b\w+\b", text)) or 1
    if caps_words >= 3 and caps_words / words > 0.5:
        return text

    def sub(m: re.Match) -> str:
        word, plural = m.group(1), m.group(2)
        if word in PRONOUNCEABLE or _ROMAN.match(word):
            return m.group(0)
        spelled = " ".join(word)
        return spelled + ("'s" if plural else "")

    return _ACRONYM.sub(sub, text)
