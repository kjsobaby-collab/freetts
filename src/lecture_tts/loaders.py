"""파일 확장자별 로더: 순수 텍스트(+ 섹션 마커 형태의 구조 힌트)를 반환한다."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path


class Loader(ABC):
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def load(self, path: Path) -> str: ...


def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig",):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    else:
        from charset_normalizer import from_bytes

        best = from_bytes(raw).best()
        if best is None:
            raise ValueError(f"파일 인코딩을 판별할 수 없습니다: {path}")
        text = str(best)
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TextLoader(Loader):
    extensions = (".txt", ".md", ".markdown")

    def load(self, path: Path) -> str:
        return read_text_any(path)


class DocxLoader(Loader):
    """Heading 스타일 문단 → `## 제목` 섹션 마커로 변환."""
    extensions = (".docx",)

    def load(self, path: Path) -> str:
        try:
            import docx  # python-docx
        except ImportError as e:
            raise RuntimeError(".docx 입력에는 python-docx가 필요합니다: pip install python-docx") from e
        d = docx.Document(str(path))
        lines: list[str] = []
        for p in d.paragraphs:
            text = p.text.strip()
            style = (p.style.name or "").lower() if p.style is not None else ""
            if not text:
                continue
            if style == "title":
                lines.append(f"# {text}")
            elif style.startswith("heading"):
                lines.append(f"## {text}")
            else:
                lines.append(text)
            lines.append("")
        return "\n".join(lines)


_SRT_TIME = re.compile(r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}")


class SrtLoader(Loader):
    """각 큐를 문단으로 취급 (원래 타임코드는 v1에서는 사용하지 않음)."""
    extensions = (".srt", ".vtt")

    def load(self, path: Path) -> str:
        text = read_text_any(path)
        paras: list[str] = []
        cur: list[str] = []
        for line in text.split("\n"):
            s = line.strip()
            if s.upper() == "WEBVTT" or _SRT_TIME.match(s) or (s.isdigit() and not cur):
                continue
            if not s:
                if cur:
                    paras.append(" ".join(cur))
                    cur = []
                continue
            cur.append(re.sub(r"<[^>]+>", "", s))
        if cur:
            paras.append(" ".join(cur))
        return "\n\n".join(paras)


LOADERS: list[Loader] = [TextLoader(), DocxLoader(), SrtLoader()]
SUPPORTED_EXTENSIONS = tuple(e for ld in LOADERS for e in ld.extensions)


def load_file(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"입력 파일이 없습니다: {path}")
    ext = path.suffix.lower()
    for ld in LOADERS:
        if ext in ld.extensions:
            return ld.load(path)
    return TextLoader().load(path)
