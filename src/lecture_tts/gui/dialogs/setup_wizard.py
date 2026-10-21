"""초기 설정 마법사: ffmpeg·espeak-ng·Kokoro 모델 점검, 모델 다운로드(이어받기·재시도), 모델 폴더 가져오기."""
from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ...doctor import CHECK_STEPS, check_environment
from ...engines.kokoro_engine import download_model
from ..workers import TaskThread


class SetupWizard(QDialog):
    """auto_close=True(프로그램 시작 시): 점검 진행 상황만 보여 주고, 문제가 없으면 저절로 닫힌다."""

    checked = Signal(list)  # 점검 결과 (list[Check])
    stepChanged = Signal(int, int, str)  # 점검 단계 (i, n, 이름)

    def __init__(self, parent=None, repo_id: str = "hexgrad/Kokoro-82M", auto_close: bool = False):
        super().__init__(parent)
        self.setWindowTitle("프로그램 준비 상태 확인" if auto_close else "초기 설정")
        self.setMinimumWidth(560)
        self.repo_id = repo_id
        self.auto_close = auto_close
        lay = QVBoxLayout(self)
        self.intro = QLabel("강의 음성 생성에 필요한 구성 요소(ffmpeg·espeak-ng·Kokoro 엔진·모델)를 확인하고 있습니다.\n"
                            "처음 실행할 때는 음성 엔진을 불러오느라 30초~1분 정도 걸릴 수 있습니다. 잠시 기다려 주세요.")
        self.intro.setWordWrap(True)
        lay.addWidget(self.intro)
        # 점검 단계 목록: · 대기 / ▶ 진행 중 / ✓ 끝남
        self.step_labels = []
        steps = QGridLayout()
        for i, name in enumerate(CHECK_STEPS):
            mark, text = QLabel("·"), QLabel(name)
            mark.setFixedWidth(18)
            steps.addWidget(mark, i, 0)
            steps.addWidget(text, i, 1)
            self.step_labels.append((mark, text))
        self.steps_box = QWidget()
        self.steps_box.setLayout(steps)
        lay.addWidget(self.steps_box)
        self.grid = QGridLayout()
        lay.addLayout(self.grid)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        lay.addWidget(self.progress)
        lay.addWidget(self.progress_label)
        btns = QHBoxLayout()
        self.btn_download = QPushButton("모델 다운로드")
        self.btn_import = QPushButton("모델 폴더 가져오기…")
        self.btn_import.setToolTip("인터넷이 막힌 환경: 다른 PC의 Hugging Face 캐시 폴더"
                                   "(models--hexgrad--Kokoro-82M)를 선택해 복사합니다.")
        self.btn_recheck = QPushButton("다시 확인")
        self.btn_close = QPushButton("닫기")
        for b in (self.btn_download, self.btn_import, self.btn_recheck):
            btns.addWidget(b)
        btns.addStretch()
        btns.addWidget(self.btn_close)
        lay.addLayout(btns)
        self.btn_download.clicked.connect(self._download)
        self.btn_import.clicked.connect(self._import)
        self.btn_recheck.clicked.connect(self.refresh)
        self.btn_close.clicked.connect(self.accept)
        self.thread: TaskThread | None = None
        self.check_thread: TaskThread | None = None
        self.checks: list = []
        self._t0 = 0.0
        self._step = ""
        self._tick = QTimer(self, interval=1000, timeout=self._show_elapsed)
        self.refresh()

    # ------------------------------------------------------------------
    # 점검 (작업 스레드에서 실행 — 엔진을 불러오는 동안에도 창이 멈추지 않는다)
    # ------------------------------------------------------------------
    def refresh(self) -> None:
        if self.check_thread is not None and self.check_thread.isRunning():
            return
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        for mark, text in self.step_labels:
            mark.setText("·")
            mark.setStyleSheet("color: #8a8f98;")
            text.setStyleSheet("color: #8a8f98;")
        self.steps_box.setVisible(True)
        for b in (self.btn_download, self.btn_import, self.btn_recheck):
            b.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(CHECK_STEPS))
        self.progress.setValue(0)
        self._t0 = time.monotonic()
        self._step = ""
        self._tick.start()
        self.check_thread = TaskThread(lambda cb: check_environment(self.repo_id, progress=cb), self)
        self.check_thread.progressed.connect(self._check_progress)
        self.check_thread.succeeded.connect(self._check_done)
        self.check_thread.failed.connect(self._check_failed)
        self.check_thread.start()

    def _check_progress(self, i: int, n: int, name: str) -> None:
        self.stepChanged.emit(i, n, name)
        self.progress.setValue(i)
        for k, (mark, text) in enumerate(self.step_labels):
            if k < i:
                mark.setText("✓")
                mark.setStyleSheet("color: #16a34a; font-weight: bold;")
                text.setStyleSheet("")
            elif k == i:
                mark.setText("▶")
                mark.setStyleSheet("color: #2563eb; font-weight: bold;")
                text.setStyleSheet("font-weight: bold;")
        self._step = name if i < n else ""
        self._show_elapsed()

    def _show_elapsed(self) -> None:
        if not self._step:
            return
        sec = int(time.monotonic() - self._t0)
        hint = " — 처음 실행할 때는 30초~1분 걸릴 수 있습니다" if "엔진" in self._step else ""
        self.progress_label.setText(f"확인 중: {self._step}…  ({sec}초 경과){hint}")

    def _check_failed(self, error: str) -> None:
        self._tick.stop()
        self._step = ""
        self.auto_close = False
        self.progress.setVisible(False)
        self.progress_label.setText(f"점검 중 오류: {error}")
        self.btn_recheck.setEnabled(True)
        self.btn_import.setEnabled(True)

    def _check_done(self, checks) -> None:
        self._tick.stop()
        self._step = ""
        self.checks = checks
        self.progress.setVisible(False)
        self.btn_recheck.setEnabled(True)
        self.btn_import.setEnabled(True)
        self.checked.emit(checks)
        if self.auto_close and all(c.ok for c in checks if c.required):
            self._check_progress(len(CHECK_STEPS), len(CHECK_STEPS), "")
            self.progress_label.setText("✓ 모든 구성 요소가 준비되었습니다.")
            QTimer.singleShot(700, self.accept)
            return
        self.auto_close = False  # 문제가 있으면 일반 초기 설정 창으로 남는다
        self.steps_box.setVisible(False)
        self.setWindowTitle("초기 설정")
        self.intro.setText("강의 음성 생성에 필요한 구성 요소를 확인했습니다. ✕ 항목을 해결한 뒤 ‘다시 확인’을 누르세요.")
        self.progress_label.setText(f"확인 완료 ({int(time.monotonic() - self._t0)}초)")
        for r, c in enumerate(checks):
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
        model_ok = next((c.ok for c in checks if c.key == "kokoro_model"), False)
        self.btn_download.setEnabled(not model_ok and (self.thread is None or not self.thread.isRunning()))

    def done(self, r: int) -> None:
        if self.thread is not None and self.thread.isRunning():
            return  # 다운로드 중에는 닫지 않는다
        if self.check_thread is not None and self.check_thread.isRunning() and self.parent() is not None:
            # 점검 도중에 닫으면 기다리지 않는다(창이 멈춤). 스레드는 메인 창에 맡겨 끝까지 돌게 한다.
            self.check_thread.setParent(self.parent())
        super().done(r)

    def model_ready(self) -> bool:
        return all(c.ok for c in self.checks if c.key in ("kokoro_pkg", "kokoro_model"))

    def _download(self) -> None:
        self.btn_download.setEnabled(False)
        self.btn_recheck.setEnabled(False)
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
