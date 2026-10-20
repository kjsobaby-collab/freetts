"""숫자 읽기 변환 (num2words)."""
from __future__ import annotations

import re

from num2words import num2words

_SCALES = {"k": "thousand", "m": "million", "b": "billion", "bn": "billion", "t": "trillion",
           "thousand": "thousand", "million": "million", "billion": "billion", "trillion": "trillion"}
_CURRENCY = {"$": ("dollar", "dollars"), "€": ("euro", "euros"), "£": ("pound", "pounds"),
             "₩": ("won", "won"), "¥": ("yen", "yen")}
_YEAR_CUES = {"in", "since", "by", "from", "until", "of", "year", "before", "after", "during", "around", "to"}


def say_number(s: str) -> str:
    s = s.replace(",", "")
    if s.count(".") > 1:
        return " point ".join(say_number(p) for p in s.split("."))
    try:
        if "." in s:
            whole, frac = s.split(".")
            head = num2words(int(whole or "0"))
            return head + " point " + " ".join(num2words(int(d)) for d in frac)
        return num2words(int(s))
    except (ValueError, OverflowError):
        return s


def _currency(m: re.Match) -> str:
    sym, num, scale = m.group(1), m.group(2), (m.group(3) or "")
    one, many = _CURRENCY[sym]
    words = say_number(num)
    scale_word = _SCALES.get(scale.lower(), "")
    unit = one if num.replace(",", "") in ("1", "1.0") and not scale_word else many
    return " ".join(w for w in (words, scale_word, unit) if w)


def _year_or_cardinal(m: re.Match, text: str) -> str:
    n = int(m.group(1))
    plural = m.group(2)
    before = re.findall(r"([A-Za-z]+)\W*$", text[:m.start()])
    after = text[m.end():]
    prev = before[0].lower() if before else ""
    next_word = re.match(r"\s+([a-z]+)", after)
    is_year = 1100 <= n <= 2099 and (prev in _YEAR_CUES or not next_word or plural)
    if not is_year:
        return num2words(n)
    word = num2words(n, to="year")
    if plural:
        word = word[:-1] + "ies" if word.endswith("y") else word + "s"
    return word


def normalize_numbers(text: str) -> str:
    text = re.sub(r"([$€£₩¥])\s?(\d[\d,]*(?:\.\d+)?)\s?(bn|[KMBT]\b|thousand|million|billion|trillion)?",
                  _currency, text, flags=re.I)
    text = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: say_number(m.group(1)) + " percent", text)
    text = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: num2words(int(m.group(1)), to="ordinal"), text, flags=re.I)
    text = re.sub(r"\b(\d{1,2}):(\d{2})\b",
                  lambda m: num2words(int(m.group(1))) + (" o'clock" if m.group(2) == "00"
                                                         else " " + (("oh " if m.group(2)[0] == "0" else "")
                                                                     + num2words(int(m.group(2))))), text)
    text = re.sub(r"(?<![\w.])-(\d[\d,]*(?:\.\d+)?)\b", lambda m: "minus " + say_number(m.group(1)), text)
    text = re.sub(r"\b(\d{4})('?s)?\b(?![.,]\d)", lambda m: _year_or_cardinal(m, text), text)
    text = re.sub(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d+\.\d+\b|\b\d+\b", lambda m: say_number(m.group(0)), text)
    return text
