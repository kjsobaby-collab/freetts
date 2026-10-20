"""엔진·음성·억양·속도·출력 포맷·출력 폴더 설정 패널. 변경 즉시 changed 시그널."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton, QSlider, QToolButton, QVBoxLayout, QWidget)

from ...config import AppConfig
from ...engines import ENGINE_LABELS, create_engine
from ...engines.kokoro_engine import describe_voice


class SettingsPanel(QWidget):
    changed = Signal()
    listenSelection = Signal()
    openAudition = Signal()
    openLexicon = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        lay = QVBoxLayout(self)
        title = QLabel("설정")
        title.setStyleSheet("font-weight: bold;")
        lay.addWidget(title)
        form = QFormLayout()
        lay.addLayout(form)

        self.engine = QComboBox()
        for k, label in ENGINE_LABELS.items():
            self.engine.addItem(label, k)
        form.addRow("엔진", self.engine)

        self.accent_us = QRadioButton("미국")
        self.accent_uk = QRadioButton("영국")
        self.accent_grp = QButtonGroup(self)
        self.accent_grp.addButton(self.accent_us)
        self.accent_grp.addButton(self.accent_uk)
        self.accent_row = QWidget()
        h = QHBoxLayout(self.accent_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.accent_us)
        h.addWidget(self.accent_uk)
        h.addStretch()
        form.addRow("억양", self.accent_row)

        self.voice = QComboBox()
        self.voice.setEditable(False)
        form.addRow("음성", self.voice)

        rate_row = QWidget()
        rh = QHBoxLayout(rate_row)
        rh.setContentsMargins(0, 0, 0, 0)
        self.rate = QSlider(Qt.Orientation.Horizontal)
        self.rate.setRange(50, 150)
        self.rate.setSingleStep(5)
        self.rate.setPageStep(5)
        self.rate_label = QLabel("1.00")
        self.rate_label.setMinimumWidth(34)
        rh.addWidget(self.rate, 1)
        rh.addWidget(self.rate_label)
        form.addRow("속도", rate_row)

        fmt_row = QWidget()
        fh = QHBoxLayout(fmt_row)
        fh.setContentsMargins(0, 0, 0, 0)
        self.fmt_mp3 = QRadioButton("mp3")
        self.fmt_wav = QRadioButton("wav")
        self.fmt_grp = QButtonGroup(self)
        self.fmt_grp.addButton(self.fmt_mp3)
        self.fmt_grp.addButton(self.fmt_wav)
        fh.addWidget(self.fmt_mp3)
        fh.addWidget(self.fmt_wav)
        fh.addStretch()
        form.addRow("포맷", fmt_row)

        out_row = QWidget()
        oh = QHBoxLayout(out_row)
        oh.setContentsMargins(0, 0, 0, 0)
        self.output = QLineEdit()
        self.output.setPlaceholderText("스크립트 폴더/output")
        browse = QToolButton()
        browse.setText("…")
        browse.clicked.connect(self._browse)
        oh.addWidget(self.output, 1)
        oh.addWidget(browse)
        form.addRow("출력", out_row)

        lay.addSpacing(8)
        self.btn_listen = QPushButton("▶ 선택 영역 듣기")
        self.btn_listen.setToolTip("편집기에서 선택한 문장만 즉시 합성해 재생합니다 (파일 저장 안 함).")
        btn_aud = QPushButton("음성 비교…")
        btn_lex = QPushButton("발음 사전…")
        for b in (self.btn_listen, btn_aud, btn_lex):
            lay.addWidget(b)
        self.engine_status = QLabel("")
        self.engine_status.setWordWrap(True)
        self.engine_status.setStyleSheet("color: #8a8f98; font-size: 11px;")
        lay.addWidget(self.engine_status)
        lay.addStretch()

        self.btn_listen.clicked.connect(self.listenSelection)
        btn_aud.clicked.connect(self.openAudition)
        btn_lex.clicked.connect(self.openLexicon)
        self.engine.currentIndexChanged.connect(self._engine_changed)
        self.accent_grp.buttonClicked.connect(lambda _: self._fill_voices(self.voice.currentData()))
        self.voice.currentIndexChanged.connect(self._emit)
        self.rate.valueChanged.connect(self._rate_changed)
        self.fmt_grp.buttonClicked.connect(lambda _: self._emit())
        self.output.editingFinished.connect(self._emit)
        self._cfg: AppConfig | None = None

    # ------------------------------------------------------------------
    def load(self, cfg: AppConfig) -> None:
        self._loading = True
        self._cfg = cfg
        self.engine.setCurrentIndex(max(0, self.engine.findData(cfg.engine.name)))
        voice = cfg.voice
        (self.accent_uk if voice.startswith("b") else self.accent_us).setChecked(True)
        self._fill_voices(voice)
        self.rate.setValue(int(round(cfg.engine.rate * 100)))
        self.rate_label.setText(f"{cfg.engine.rate:.2f}")
        (self.fmt_wav if cfg.audio.format == "wav" else self.fmt_mp3).setChecked(True)
        self.output.setText(cfg.runtime.output_dir or "")
        self._loading = False

    def _fill_voices(self, keep: str | None) -> None:
        name = self.engine.currentData()
        was_loading = self._loading
        self._loading = True
        self.voice.clear()
        cfg = self._cfg
        voices = create_engine(cfg, name).list_voices() if cfg else []
        is_kokoro = name == "kokoro"
        self.accent_row.setVisible(is_kokoro)
        if is_kokoro:
            prefix = "b" if self.accent_uk.isChecked() else "a"
            voices = [v for v in voices if v.startswith(prefix)]
        for v in voices:
            self.voice.addItem(describe_voice(v) if is_kokoro else v, v)
        i = self.voice.findData(keep)
        self.voice.setCurrentIndex(i if i >= 0 else 0)
        self._loading = was_loading
        self._emit()

    def _engine_changed(self) -> None:
        if self._loading or not self._cfg:
            return
        name = self.engine.currentData()
        keep = self._cfg.engine_cfg(name).voice  # type: ignore[attr-defined]
        if name == "kokoro":
            (self.accent_uk if keep.startswith("b") else self.accent_us).setChecked(True)
        self._fill_voices(keep)

    def _rate_changed(self, v: int) -> None:
        v = int(round(v / 5) * 5)
        self.rate_label.setText(f"{v / 100:.2f}")
        self._emit()

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "출력 폴더 선택", self.output.text())
        if d:
            self.output.setText(d)
            self._emit()

    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def overrides(self) -> dict:
        """현재 패널 값 → AppConfig에 deep-merge할 dict."""
        name = self.engine.currentData()
        voice = self.voice.currentData()
        over: dict = {
            "engine": {"name": name, "rate": round(int(round(self.rate.value() / 5) * 5) / 100, 2)},
            "audio": {"format": "wav" if self.fmt_wav.isChecked() else "mp3"},
            "runtime": {"output_dir": self.output.text().strip() or None},
        }
        if voice:
            over["engines"] = {name: {"voice": voice}}
            if name == "kokoro":
                over["engines"]["kokoro"]["lang_code"] = voice[0]
        return over
