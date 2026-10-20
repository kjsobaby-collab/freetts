"""기호·수식·URL·코드 식별자 읽기 변환."""
from __future__ import annotations

import re

_SYMBOLS = {
    "≤": " less than or equal to ", "≥": " greater than or equal to ", "≈": " approximately ",
    "≠": " not equal to ", "±": " plus or minus ", "×": " times ", "÷": " divided by ",
    "→": " to ", "←": " from ", "⇒": " implies ", "∞": " infinity ", "°": " degrees ",
    "&": " and ", "√": " square root of ", "∑": " sum of ", "π": " pi ", "µ": " micro ",
}
_CIRCLED = {chr(0x2460 + i): str(i + 1) for i in range(20)}  # ①..⑳
_TLDS = r"(?:com|org|net|edu|gov|io|ai|kr|dev|co|uk|me|info)"


def _say_url(url: str) -> str:
    url = re.sub(r"^https?://", "", url).rstrip("/.,")
    url = re.sub(r"^www\.", "w w w dot ", url)
    url = url.replace(".", " dot ").replace("/", " slash ").replace("-", " dash ").replace("_", " underscore ")
    return url


def _split_camel(m: re.Match) -> str:
    word = m.group(1)
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", word).lower()


def normalize_symbols(text: str, *, read_urls: bool = True) -> str:
    for k, v in _CIRCLED.items():
        text = text.replace(k, v)
    if read_urls:
        text = re.sub(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b",
                      lambda m: _say_url(m.group(0).replace("@", " at ")), text)
        text = re.sub(rf"https?://\S+|\b(?:www\.)?[\w-]+(?:\.[\w-]+)*\.{_TLDS}\b(?:/\S*)?",
                      lambda m: _say_url(m.group(0)), text)
    # 거듭제곱
    text = re.sub(r"(\w)\^2\b", r"\1 squared", text)
    text = re.sub(r"(\w)\^3\b", r"\1 cubed", text)
    text = re.sub(r"(\w)\^\(?(\w+)\)?", r"\1 to the power of \2", text)
    # 범위: 5–10, 1-10 → five to ten (날짜처럼 3개 이상 이어진 경우 제외)
    text = re.sub(r"(?<![\d\-–])(\d+(?:\.\d+)?)\s*[–—-]\s*(\d+(?:\.\d+)?)(?![\d\-–])", r"\1 to \2", text)
    # 비교/산술 연산자 (공백으로 둘러싸인 경우만)
    for sym, word in ((" <= ", " less than or equal to "), (" >= ", " greater than or equal to "),
                      (" != ", " not equal to "), (" == ", " equals "), (" = ", " equals "),
                      (" < ", " less than "), (" > ", " greater than "), (" + ", " plus "),
                      (" * ", " times "), (" / ", " divided by ")):
        text = text.replace(sym, word)
    for k, v in _SYMBOLS.items():
        text = text.replace(k, v)
    # 가운뎃점: w·x → w dot x, "a · b"(구분자) → 쉼표
    text = re.sub(r"\s+[·•]\s+", ", ", text)
    text = re.sub(r"(?<=\w)[·•](?=\w)", " dot ", text)
    # 문장 중 대시 → 쉼표
    text = re.sub(r"\s+[–—]\s+|\s*—\s*", ", ", text)
    # 코드 식별자
    text = re.sub(r"\b(\w+)\(\)", r"\1", text)
    text = re.sub(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", lambda m: m.group(1).replace("_", " "), text)
    text = re.sub(r"\b([a-z]{2,}(?:[A-Z][a-z0-9]+)+)\b", _split_camel, text)
    # 단어/단어 → 단어 or 단어
    text = re.sub(r"(?<=[A-Za-z])/(?=[A-Za-z])", " or ", text)
    return text
