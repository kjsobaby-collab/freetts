"""환경설정: 사용자 설정(settings.yaml)에 저장 — 쉼 길이, 음량, 자막, 캐시, Azure 키, 업데이트 확인."""
from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout)

from ... import UPDATE_URL, paths
from ...cache import TTSCache
from ...config import AppConfig, read_yaml, save_user_settings


class PreferencesDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("환경설정")
        self.setMinimumWidth(480)
        self.cfg = cfg
        lay = QVBoxLayout(self)

        audio = QGroupBox("오디오")
        f = QFormLayout(audio)
        self.para_pause = QSpinBox()
        self.para_pause.setRange(0, 5000)
        self.para_pause.setSingleStep(100)
        self.para_pause.setSuffix(" ms")
        self.para_pause.setValue(cfg.audio.paragraph_pause_ms)
        self.sec_pad = QSpinBox()
        self.sec_pad.setRange(0, 10000)
        self.sec_pad.setSingleStep(250)
        self.sec_pad.setSuffix(" ms")
        self.sec_pad.setValue(cfg.audio.section_padding_ms)
        self.default_pause = QSpinBox()
        self.default_pause.setRange(100, 10000)
        self.default_pause.setSingleStep(100)
        self.default_pause.setSuffix(" ms")
        self.default_pause.setValue(cfg.parsing.default_pause_ms)
        self.lufs = QDoubleSpinBox()
        self.lufs.setRange(-30, -6)
        self.lufs.setSuffix(" LUFS")
        self.lufs.setValue(cfg.audio.loudness_lufs)
        self.bitrate = QComboBox()
        self.bitrate.addItems(["96k", "128k", "192k", "256k"])
        self.bitrate.setCurrentText(cfg.audio.bitrate)
        f.addRow("문단 사이 쉼", self.para_pause)
        f.addRow("섹션 앞뒤 여백", self.sec_pad)
        f.addRow("[pause] 기본 길이", self.default_pause)
        f.addRow("음량 목표", self.lufs)
        f.addRow("mp3 비트레이트", self.bitrate)
        lay.addWidget(audio)

        text = QGroupBox("텍스트·자막")
        f2 = QFormLayout(text)
        self.acronyms = QCheckBox("대문자 약어를 한 글자씩 읽기 (API → A P I)")
        self.acronyms.setChecked(cfg.normalization.spell_out_acronyms)
        self.section_titles = QCheckBox("섹션 제목도 읽기")
        self.section_titles.setChecked(cfg.parsing.read_section_titles)
        self.srt = QCheckBox("SRT")
        self.srt.setChecked("srt" in cfg.subtitles.formats)
        self.vtt = QCheckBox("VTT")
        self.vtt.setChecked("vtt" in cfg.subtitles.formats)
        sub_row = QHBoxLayout()
        sub_row.addWidget(self.srt)
        sub_row.addWidget(self.vtt)
        sub_row.addStretch()
        self.line_chars = QSpinBox()
        self.line_chars.setRange(20, 80)
        self.line_chars.setValue(cfg.subtitles.max_line_chars)
        f2.addRow(self.acronyms)
        f2.addRow(self.section_titles)
        f2.addRow("자막 형식", sub_row)
        f2.addRow("자막 한 줄 최대 글자", self.line_chars)
        lay.addWidget(text)

        cache = QGroupBox("캐시")
        ch = QHBoxLayout(cache)
        self.cache_label = QLabel()
        clear = QPushButton("캐시 비우기")
        clear.clicked.connect(self._clear_cache)
        ch.addWidget(self.cache_label, 1)
        ch.addWidget(clear)
        lay.addWidget(cache)
        self._update_cache_label()

        az = QGroupBox("Azure Speech (선택, 각자 키 입력 · Windows 자격 증명 관리자에 저장)")
        f3 = QFormLayout(az)
        self.az_key = QLineEdit()
        self.az_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.az_key.setPlaceholderText("변경할 때만 입력")
        self.az_region = QLineEdit()
        self.az_region.setPlaceholderText("예: koreacentral")
        f3.addRow("키", self.az_key)
        f3.addRow("지역", self.az_region)
        lay.addWidget(az)

        upd = QGroupBox("업데이트")
        f4 = QFormLayout(upd)
        s = QSettings()
        self.check_updates = QCheckBox("시작할 때 새 버전 확인 (알림만 표시)")
        self.check_updates.setChecked(s.value("update/check", True, type=bool))
        self.update_url = QLineEdit(s.value("update/url", UPDATE_URL, type=str))
        self.update_url.setPlaceholderText("https://api.github.com/repos/<owner>/<repo>/releases/latest")
        f4.addRow(self.check_updates)
        f4.addRow("확인 주소", self.update_url)
        lay.addWidget(upd)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _update_cache_label(self) -> None:
        c = TTSCache(self.cfg.cache_path())
        self.cache_label.setText(f"{self.cfg.cache_path()}\n{c.size_bytes() / 1e6:.1f} MB")

    def _clear_cache(self) -> None:
        if QMessageBox.question(self, "캐시 비우기", "합성 캐시를 모두 삭제할까요? 다음 생성 때 모든 문장을 다시 합성합니다.") \
                == QMessageBox.StandardButton.Yes:
            TTSCache(self.cfg.cache_path()).clear()
            self._update_cache_label()

    def save(self) -> None:
        data = read_yaml(paths.user_settings_path())
        data.setdefault("audio", {}).update({
            "paragraph_pause_ms": self.para_pause.value(), "section_padding_ms": self.sec_pad.value(),
            "loudness_lufs": self.lufs.value(), "bitrate": self.bitrate.currentText()})
        data.setdefault("parsing", {}).update({"default_pause_ms": self.default_pause.value(),
                                               "read_section_titles": self.section_titles.isChecked()})
        data.setdefault("normalization", {})["spell_out_acronyms"] = self.acronyms.isChecked()
        data.setdefault("subtitles", {}).update({
            "formats": [f for f, cb in (("srt", self.srt), ("vtt", self.vtt)) if cb.isChecked()],
            "max_line_chars": self.line_chars.value()})
        save_user_settings(data)
        if self.az_key.text().strip():
            try:
                from ...engines.azure_engine import save_credentials
                save_credentials(self.az_key.text().strip(), self.az_region.text().strip())
            except Exception as e:
                QMessageBox.warning(self, "Azure 키 저장 실패", f"keyring 저장 실패: {e}")
        s = QSettings()
        s.setValue("update/check", self.check_updates.isChecked())
        s.setValue("update/url", self.update_url.text().strip())
        self.accept()
