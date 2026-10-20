"""정보(버전·라이선스 고지), 스크립트 문법 도움말, 진단 정보 내보내기, 업데이트 확인."""
from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QTextBrowser, QVBoxLayout

from ... import __version__, paths


def _read(name: str) -> str:
    try:
        return paths.data_file(name).read_text(encoding="utf-8")
    except OSError:
        return ""


class TextDialog(QDialog):
    def __init__(self, title: str, tabs: list[tuple[str, str, bool]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 620)
        lay = QVBoxLayout(self)
        tw = QTabWidget()
        for name, text, is_md in tabs:
            b = QTextBrowser()
            b.setOpenExternalLinks(True)
            if is_md:
                b.setMarkdown(text)
            else:
                b.setPlainText(text)
            tw.addTab(b, name)
        lay.addWidget(tw)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def show_about(parent) -> None:
    about = (f"# Lecture TTS {__version__}\n\n강의 스크립트를 영어 내레이션(mp3/wav)과 자막(SRT/VTT)으로 만드는 앱입니다.\n\n"
             "- 기본 엔진: Kokoro-82M (Apache 2.0), 로컬 실행 — 인터넷·사용료 없음\n"
             "- 사용 데이터(텔레메트리)를 수집하지 않습니다.\n\n"
             f"사용자 데이터 폴더: `{paths.user_data_dir()}`")
    TextDialog("정보", [("정보", about, True), ("오픈소스 라이선스", _read("THIRD_PARTY_NOTICES.md"), True)],
               parent).exec()


def show_syntax_help(parent) -> None:
    TextDialog("스크립트 문법", [("문법", _read("syntax_help.md"), True)], parent).exec()


def export_diagnostics(target: Path) -> Path:
    """로그 + 환경 정보 zip. 스크립트 원문과 API 키는 포함하지 않는다."""
    from ...doctor import environment_report

    target = Path(target)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("environment.json", json.dumps(environment_report(), ensure_ascii=False, indent=2))
        for f in paths.logs_dir().glob("*.log*"):
            z.write(f, f"logs/{f.name}")
        settings = paths.user_settings_path()
        if settings.exists():
            z.write(settings, "settings.yaml")
    return target


def _ver(s: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in s.lstrip("vV").split("."))


def check_latest(url: str, timeout: float = 5.0) -> tuple[str, str] | None:
    """(최신 버전, 페이지 URL). 현재 버전보다 새로우면 반환, 아니면 None. 자동 설치는 하지 않는다."""
    req = urllib.request.Request(url, headers={"User-Agent": f"LectureTTS/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    tag = str(data.get("tag_name") or data.get("version") or "")
    page = str(data.get("html_url") or url)
    if tag and _ver(tag) > _ver(__version__):
        return tag, page
    return None
