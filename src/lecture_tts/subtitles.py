"""SRT/VTT 자막 생성. 청크(문장) 단위 큐, 한 줄 최대 길이·최대 2줄 규칙 적용."""
from __future__ import annotations

from pathlib import Path

from .assembler import ChunkTiming


def wrap(text: str, max_chars: int) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def make_cues(timings: list[ChunkTiming], max_line_chars: int = 42, offset_ms: int = 0) -> list[tuple[int, int, str]]:
    cues: list[tuple[int, int, str]] = []
    for t in timings:
        lines = wrap(t.text, max_line_chars)
        if not lines:
            continue
        groups = [lines[i:i + 2] for i in range(0, len(lines), 2)]
        total = sum(len(" ".join(g)) for g in groups) or 1
        start = t.start_ms
        span = t.end_ms - t.start_ms
        for i, g in enumerate(groups):
            txt = "\n".join(g)
            end = t.end_ms if i == len(groups) - 1 else start + int(span * len(" ".join(g)) / total)
            cues.append((start + offset_ms, end + offset_ms, txt))
            start = end
    return cues


def _ts(ms: int, sep: str) -> str:
    h, rem = divmod(max(ms, 0), 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def write_srt(cues: list[tuple[int, int, str]], path: Path) -> Path:
    path = Path(path).with_suffix(".srt")
    body = "\n".join(f"{i}\n{_ts(s, ',')} --> {_ts(e, ',')}\n{t}\n" for i, (s, e, t) in enumerate(cues, 1))
    path.write_text(body, encoding="utf-8")
    return path


def write_vtt(cues: list[tuple[int, int, str]], path: Path) -> Path:
    path = Path(path).with_suffix(".vtt")
    body = "WEBVTT\n\n" + "\n".join(f"{_ts(s, '.')} --> {_ts(e, '.')}\n{t}\n" for s, e, t in cues)
    path.write_text(body, encoding="utf-8")
    return path


def write_subtitles(cues, base: Path, formats: list[str]) -> list[Path]:
    out = []
    if "srt" in formats:
        out.append(write_srt(cues, base))
    if "vtt" in formats:
        out.append(write_vtt(cues, base))
    return out
