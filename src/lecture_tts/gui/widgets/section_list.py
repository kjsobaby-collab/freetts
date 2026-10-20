"""섹션 목록 + 상태 아이콘 (● 완료 / ◐ 생성 중 / ○ 미생성·변경됨 / ✕ 오류)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QListWidget, QListWidgetItem, QMenu, QVBoxLayout, QWidget

STATUS = {
    "done": ("●", "#16a34a", "완료"),
    "running": ("◐", "#f59e0b", "생성 중"),
    "changed": ("○", "#3b82f6", "변경됨"),
    "new": ("○", "#9ca3af", "미생성"),
    "error": ("✕", "#ef4444", "오류"),
}


class SectionList(QWidget):
    sectionActivated = Signal(int)       # 클릭 → 편집기 이동
    buildSection = Signal(int)
    playSection = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel("섹션")
        title.setStyleSheet("font-weight: bold; padding: 4px;")
        self.list = QListWidget()
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        self.list.itemClicked.connect(lambda it: self.sectionActivated.emit(it.data(Qt.ItemDataRole.UserRole)))
        legend = QLabel("  ".join(f"<span style='color:{c}'>{s}</span> {t}"
                                  for k, (s, c, t) in STATUS.items() if k != "new"))
        legend.setWordWrap(True)
        legend.setStyleSheet("font-size: 11px; padding: 4px;")
        lay.addWidget(title)
        lay.addWidget(self.list, 1)
        lay.addWidget(legend)
        self._labels: dict[int, str] = {}
        self._status: dict[int, str] = {}

    def set_sections(self, sections: list[tuple[int, str]], status: dict[int, str]) -> None:
        self._labels = dict(sections)
        current = self.current_index()
        self.list.clear()
        for idx, label in sections:
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, idx)
            self.list.addItem(it)
        self.update_status(status)
        if current is not None:
            self.select(current)

    def update_status(self, status: dict[int, str]) -> None:
        self._status.update(status)
        for i in range(self.list.count()):
            it = self.list.item(i)
            idx = it.data(Qt.ItemDataRole.UserRole)
            st = self._status.get(idx, "new")
            sym, color, tip = STATUS[st]
            it.setText(f"{sym}  {self._labels.get(idx, idx)}")
            it.setForeground(QColor(color) if st in ("running", "error") else self.palette().text().color())
            it.setToolTip(tip)

    def set_one(self, idx: int, status: str) -> None:
        self.update_status({idx: status})

    def current_index(self) -> int | None:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def select(self, idx: int) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == idx:
                self.list.setCurrentRow(i)
                return

    def _menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if not it:
            return
        idx = it.data(Qt.ItemDataRole.UserRole)
        m = QMenu(self)
        m.addAction("이 섹션만 생성", lambda: self.buildSection.emit(idx))
        play = m.addAction("이 섹션 재생", lambda: self.playSection.emit(idx))
        play.setEnabled(self._status.get(idx) in ("done", "changed"))
        m.exec(self.list.mapToGlobal(pos))
