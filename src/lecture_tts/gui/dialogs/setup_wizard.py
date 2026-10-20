"""초기 설정 마법사: ffmpeg·espeak-ng·Kokoro 모델 점검, 모델 다운로드(이어받기·재시도), 모델 폴더 가져오기."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout)

from ...doctor import check_environment
from ...engines.kokoro_engine import download_model
from ..workers import TaskThread


class SetupWizard(QDialog):
    def __init__(self, parent=None, repo_id: str = "hexgrad/Kokoro-82M"):
        super().__init__(parent)
        self.setWindowTitle("초기 설정")
        self.setMinimumWidth(560)
        self.repo_id = repo_id
        lay = QVBoxLayout(self)
        intro = QLabel("강의 음성 생성에 필요한 구성 요소를 확인합니다. ✕ 항목을 해결한 뒤 ‘다시 확인’을 누르세요.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.grid = QGridLayout()
        lay.addLayout(self.grid)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress_label = QLabel("")
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)
        btns = QHBoxLayout()
        self.btn_download = QPushButton("모델 다운로드")
        self.btn_import = QPushButton("모델 폴더 가져오기…")
        self.btn_import.setToolTip("인터넷이 막힌 환경: 다른 PC의 Hugging Face 캐시 폴더"
                                   "(models--hexgrad--Kokoro-82M)를 선택해 복사합니다.")
        btn_recheck = QPushButton("다시 확인")
        self.btn_close = QPushButton("닫기")
        for b in (self.btn_download, self.btn_import, btn_recheck):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)
        self.btn_download.clicked.connect(self._download)
        self.btn_import.clicked.connect(self._import)
        btn_recheck.clicked.connect(self.refresh)
        self.btn_close.clicked.connect(self.accept)
        self.thread: TaskThread | None = None
        self.refresh()

    def refresh(self) -> None:
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.checks = check_environment(self.repo_id)
        for r, c in enumerate(self.checks):
            mark = QLabel("✓" if c.ok else ("✕" if c.required else "△"))
            mark.setStyleSheet(f"color: {'#16a34a' if c.ok else '#ef4444' if c.required else '#f59e0b'};"
                               "font-weight: bold; font-size: 15px;")
            self.grid.addWidget(mark, r, 0)
            self.grid.addWidget(QLabel(c.name), r, 1)
            detail = QLabel(c.detail)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(detail, r, 2)
            if not c.ok and c.help_url:
                b = QPushButton("설치 안내")
                b.clicked.connect(lambda _=False, u=c.help_url: QDesktopServices.openUrl(QUrl(u)))
                self.grid.addWidget(b, r, 3)
        model_ok = next((c.ok for c in self.checks if c.key == "kokoro_model"), False)
        self.btn_download.setEnabled(not model_ok)

    def model_ready(self) -> bool:
        return all(c.ok for c in self.checks if c.key in ("kokoro_pkg", "kokoro_model"))

    def _download(self) -> None:
        self.btn_download.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.thread = TaskThread(lambda cb: download_model(self.repo_id, progress=cb), self)
        self.thread.progressed.connect(self._progress)
        self.thread.succeeded.connect(self._ok)  # 메서드에 연결 (람다는 작업 스레드에서 실행됨)
        self.thread.failed.connect(self._done)
        self.thread.start()

    def _progress(self, i: int, n: int, name: str) -> None:
        self.progress.setRange(0, n)
        self.progress.setValue(i)
        self.progress_label.setText(f"내려받는 중: {name}  ({i}/{n}) — 중단돼도 다시 누르면 이어받습니다.")

    def _ok(self, _result) -> None:
        self._done(None)

    def _done(self, error: str | None) -> None:
        self.btn_close.setEnabled(True)
        self.progress.setVisible(False)
        if error:
            self.progress_label.setText("")
            QMessageBox.warning(self, "다운로드 실패",
                                f"모델을 내려받지 못했습니다.\n{error}\n\n인터넷 연결을 확인하고 다시 시도하세요.")
        else:
            self.progress_label.setText("모델 준비 완료")
        self.refresh()

    def _import(self) -> None:
        src = QFileDialog.getExistingDirectory(self, "모델 폴더 선택 (models--hexgrad--Kokoro-82M)")
        if not src:
            return
        from huggingface_hub import constants
        src_p = Path(src)
        name = "models--" + self.repo_id.replace("/", "--")
        if src_p.name != name and (src_p / name).is_dir():
            src_p = src_p / name
        if src_p.name != name:
            QMessageBox.warning(self, "모델 가져오기", f"'{name}' 폴더를 선택하세요.")
            return
        dst = Path(constants.HF_HUB_CACHE) / name
        try:
            shutil.copytree(src_p, dst, dirs_exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "모델 가져오기", f"복사 실패: {e}")
            return
        self.refresh()
