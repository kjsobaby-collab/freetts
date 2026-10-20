import json

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QSettings  # noqa: E402


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path / "qsettings"))
    app = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.instance()
    app.setOrganizationName("LectureTTS-test")
    app.setApplicationName("LectureTTS-test")
    s = QSettings()
    s.setValue("last_overrides", json.dumps({"engine": {"name": "fake"}, "audio": {"format": "wav"}}))
    s.setValue("update/check", False)
    from lecture_tts.gui.main_window import MainWindow
    w = MainWindow()
    qtbot.addWidget(w)
    yield w
    w.worker_thread.quit()
    w.worker_thread.wait(5000)


def test_open_shows_sections(window, sample_md):
    window.open_file(str(sample_md))
    assert window.section_list.list.count() == 2
    assert window.cfg.engine.name == "fake"
    assert "R-E-L-U" in window.normalized.toPlainText()
    assert window.chunk_table.rowCount() == len(window.chunks) > 0


def test_build_all_then_status_done(window, qtbot, sample_md):
    window.open_file(str(sample_md))
    with qtbot.waitSignal(window.host.buildFinished, timeout=30000) as sig:
        window.build("all")
    qtbot.waitUntil(lambda: not window.building)
    res = sig.args[0]
    assert res.merged_path and res.merged_path.exists()
    assert set(window.status.values()) == {"done"}
    assert window.player.source.count() == 3          # 전체 + 섹션 2개
    assert window.timeline and window.timeline[0]["src_start"] > 0


def test_edit_marks_section_changed_and_changed_build(window, qtbot, sample_md):
    window.open_file(str(sample_md))
    with qtbot.waitSignal(window.host.buildFinished, timeout=30000):
        window.build("all")
    qtbot.waitUntil(lambda: not window.building)
    window.editor.setPlainText(window.editor.toPlainText().replace("weighted sum", "weighted total"))
    window.reparse()
    assert window.status == {1: "done", 2: "changed"}
    with qtbot.waitSignal(window.host.buildFinished, timeout=30000) as sig:
        window.build("changed")
    qtbot.waitUntil(lambda: not window.building)
    assert sig.args[0].synthesized == 1
    assert set(window.status.values()) == {"done"}


def test_settings_change_updates_cfg(window, sample_md):
    window.open_file(str(sample_md))
    window.settings_panel.rate.setValue(90)
    assert window.cfg.engine.rate == 0.9


def test_listen_selection(window, qtbot, sample_md):
    window.open_file(str(sample_md))
    with qtbot.waitSignal(window.host.speakReady, timeout=30000) as sig:
        window.listen("Hello there.")
    assert sig.args[0] == "sel"
