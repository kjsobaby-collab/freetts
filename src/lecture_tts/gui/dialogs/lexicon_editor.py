"""발음 사전 편집기: lexicon.yaml을 표(표기/읽기)로 편집, 행별 즉시 듣기."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...config import load_lexicon, save_lexicon


class LexiconEditor(QDialog):
    requestSpeak = Signal(str, str)     # 읽기 텍스트, tag
    saved = Signal()

    def __init__(self, path: Path, add_word: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("발음 사전")
        self.resize(560, 520)
        self.path = Path(path)
        lay = QVBoxLayout(self)
        info = QLabel(f"표기된 단어를 ‘읽기’대로 발음합니다 (대소문자 구분, 단어 단위).\n파일: {self.path}")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["표기", "읽기", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("행 추가")
        rem = QPushButton("선택 행 삭제")
        save = QPushButton("저장")
        close = QPushButton("닫기")
        for b in (add, rem):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(save)
        row.addWidget(close)
        lay.addLayout(row)
        add.clicked.connect(lambda: self._add_row("", ""))
        rem.clicked.connect(self._remove)
        save.clicked.connect(self.save)
        close.clicked.connect(self.reject)
        for k, v in sorted(load_lexicon(self.path).items(), key=lambda kv: kv[0].lower()):
            self._add_row(k, v)
        if add_word:
            self._add_row(add_word, "")
            self.table.setCurrentCell(self.table.rowCount() - 1, 1)
            self.table.editItem(self.table.item(self.table.rowCount() - 1, 1))

    def _add_row(self, key: str, val: str) -> None:
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(key))
        self.table.setItem(r, 1, QTableWidgetItem(val))
        b = QPushButton("▶ 듣기")
        b.clicked.connect(lambda: self._listen(b))
        self.table.setCellWidget(r, 2, b)

    def _listen(self, button: QPushButton) -> None:
        for r in range(self.table.rowCount()):
            if self.table.cellWidget(r, 2) is button:
                item = self.table.item(r, 1)
                text = (item.text() if item else "").strip() or (self.table.item(r, 0).text())
                if text:
                    self.requestSpeak.emit(f"{{{text}|{text}}}", f"lex:{r}")

    def _remove(self) -> None:
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)

    def entries(self) -> dict[str, str]:
        out = {}
        for r in range(self.table.rowCount()):
            k = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            v = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            if k and v:
                out[k] = v
        return out

    def save(self) -> None:
        try:
            save_lexicon(self.path, self.entries())
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return
        self.saved.emit()
        self.accept()
