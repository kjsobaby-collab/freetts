"""GUI 진입점 (lecture-tts-gui)."""
from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback


def _setup_logging() -> None:
    from .. import paths

    log = logging.getLogger("lecture_tts")
    log.setLevel(logging.INFO)
    fh = logging.handlers.RotatingFileHandler(paths.logs_dir() / "app.log", maxBytes=2_000_000, backupCount=3,
                                              encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    log.addHandler(fh)


def _install_excepthook() -> None:
    """처리되지 않은 예외 → 로그 저장 + 충돌 대화상자."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    def hook(etype, value, tb):
        details = "".join(traceback.format_exception(etype, value, tb))
        logging.getLogger("lecture_tts").error("처리되지 않은 예외\n%s", details)
        if QApplication.instance() is not None:
            box = QMessageBox(QMessageBox.Icon.Critical, "오류",
                              f"예기치 않은 오류가 발생했습니다.\n{value}\n\n"
                              "도움말 → 진단 정보 내보내기로 로그를 저장해 보내 주세요.")
            box.setDetailedText(details)
            box.exec()

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    from .. import APP_NAME, __version__, paths

    paths.setup_runtime_env()
    _setup_logging()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1] + list(argv or sys.argv[1:]))
    app.setOrganizationName(APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")  # 시스템 밝은/어두운 테마를 따름
    _install_excepthook()
    logging.getLogger("lecture_tts").info("Lecture TTS %s 시작", __version__)

    w = MainWindow()
    w.show()
    args = list(argv if argv is not None else sys.argv[1:])
    if args:
        w.open_file(args[0])
    else:
        rec = w.settings.value("recent", [], type=list)
        from pathlib import Path
        if rec and Path(rec[0]).exists():
            w.open_file(rec[0])
        else:
            w.open_example()
    QTimer.singleShot(300, w.first_run_checks)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
