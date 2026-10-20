"""스크립트 편집기: 구문 강조(Parser 정규식 재사용) + 잘못된 지시어 물결 밑줄 + 재생 문장 하이라이트."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat, QTextCursor,
                           QTextFormat)
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QTextEdit, QToolTip

from ...models import ParseWarning
from ...parser import EMPHASIS_RE, OVERRIDE_RE, PAUSE_RE, RATE_RE, SPEAKER_RE


def _fmt(color: str, bold=False, italic=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.Bold)
    if italic:
        f.setFontItalic(True)
    return f


class ScriptHighlighter(QSyntaxHighlighter):
    """섹션 헤더·지시어·발음 지정·강조·주석을 색으로 구분 (밝은/어두운 테마 모두 읽히는 중간 톤)."""

    def __init__(self, doc, section_patterns: list[str], title_pattern: str):
        super().__init__(doc)
        self.f_section = _fmt("#3b82f6", bold=True)
        self.f_title = _fmt("#8b5cf6", bold=True)
        self.f_directive = _fmt("#e67e22", bold=True)
        self.f_override = _fmt("#16a34a")
        self.f_emph = _fmt("#c026d3", italic=True)
        self.f_comment = _fmt("#8a8f98", italic=True)
        self.set_patterns(section_patterns, title_pattern)

    def set_patterns(self, section_patterns: list[str], title_pattern: str) -> None:
        self.section_res = [re.compile(p, re.I) for p in section_patterns]
        self.title_re = re.compile(title_pattern)
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        stripped = text.strip()
        if any(rx.match(stripped) for rx in self.section_res):
            self.setFormat(0, len(text), self.f_section)
        elif self.title_re.match(stripped):
            self.setFormat(0, len(text), self.f_title)
        for rx, f in ((PAUSE_RE, self.f_directive), (RATE_RE, self.f_directive),
                      (SPEAKER_RE, self.f_directive), (OVERRIDE_RE, self.f_override), (EMPHASIS_RE, self.f_emph)):
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), f)
        # 여러 줄 주석 (<!-- ... -->)
        self.setCurrentBlockState(0)
        start = 0 if self.previousBlockState() == 1 else text.find("<!--")
        while start >= 0:
            end = text.find("-->", start)
            if end < 0:
                self.setCurrentBlockState(1)
                self.setFormat(start, len(text) - start, self.f_comment)
                break
            self.setFormat(start, end + 3 - start, self.f_comment)
            start = text.find("<!--", end + 3)


class ScriptEditor(QPlainTextEdit):
    listenRequested = Signal(str)          # 선택 영역 듣기
    addToLexicon = Signal(str)             # 발음 사전에 추가
    playFromOffset = Signal(int)           # 더블클릭 → 해당 문장부터 재생

    def __init__(self, parent=None):
        super().__init__(parent)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.highlighter: ScriptHighlighter | None = None
        self._warnings: list[ParseWarning] = []
        self._warn_sel: list[QTextEdit.ExtraSelection] = []
        self._play_sel: list[QTextEdit.ExtraSelection] = []
        self._sec_sel: list[QTextEdit.ExtraSelection] = []
        self.setMouseTracking(True)

    def install_highlighter(self, section_patterns: list[str], title_pattern: str) -> None:
        if self.highlighter is None:
            self.highlighter = ScriptHighlighter(self.document(), section_patterns, title_pattern)
        else:
            self.highlighter.set_patterns(section_patterns, title_pattern)

    # --- 표시 -----------------------------------------------------------------
    def _apply(self) -> None:
        self.setExtraSelections(self._sec_sel + self._warn_sel + self._play_sel)

    def _selection(self, start: int, end: int, fmt: QTextCharFormat) -> QTextEdit.ExtraSelection:
        sel = QTextEdit.ExtraSelection()
        cur = QTextCursor(self.document())
        n = self.document().characterCount() - 1
        cur.setPosition(max(0, min(start, n)))
        cur.setPosition(max(0, min(end, n)), QTextCursor.MoveMode.KeepAnchor)
        sel.cursor = cur
        sel.format = fmt
        return sel

    def set_warnings(self, warnings: list[ParseWarning]) -> None:
        self._warnings = warnings
        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        fmt.setUnderlineColor(QColor("#ef4444"))
        self._warn_sel = [self._selection(w.start, w.end, fmt) for w in warnings]
        self._apply()

    def highlight_playing(self, start: int | None, end: int | None, scroll: bool = True) -> None:
        if start is None:
            self._play_sel = []
        else:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(250, 204, 21, 110))
            self._play_sel = [self._selection(start, end, fmt)]
            if scroll and not self.hasFocus():  # 사용자가 편집 중이면 커서를 빼앗지 않음
                cur = QTextCursor(self.document())
                cur.setPosition(min(start, self.document().characterCount() - 1))
                self.setTextCursor(cur)
                self.ensureCursorVisible()
        self._apply()

    def highlight_section(self, start: int | None, end: int | None) -> None:
        if start is None:
            self._sec_sel = []
        else:
            fmt = QTextCharFormat()
            fmt.setBackground(QColor(59, 130, 246, 28))
            fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
            self._sec_sel = [self._selection(start, end, fmt)]
        self._apply()

    def goto_offset(self, offset: int) -> None:
        cur = QTextCursor(self.document())
        cur.setPosition(min(offset, self.document().characterCount() - 1))
        self.setTextCursor(cur)
        self.centerCursor()
        self.setFocus()

    # --- 상호작용 ---------------------------------------------------------------
    def event(self, e):
        if e.type() == e.Type.ToolTip:
            pos = self.cursorForPosition(e.pos()).position()
            msgs = [w.message for w in self._warnings if w.start <= pos <= w.end]
            if msgs:
                QToolTip.showText(e.globalPos(), "\n".join(msgs), self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    def mouseDoubleClickEvent(self, e):
        super().mouseDoubleClickEvent(e)
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.playFromOffset.emit(self.cursorForPosition(e.pos()).position())

    def contextMenuEvent(self, e):
        menu: QMenu = self.createStandardContextMenu()
        sel = self.textCursor().selectedText().replace(" ", "\n").strip()
        menu.addSeparator()
        a = menu.addAction("▶ 선택 영역 듣기")
        a.setEnabled(bool(sel))
        a.triggered.connect(lambda: self.listenRequested.emit(sel))
        word = sel if sel and len(sel.split()) <= 3 else ""
        b = menu.addAction(f"발음 사전에 추가: {word}" if word else "발음 사전에 추가")
        b.setEnabled(bool(word))
        b.triggered.connect(lambda: self.addToLexicon.emit(word))
        c = menu.addAction("이 문장부터 재생 (Ctrl+더블클릭)")
        pos = self.cursorForPosition(e.pos()).position()
        c.triggered.connect(lambda: self.playFromOffset.emit(pos))
        menu.exec(e.globalPos())

    def selected_text(self) -> str:
        return self.textCursor().selectedText().replace(" ", "\n").strip()
