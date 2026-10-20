"""음성 비교 창: 후보 음성 × 속도 샘플 합성 → 표에서 재생·비교 → 기본 음성으로 지정."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...config import AppConfig
from ...engines import create_engine
from ...engines.kokoro_engine import describe_voice
from ...samples import AUDITION_TEXT

DEFAULT_CANDIDATES = {"af_heart", "af_bella", "am_michael", "am_fenrir", "bf_emma", "bm_george"}
RATES = [0.9, 0.95, 1.0, 1.1]


class AuditionDialog(QDialog):
    requestSpeak = Signal(object, str, str)     # cfg, text, tag
    playFile = Signal(str, str)                 # label, path
    setDefault = Signal(str, float)             # voice, rate

    def __init__(self, cfg: AppConfig, text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("음성 비교")
        self.resize(720, 600)
        self.cfg = cfg
        self.files: dict[str, str] = {}
        lay = QVBoxLayout(self)

        vbox = QGroupBox(f"후보 음성 ({cfg.engine.name})")
        grid = QGridLayout(vbox)
        self.voice_boxes: list[QCheckBox] = []
        voices = create_engine(cfg).list_voices()
        for i, v in enumerate(voices):
            cb = QCheckBox(describe_voice(v) if cfg.engine.name == "kokoro" else v)
            cb.setProperty("voice", v)
            cb.setChecked(v in DEFAULT_CANDIDATES or (len(voices) <= 6))
            grid.addWidget(cb, i // 4, i % 4)
            self.voice_boxes.append(cb)
        lay.addWidget(vbox)

        rbox = QGroupBox("속도")
        rh = QHBoxLayout(rbox)
        self.rate_boxes = []
        for r in RATES:
            cb = QCheckBox(f"{r:.2f}")
            cb.setProperty("rate", r)
            cb.setChecked(r in (0.9, 1.0))
            rh.addWidget(cb)
            self.rate_boxes.append(cb)
        rh.addStretch()
        lay.addWidget(rbox)

        lay.addWidget(QLabel("샘플 문장 (전문 용어·숫자·긴 문장이 섞인 30초 분량 단락 권장)"))
        self.text = QPlainTextEdit(text or AUDITION_TEXT)
        self.text.setMaximumHeight(110)
        lay.addWidget(self.text)

        self.btn_gen = QPushButton("샘플 생성")
        self.btn_gen.clicked.connect(self.generate)
        lay.addWidget(self.btn_gen)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["음성", "속도", "상태", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)
        hint = QLabel("평가 기준: ① 장시간 들어도 피로하지 않은가 ② 전문 용어 발음 ③ 문장 끝 억양 ④ 비원어민이 알아듣기 쉬운 속도")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8f98;")
        lay.addWidget(hint)
        self.rows: dict[str, int] = {}

    def generate(self) -> None:
        voices = [cb.property("voice") for cb in self.voice_boxes if cb.isChecked()]
        rates = [cb.property("rate") for cb in self.rate_boxes if cb.isChecked()]
        text = self.text.toPlainText().strip()
        if not voices or not rates or not text:
            return
        self.table.setRowCount(0)
        self.rows.clear()
        for v in voices:
            for r in rates:
                tag = f"aud:{v}:{r}"
                row = self.table.rowCount()
                self.table.insertRow(row)
                self.table.setItem(row, 0, QTableWidgetItem(v))
                self.table.setItem(row, 1, QTableWidgetItem(f"{r:.2f}"))
                self.table.setItem(row, 2, QTableWidgetItem("대기 중…"))
                self.rows[tag] = row
                c = self.cfg.model_copy(deep=True)
                c.set_voice(v)
                c.engine.rate = r
                self.requestSpeak.emit(c, text, tag)

    def on_ready(self, tag: str, path: str) -> None:
        if tag not in self.rows:
            return
        row = self.rows[tag]
        _, v, r = tag.split(":")
        self.files[tag] = path
        self.table.setItem(row, 2, QTableWidgetItem("완료"))
        cell = QHBoxLayout()
        w = QGroupBox()
        w.setFlat(True)
        w.setStyleSheet("QGroupBox { border: 0; margin: 0; }")
        w.setLayout(cell)
        cell.setContentsMargins(0, 0, 0, 0)
        play = QPushButton("▶ 재생")
        play.clicked.connect(lambda: self.playFile.emit(f"비교: {v} {r}", path))
        use = QPushButton("기본 음성으로 지정")
        use.clicked.connect(lambda: (self.setDefault.emit(v, float(r)), self.accept()))
        cell.addWidget(play)
        cell.addWidget(use)
        self.table.setCellWidget(row, 3, w)
        self.table.resizeColumnToContents(3)

    def on_failed(self, tag: str, msg: str) -> None:
        if tag in self.rows:
            self.table.setItem(self.rows[tag], 2, QTableWidgetItem(f"실패: {msg[:60]}"))
