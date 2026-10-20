"""메인 창: 툴바 / 섹션 목록 · 편집기 탭 · 설정 패널 / 플레이어 · 진행률 · 로그.

화면 상태와 사용자 입력만 다루고, 파싱·합성·병합은 core(pipeline)를 호출한다.
무거운 작업은 EngineHost(작업 스레드)에서 실행되고 시그널로 결과가 돌아온다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from .. import UPDATE_URL, __version__, paths
from ..cache import TTSCache
from ..config import AppConfig, load_config
from ..engines import TTSEngine, create_engine
from ..loaders import SUPPORTED_EXTENSIONS, load_file
from ..models import LectureDocument
from ..pipeline import diff_sections, normalized_script, output_dir_for, parse_text, plan_chunks, read_manifest
from .dialogs.about import check_latest, export_diagnostics, show_about, show_syntax_help
from .project import PROJECT_EXT, Project
from .widgets.player_bar import PlayerBar
from .widgets.script_editor import ScriptEditor
from .widgets.section_list import SectionList
from .widgets.settings_panel import SettingsPanel
from .workers import EngineHost, TaskThread

log = logging.getLogger("lecture_tts")
EDITABLE = (".md", ".txt", ".markdown")
SCRIPT_FILTER = "스크립트 (" + " ".join(f"*{e}" for e in SUPPORTED_EXTENSIONS) + ");;모든 파일 (*)"


class QtLogBridge(logging.Handler):
    """로그 → UI 로그 패널 (스레드 안전: 시그널로 전달)."""

    def __init__(self, emit_fn):
        super().__init__(logging.INFO)
        self.emit_fn = emit_fn
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            self.emit_fn(self.format(record))
        except RuntimeError:
            pass


class MainWindow(QMainWindow):
    requestBuild = Signal(object, str, object, bool)
    requestSpeak = Signal(object, str, str)
    logLine = Signal(str)

    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.project = Project()
        self.overrides: dict = json.loads(self.settings.value("last_overrides", "{}", type=str) or "{}")
        self.cfg: AppConfig = self._load_cfg()
        self.script_path: Path | None = None
        self.doc: LectureDocument | None = None
        self.chunks = []
        self.status: dict[int, str] = {}
        self.manifest: dict | None = None
        self.timeline: list[dict] = []
        self.building = False
        self._light_engines: dict[str, TTSEngine] = {}
        self._audition = None
        self._lexicon = None
        self._tasks: list[TaskThread] = []

        # 작업 스레드에 엔진 상주
        self.worker_thread = QThread(self)
        self.host = EngineHost()
        self.host.moveToThread(self.worker_thread)
        self.worker_thread.finished.connect(self.host.deleteLater)
        self.worker_thread.start()
        self.requestBuild.connect(self.host.build)
        self.requestSpeak.connect(self.host.speak)
        # 주의: 작업 스레드 시그널은 반드시 QObject 메서드에 연결한다 (람다는 작업 스레드에서 직접 실행됨)
        self.host.engineLoading.connect(self._on_engine_loading)
        self.host.engineReady.connect(self._on_engine_ready)
        self.host.planReady.connect(self._on_plan)
        self.host.sectionStarted.connect(self._on_section_started)
        self.host.chunkDone.connect(self._on_chunk_done)
        self.host.chunkFailed.connect(self._on_chunk_failed)
        self.host.message.connect(self._on_host_message)
        self.host.buildFinished.connect(self._on_build_finished)
        self.host.buildFailed.connect(self._on_build_failed)
        self.host.speakReady.connect(self._on_speak_ready)
        self.host.speakFailed.connect(self._on_speak_failed)

        self._build_ui()
        self._build_menus()
        self.logLine.connect(self._append_log)
        self._log_handler = QtLogBridge(self.logLine.emit)
        logging.getLogger("lecture_tts").addHandler(self._log_handler)

        self.reparse_timer = QTimer(self, singleShot=True, interval=400, timeout=self.reparse)
        self.autosave_timer = QTimer(self, singleShot=True, interval=2000, timeout=self._autosave)
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.document().modificationChanged.connect(lambda _: self._update_title())

        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1280, 820)
        split = self.settings.value("splitter")
        if split is not None:
            self.splitter.restoreState(split)
        self.setAcceptDrops(True)
        self.settings_panel.load(self.cfg)
        self.editor.install_highlighter(self.cfg.parsing.section_patterns, self.cfg.parsing.title_pattern)
        self._set_building(False)
        self._update_title()
        self.reparse()

    # ======================================================================
    # UI 구성
    # ======================================================================
    def _build_ui(self) -> None:
        tb = self.addToolBar("main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.act_open = QAction("열기", self, shortcut=QKeySequence.StandardKey.Open, triggered=lambda: self.open_file())
        self.act_save = QAction("저장", self, shortcut=QKeySequence.StandardKey.Save, triggered=self.save)
        self.act_build_all = QAction("▶ 전체 생성", self, shortcut="F5", triggered=lambda: self.build("all"))
        self.act_build_all.setToolTip("모든 섹션을 생성합니다 (캐시된 문장은 재사용).")
        self.act_build_changed = QAction("⟳ 변경분만 생성", self, shortcut="Ctrl+F5",
                                         triggered=lambda: self.build("changed"))
        self.act_build_changed.setToolTip("수정됐거나 아직 생성되지 않은 섹션만 합성합니다.")
        self.act_stop = QAction("■ 중지", self, shortcut="Esc", triggered=self.stop)
        self.act_output = QAction("출력 폴더 열기", self, triggered=self.open_output)
        for a in (self.act_open, self.act_save):
            tb.addAction(a)
        tb.addSeparator()
        for a in (self.act_build_all, self.act_build_changed, self.act_stop):
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.act_output)

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(4, 4, 4, 4)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.section_list = SectionList()
        self.section_list.setMinimumWidth(170)
        self.section_list.sectionActivated.connect(self._goto_section)
        self.section_list.buildSection.connect(lambda i: self.build([i]))
        self.section_list.playSection.connect(self._play_section)

        self.tabs = QTabWidget()
        self.editor = ScriptEditor()
        self.editor.listenRequested.connect(self.listen)
        self.editor.addToLexicon.connect(self.open_lexicon)
        self.editor.playFromOffset.connect(self._play_from_offset)
        self.normalized = QPlainTextEdit(readOnly=True)
        self.normalized.setFont(self.editor.font())
        self.chunk_table = QTableWidget(0, 5)
        self.chunk_table.setHorizontalHeaderLabels(["청크", "글자", "쉼(ms)", "캐시", "읽을 텍스트"])
        self.chunk_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.chunk_table.verticalHeader().setVisible(False)
        self.chunk_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tabs.addTab(self.editor, "원문 편집")
        self.tabs.addTab(self.normalized, "정규화 미리보기")
        self.tabs.addTab(self.chunk_table, "청크 보기")

        self.settings_panel = SettingsPanel()
        self.settings_panel.setMinimumWidth(230)
        self.settings_panel.changed.connect(self._on_settings_changed)
        self.settings_panel.listenSelection.connect(lambda: self.listen(self.editor.selected_text()))
        self.settings_panel.openAudition.connect(self.open_audition)
        self.settings_panel.openLexicon.connect(lambda: self.open_lexicon(""))

        self.splitter.addWidget(self.section_list)
        self.splitter.addWidget(self.tabs)
        self.splitter.addWidget(self.settings_panel)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([210, 780, 270])
        v.addWidget(self.splitter, 1)

        self.player = PlayerBar()
        self.player.timelinePosition.connect(self._on_timeline)
        v.addWidget(self.player)

        prow = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress_label = QLabel("대기 중")
        prow.addWidget(self.progress_label)
        prow.addWidget(self.progress, 1)
        v.addLayout(prow)

        self.log_toggle = QToolButton()
        self.log_toggle.setText("▸ 로그")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setStyleSheet("QToolButton { border: 0; }")
        self.log_view = QPlainTextEdit(readOnly=True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setMaximumHeight(150)
        self.log_view.setVisible(False)
        self.log_toggle.toggled.connect(lambda on: (self.log_view.setVisible(on),
                                                    self.log_toggle.setText("▾ 로그" if on else "▸ 로그")))
        v.addWidget(self.log_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        v.addWidget(self.log_view)
        self.engine_label = QLabel("")
        self.statusBar().addPermanentWidget(self.engine_label)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu("파일(&F)")
        f.addAction("새 스크립트", QKeySequence.StandardKey.New, self.new_file)
        f.addAction(self.act_open)
        self.recent_menu = f.addMenu("최근 파일")
        self._refresh_recent()
        f.addAction(self.act_save)
        f.addAction("다른 이름으로 저장…", QKeySequence.StandardKey.SaveAs, self.save_as)
        f.addSeparator()
        f.addAction("프로젝트 열기…", self.open_project)
        f.addAction("프로젝트 저장", self.save_project)
        f.addSeparator()
        f.addAction("예제 스크립트 열기", lambda: self.open_example())
        f.addSeparator()
        f.addAction("종료", QKeySequence.StandardKey.Quit, self.close)

        b = mb.addMenu("생성(&B)")
        for a in (self.act_build_all, self.act_build_changed, self.act_stop, self.act_output):
            b.addAction(a)

        t = mb.addMenu("도구(&T)")
        t.addAction("선택 영역 듣기", "Ctrl+Space", lambda: self.listen(self.editor.selected_text()))
        t.addAction("음성 비교…", self.open_audition)
        t.addAction("발음 사전…", lambda: self.open_lexicon(""))
        t.addSeparator()
        t.addAction("초기 설정 마법사…", self.open_wizard)
        t.addAction("환경설정…", self.open_preferences)

        h = mb.addMenu("도움말(&H)")
        h.addAction("스크립트 문법", "F1", lambda: show_syntax_help(self))
        h.addAction("진단 정보 내보내기…", self.export_diagnostics)
        h.addAction("업데이트 확인", lambda: self.check_updates(manual=True))
        h.addSeparator()
        h.addAction("정보", lambda: show_about(self))

    # ======================================================================
    # 파일 / 프로젝트
    # ======================================================================
    @property
    def modified(self) -> bool:
        return self.editor.document().isModified()

    @modified.setter
    def modified(self, value: bool) -> None:
        self.editor.document().setModified(value)

    def _load_cfg(self) -> AppConfig:
        try:
            return load_config(overrides=self.overrides)
        except Exception as e:
            log.warning("설정 로드 실패, 기본값 사용: %s", e)
            self.overrides = {}
            return load_config()

    def maybe_save(self) -> bool:
        if not self.modified:
            return True
        if self.script_path and self.script_path.suffix.lower() in EDITABLE:
            return self.save()
        r = QMessageBox.question(self, "저장", "변경 내용을 저장할까요?",
                                 QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                 | QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if r == QMessageBox.StandardButton.Save else True

    def new_file(self) -> None:
        if not self.maybe_save():
            return
        self.script_path = None
        self.project = Project()
        self.editor.setPlainText("# Lecture title\n\n## Slide 1: Welcome\nHello everyone, and welcome.\n")
        self.modified = False
        self._after_open()

    def open_example(self) -> None:
        dst = paths.user_data_dir() / "samples" / "lecture_sample.md"
        dst.parent.mkdir(exist_ok=True)
        if not dst.exists():
            dst.write_text(paths.data_file("lecture_sample.md").read_text(encoding="utf-8"), encoding="utf-8")
        self.open_file(str(dst))

    def open_file(self, path: str | None = None) -> None:
        if not self.maybe_save():
            return
        if not path:
            start = self.settings.value("last_dir", str(Path.home()), type=str)
            path, _ = QFileDialog.getOpenFileName(self, "스크립트 또는 프로젝트 열기", start,
                                                  SCRIPT_FILTER + f";;프로젝트 (*{PROJECT_EXT})")
            if not path:
                return
        p = Path(path)
        if p.suffix.lower() == PROJECT_EXT:
            self._open_project_file(p)
            return
        try:
            text = load_file(p)
        except Exception as e:
            QMessageBox.warning(self, "열기 실패", str(e))
            return
        self.script_path = p
        sibling = p.with_suffix(PROJECT_EXT)
        self.project = Project.load(sibling) if sibling.exists() else Project(script=str(p))
        if self.project.overrides:
            self.overrides = self.project.overrides
            self.cfg = self._load_cfg()
            self.settings_panel.load(self.cfg)
        self.editor.setPlainText(text)
        self.modified = False
        self.settings.setValue("last_dir", str(p.parent))
        self._add_recent(str(p))
        if p.suffix.lower() not in EDITABLE:
            self._log(f"{p.suffix} 파일은 텍스트로 가져왔습니다. 수정하면 .md로 저장됩니다.")
        self._after_open()

    def _open_project_file(self, p: Path) -> None:
        try:
            proj = Project.load(p)
        except Exception as e:
            QMessageBox.warning(self, "프로젝트 열기 실패", str(e))
            return
        if not proj.script or not Path(proj.script).exists():
            QMessageBox.warning(self, "프로젝트 열기", f"스크립트 파일을 찾을 수 없습니다: {proj.script}")
            return
        self.open_file(proj.script)
        self.project = proj
        self.overrides = proj.overrides
        self.cfg = self._load_cfg()
        self.settings_panel.load(self.cfg)
        self.reparse()

    def open_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "프로젝트 열기", self.settings.value("last_dir", "", type=str),
                                              f"프로젝트 (*{PROJECT_EXT})")
        if path:
            self._open_project_file(Path(path))

    def save_project(self) -> None:
        if not self.script_path and not self.save_as():
            return
        target = self.project.path or str(self.script_path.with_suffix(PROJECT_EXT))
        self.project.script = str(self.script_path)
        self.project.overrides = self.overrides
        self.project.save(target)
        self.statusBar().showMessage(f"프로젝트 저장: {target}", 4000)

    def _after_open(self) -> None:
        self.manifest = None
        self.player.unload()
        self.player.set_sources([])
        self._update_title()
        self.reparse()
        self._load_manifest()

    def save(self) -> bool:
        if not self.script_path or self.script_path.suffix.lower() not in EDITABLE:
            return self.save_as()
        try:
            self.script_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as e:
            QMessageBox.warning(self, "저장 실패", str(e))
            return False
        self.modified = False
        self._update_title()
        if self.project.path:
            self.project.save(self.project.path)
        return True

    def save_as(self) -> bool:
        start = str(self.script_path.with_suffix(".md")) if self.script_path else \
            str(Path(self.settings.value("last_dir", str(Path.home()), type=str)) / "lecture.md")
        path, _ = QFileDialog.getSaveFileName(self, "다른 이름으로 저장", start, "Markdown (*.md);;텍스트 (*.txt)")
        if not path:
            return False
        self.script_path = Path(path)
        self.project.script = path
        self._add_recent(path)
        ok = self.save()
        self._after_open()
        return ok

    def _autosave(self) -> None:
        if self.modified and self.script_path and self.script_path.suffix.lower() in EDITABLE and not self.building:
            self.save()

    def _add_recent(self, path: str) -> None:
        rec = [p for p in self.settings.value("recent", [], type=list) if p != path]
        self.settings.setValue("recent", [path] + rec[:7])
        self._refresh_recent()

    def _refresh_recent(self) -> None:
        self.recent_menu.clear()
        rec = self.settings.value("recent", [], type=list)
        for p in rec:
            self.recent_menu.addAction(p, lambda p=p: self.open_file(p))
        self.recent_menu.setEnabled(bool(rec))

    def _update_title(self) -> None:
        name = self.script_path.name if self.script_path else "제목 없음"
        self.setWindowTitle(f"{name}{' *' if self.modified else ''} — Lecture TTS {__version__}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.open_file(urls[0].toLocalFile())

    # ======================================================================
    # 파싱·상태 갱신
    # ======================================================================
    def _on_text_changed(self) -> None:
        if not self.modified:  # 구문 강조 갱신 등 내용 변경이 아닌 신호
            return
        self.reparse_timer.start()
        self.autosave_timer.start()

    def _light_engine(self) -> TTSEngine:
        """모델을 올리지 않은 엔진 객체 (청크 계획·캐시 키 계산용)."""
        key = f"{self.cfg.engine.name}:{self.cfg.engine_cfg().model_dump_json()}"
        if key not in self._light_engines:
            self._light_engines[key] = create_engine(self.cfg)
        return self._light_engines[key]

    def out_dir(self) -> Path | None:
        return output_dir_for(self.script_path, self.cfg) if self.script_path else None

    def reparse(self) -> None:
        text = self.editor.toPlainText()
        try:
            self.doc = parse_text(text, self.cfg, str(self.script_path or ""))
            self.chunks = plan_chunks(self.doc, self.cfg, self._light_engine())
        except Exception as e:
            self.statusBar().showMessage(f"파싱 오류: {e}", 5000)
            return
        self.editor.set_warnings(self.doc.warnings)
        cache = TTSCache(self.cfg.cache_path())
        out = self.out_dir()
        if out:
            self.manifest = read_manifest(out)
            self.status = diff_sections(self.doc, self.chunks, self.manifest, cache, out)
        else:
            self.status = {s.index: "new" for s in self.doc.sections}
        if not self.building:
            self.section_list.set_sections([(s.index, s.label) for s in self.doc.sections], self.status)
        self.normalized.setPlainText(normalized_script(self.doc))
        self._fill_chunk_table(cache)
        n_chars = sum(len(c.text) for c in self.chunks)
        self.statusBar().showMessage(
            f"섹션 {len(self.doc.sections)} · 청크 {len(self.chunks)} · {n_chars:,}자 · 예상 길이 약 "
            f"{n_chars / 15 / 60 / max(self.cfg.engine.rate, 0.1):.1f}분"
            + (f" · 경고 {len(self.doc.warnings)}" if self.doc.warnings else ""))

    def _fill_chunk_table(self, cache: TTSCache) -> None:
        t = self.chunk_table
        t.setUpdatesEnabled(False)
        t.setRowCount(len(self.chunks))
        for r, c in enumerate(self.chunks):
            for col, val in enumerate((c.id, str(len(c.text)), str(c.trailing_pause_ms or ""),
                                       "✓" if cache.has(c.cache_key) else "", c.text)):
                item = QTableWidgetItem(val)
                if col == 4:
                    item.setToolTip(c.display_text)
                t.setItem(r, col, item)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        t.setUpdatesEnabled(True)

    def _load_manifest(self) -> None:
        out = self.out_dir()
        self.manifest = read_manifest(out) if out else None
        self.timeline = []
        sources: list[tuple[str, str, int | None]] = []
        if self.manifest:
            if self.manifest.get("merged_file"):
                p = out / self.manifest["merged_file"]
                if p.exists():
                    sources.append(("전체", str(p), 0))
            for s in self.manifest.get("sections", []):
                if s.get("file") and (out / s["file"]).exists():
                    label = f"섹션 {s.get('number') or s['index']} {s.get('title') or ''}".strip()
                    sources.append((label, str(out / s["file"]), s["start_ms"]))
                self.timeline.extend(s.get("chunks", []))
        self.player.set_sources(sources)

    def _on_settings_changed(self) -> None:
        self.overrides = self.settings_panel.overrides()
        self.settings.setValue("last_overrides", json.dumps(self.overrides))
        self.project.overrides = self.overrides
        self.cfg = self._load_cfg()
        self.reparse()
        self._load_manifest()
        if self.project.path:
            self.project.save(self.project.path)

    # ======================================================================
    # 생성
    # ======================================================================
    def _set_building(self, on: bool) -> None:
        self.building = on
        self.act_build_all.setEnabled(not on)
        self.act_build_changed.setEnabled(not on)
        self.act_stop.setEnabled(on)
        self.settings_panel.setEnabled(not on)
        if not on:
            self.progress_label.setText("대기 중")

    def _engine_ready_or_wizard(self) -> bool:
        problems = self._light_engine().problems()
        if not problems:
            return True
        if self.cfg.engine.name == "kokoro":
            QMessageBox.information(self, "초기 설정 필요", "\n".join(problems))
            self.open_wizard()
            return not self._light_engine().problems()
        QMessageBox.warning(self, "엔진 준비 안 됨", "\n".join(problems))
        return False

    def build(self, mode) -> None:
        if self.building:
            return
        if not self.save():  # 생성 직전 강제 저장
            return
        self.reparse()
        if not self.doc or not self.chunks:
            QMessageBox.information(self, "생성", "읽을 내용이 없습니다.")
            return
        if not self._engine_ready_or_wizard():
            return
        if mode == "all":
            sections = None
        elif mode == "changed":
            sections = [i for i, st in self.status.items() if st != "done"]
            if not sections:
                self.statusBar().showMessage("변경된 섹션이 없습니다 — 모두 최신 상태입니다.", 5000)
                return
        else:
            sections = list(mode)
        self.player.unload()  # 출력 파일 잠금 해제
        self._set_building(True)
        self._targets = set(sections) if sections else {s.index for s in self.doc.sections}
        self._t0 = time.perf_counter()
        self._done_chunks = 0
        self._done_chars = 0
        self._total_chars = 0
        self._speed = deque(maxlen=12)
        self._sections_done = 0
        self.progress.setRange(0, 0)
        self.progress_label.setText("준비 중…")
        self._log(f"생성 시작: {'전체' if sections is None else '섹션 ' + ', '.join(map(str, sections))}")
        self.requestBuild.emit(self.cfg.model_copy(deep=True), str(self.script_path), sections, True)

    def stop(self) -> None:
        if self.building:
            self.host.cancel_token.cancel()
            self.progress_label.setText("중지하는 중… (현재 문장 합성이 끝나면 멈춥니다)")

    def _on_plan(self, total: int, chars: int, cached: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(0)
        self._total = total
        self._total_chars = chars

    def _on_section_started(self, idx: int, n: int) -> None:
        self.section_list.set_one(idx, "running")
        self._cur_section = idx
        self._sections_done += 1
        self._update_progress_label()

    def _on_chunk_done(self, section: int, chunk_id: str, cached: bool, chars: int, seconds: float) -> None:
        self._done_chunks += 1
        self._done_chars += chars
        if not cached and chars:
            self._speed.append(seconds / chars)
        self.progress.setValue(self._done_chunks)
        self._update_progress_label()

    def _update_progress_label(self) -> None:
        eta = ""
        if self._speed:
            remain = (sum(self._speed) / len(self._speed)) * max(self._total_chars - self._done_chars, 0)
            m, s = divmod(int(remain), 60)
            eta = f" · 남은 시간 약 {m}분 {s}초" if m else f" · 남은 시간 약 {s}초"
        self.progress_label.setText(f"진행: 섹션 {self._sections_done}/{len(self._targets)} · "
                                    f"청크 {self._done_chunks}/{getattr(self, '_total', 0)}{eta}")

    def _on_build_finished(self, result) -> None:
        self._set_building(False)
        elapsed = time.perf_counter() - self._t0
        self.progress.setRange(0, 1)
        self.progress.setValue(1 if not result.cancelled else 0)
        self.reparse()
        for cid, _ in result.failed:
            self.section_list.set_one(int(cid.split("-")[0]), "error")
        self._load_manifest()
        if result.cancelled:
            self._log("■ 중지됨 — 완료된 문장은 캐시에 남았습니다.")
            self.progress_label.setText("중지됨")
            return
        msg = f"완료 ({elapsed:.1f}초) · 새로 합성 {result.synthesized} · 캐시 {result.cached}"
        if result.merged_path:
            msg += f" · 전체 {result.total_duration_ms / 1000 / 60:.1f}분"
        self._log("✓ " + msg)
        self.progress_label.setText(msg)
        self.project.last_output = str(result.out_dir)
        if result.failed:
            QMessageBox.warning(self, "일부 실패", f"{len(result.failed)}개 문장을 합성하지 못했습니다.\n"
                                "‘변경분만 생성’을 다시 누르면 실패한 문장만 재시도합니다.\n\n"
                                + "\n".join(f"{i}: {e[:120]}" for i, e in result.failed[:5]))

    def _on_build_failed(self, msg: str, details: str) -> None:
        self._set_building(False)
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.reparse()
        self._log("✕ " + msg)
        box = QMessageBox(QMessageBox.Icon.Warning, "생성 실패", msg, parent=self)
        box.setDetailedText(details)
        box.exec()

    def open_output(self) -> None:
        out = self.out_dir()
        if out is None:
            return
        out.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    # ======================================================================
    # 재생·하이라이트
    # ======================================================================
    def _on_timeline(self, ms) -> None:
        if ms is None or not self.timeline:
            self.editor.highlight_playing(None, None)
            return
        for c in self.timeline:
            if c["start_ms"] <= ms < c["end_ms"]:
                self.editor.highlight_playing(c["src_start"], c["src_end"])
                return

    def _play_from_offset(self, offset: int) -> None:
        if not self.timeline:
            self.statusBar().showMessage("아직 생성된 오디오가 없습니다.", 4000)
            return
        hit = next((c for c in self.timeline if c["src_start"] <= offset <= c["src_end"]), None)
        if hit is None:
            hit = min(self.timeline, key=lambda c: abs(c["src_start"] - offset))
        if not self.player.play_label("전체", hit["start_ms"]):
            for s in (self.manifest or {}).get("sections", []):
                if any(c["id"] == hit["id"] for c in s.get("chunks", [])):
                    label = f"섹션 {s.get('number') or s['index']} {s.get('title') or ''}".strip()
                    self.player.play_label(label, hit["start_ms"] - s["start_ms"])

    def _play_section(self, idx: int) -> None:
        for s in (self.manifest or {}).get("sections", []):
            if s["index"] == idx:
                self.player.play_label(f"섹션 {s.get('number') or s['index']} {s.get('title') or ''}".strip(), 0)

    def _goto_section(self, idx: int) -> None:
        if not self.doc:
            return
        for s in self.doc.sections:
            if s.index == idx:
                self.tabs.setCurrentWidget(self.editor)
                self.editor.goto_offset(s.src_start)
                self.editor.highlight_section(s.src_start, s.src_end)

    # ======================================================================
    # 즉시 듣기·보조 창
    # ======================================================================
    def listen(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            self.statusBar().showMessage("편집기에서 들을 문장을 선택하세요.", 4000)
            return
        if not self._engine_ready_or_wizard():
            return
        self.statusBar().showMessage("합성 중…" + (" (생성 작업이 끝난 뒤 처리됩니다)" if self.building else ""))
        self.requestSpeak.emit(self.cfg.model_copy(deep=True), text[:2000], "sel")

    def _on_speak_ready(self, tag: str, path: str) -> None:
        if tag == "sel" or tag.startswith("lex:"):
            self.statusBar().clearMessage()
            self.player.play_temp("선택 영역", path)
        elif tag.startswith("aud:") and self._audition is not None:
            self._audition.on_ready(tag, path)

    def _on_speak_failed(self, tag: str, msg: str) -> None:
        if tag.startswith("aud:") and self._audition is not None:
            self._audition.on_failed(tag, msg)
        else:
            self.statusBar().showMessage(f"합성 실패: {msg}", 6000)

    def open_audition(self) -> None:
        from .dialogs.audition import AuditionDialog

        if not self._engine_ready_or_wizard():
            return
        dlg = AuditionDialog(self.cfg, self.editor.selected_text(), self)
        self._audition = dlg
        dlg.requestSpeak.connect(self.requestSpeak)
        dlg.playFile.connect(self.player.play_temp)
        dlg.setDefault.connect(self._set_default_voice)
        dlg.finished.connect(lambda _: setattr(self, "_audition", None))
        dlg.show()

    def _set_default_voice(self, voice: str, rate: float) -> None:
        cfg = self.cfg.model_copy(deep=True)
        cfg.set_voice(voice)
        cfg.engine.rate = rate
        self.settings_panel.load(cfg)
        self._on_settings_changed()
        self._log(f"기본 음성: {voice} · 속도 {rate:.2f}")

    def open_lexicon(self, word: str = "") -> None:
        from .dialogs.lexicon_editor import LexiconEditor

        dlg = LexiconEditor(self.cfg.lexicon_path(), word, self)
        dlg.requestSpeak.connect(lambda text, tag: self.requestSpeak.emit(self.cfg.model_copy(deep=True), text, tag))
        dlg.saved.connect(self.reparse)
        dlg.show()
        self._lexicon = dlg

    def open_wizard(self) -> None:
        from .dialogs.setup_wizard import SetupWizard

        SetupWizard(self, self.cfg.engines.kokoro.repo_id).exec()
        self._light_engines.clear()
        self.reparse()

    def open_preferences(self) -> None:
        from .dialogs.preferences import PreferencesDialog

        if PreferencesDialog(self.cfg, self).exec():
            self.cfg = self._load_cfg()
            self._light_engines.clear()
            self.reparse()

    def export_diagnostics(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "진단 정보 저장",
                                              str(Path.home() / "LectureTTS_diagnostics.zip"), "Zip (*.zip)")
        if path:
            try:
                export_diagnostics(Path(path))
                QMessageBox.information(self, "진단 정보", f"저장했습니다 (스크립트 원문·API 키는 포함되지 않음).\n{path}")
            except Exception as e:
                QMessageBox.warning(self, "진단 정보", f"저장 실패: {e}")

    def check_updates(self, manual: bool = False) -> None:
        url = self.settings.value("update/url", UPDATE_URL, type=str)
        if not url:
            if manual:
                QMessageBox.information(self, "업데이트 확인", "업데이트 확인 주소가 설정되지 않았습니다 (환경설정 → 업데이트).")
            return
        self._update_manual = manual
        task = TaskThread(lambda _cb: check_latest(url), self)
        task.succeeded.connect(self._on_update_result)
        task.failed.connect(self._on_update_failed)
        self._tasks.append(task)
        task.start()

    def _on_update_result(self, res) -> None:
        if res:
            tag, page = res
            if QMessageBox.question(self, "새 버전", f"새 버전 {tag}이(가) 있습니다. 배포 페이지를 열까요?") \
                    == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(page))
        elif self._update_manual:
            QMessageBox.information(self, "업데이트 확인", f"최신 버전입니다 ({__version__}).")

    def _on_update_failed(self, err: str) -> None:
        if self._update_manual:
            QMessageBox.warning(self, "업데이트 확인", f"확인 실패: {err}")

    def first_run_checks(self) -> None:
        if self.cfg.engine.name == "kokoro" and self._light_engine().problems():
            self.open_wizard()
        if self.settings.value("update/check", True, type=bool):
            self.check_updates(manual=False)

    # ======================================================================
    # 로그·종료
    # ======================================================================
    def _on_engine_loading(self, name: str) -> None:
        self._engine_state(f"{name} 모델 불러오는 중…")

    def _on_engine_ready(self, name: str) -> None:
        self._engine_state(f"{name} 준비됨")

    def _on_chunk_failed(self, where: str, msg: str) -> None:
        self._log(f"✕ {where}: {msg}")

    def _on_host_message(self, level: str, text: str) -> None:
        self._log(("⚠ " if level == "warning" else "") + text)

    def _engine_state(self, text: str) -> None:
        self.engine_label.setText(text)
        self._log(text)

    def _log(self, text: str) -> None:
        self._append_log(time.strftime("%H:%M:%S  ") + text)

    def _append_log(self, line: str) -> None:
        self.log_view.appendPlainText(line)

    def closeEvent(self, e) -> None:
        if self.building:
            if QMessageBox.question(self, "종료", "생성 중입니다. 중지하고 종료할까요?") != QMessageBox.StandardButton.Yes:
                e.ignore()
                return
            self.host.cancel_token.cancel()
        if not self.maybe_save():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.splitter.saveState())
        logging.getLogger("lecture_tts").removeHandler(self._log_handler)
        self.player.unload()
        self.worker_thread.quit()
        if not self.worker_thread.wait(15000):
            os._exit(0)  # 합성 중인 모델 호출이 끝나지 않으면 강제 종료
        for t in self._tasks:
            t.wait(2000)
        e.accept()
        QApplication.instance().quit()
