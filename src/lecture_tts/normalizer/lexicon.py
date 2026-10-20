"""사용자 발음 사전 (철자 치환 respelling)."""
from __future__ import annotations

import re


class Lexicon:
    def __init__(self, entries: dict[str, str] | None = None):
        self.entries = dict(entries or {})
        keys = sorted(self.entries, key=len, reverse=True)
        self.pattern = (
            re.compile("|".join(rf"(?<![\w]){re.escape(k)}(?![\w])" for k in keys)) if keys else None
        )

    def split(self, text: str) -> list[tuple[str, bool]]:
        """텍스트를 (조각, 보호여부) 목록으로 분할. 사전 치환 결과는 이후 규칙에서 보호된다."""
        if not self.pattern:
            return [(text, False)]
        out: list[tuple[str, bool]] = []
        pos = 0
        for m in self.pattern.finditer(text):
            if m.start() > pos:
                out.append((text[pos:m.start()], False))
            out.append((self.entries[m.group(0)], True))
            pos = m.end()
        if pos < len(text):
            out.append((text[pos:], False))
        return out
