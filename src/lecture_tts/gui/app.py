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


def selftest(out_dir: str) -> int:
    """배포판 점검: 예제 스크립트 첫 섹션을 실제 엔진으로 합성해 out_dir에 저장하고 결과를 selftest.txt에 기록.

    콘솔이 없는 GUI 실행 파일이므로 결과는 파일로 남긴다. 사용: LectureTTS.exe --selftest <폴더>
    """
    import asyncio
    import shutil
    from pathlib import Path

    from .. import __version__, paths
    from ..config import load_config
    from ..pipeline import run_pipeline

    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = out / "selftest.txt"
    try:
        script = out / "selftest_sample.md"
        shutil.copyfile(paths.data_file("lecture_sample.md"), script)
        cfg = load_config(overrides={"runtime": {"output_dir": str(out)}})
        res = asyncio.run(run_pipeline(script, cfg, sections=[1], use_cache=False))
        files = sorted(str(p.relative_to(out)) for p in res.out_dir.rglob("*") if p.is_file())
        ok = not res.failed and any(f.endswith((".mp3", ".wav")) for f in files)
        report.write_text(f"{'OK' if ok else 'FAIL'}\nversion {__version__}\nengine {cfg.engine.name}\n"
                          f"synthesized {res.synthesized}\nfailed {res.failed}\n" + "\n".join(files) + "\n",
                          encoding="utf-8")
        return 0 if ok else 1
    except Exception:
        report.write_text("FAIL\n" + traceback.format_exc(), encoding="utf-8")
        return 1


def main(argv: list[str] | None = None) -> int:
    from .. import APP_NAME, __version__, paths

    paths.setup_runtime_env()
    _setup_logging()
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) >= 2 and args[0] == "--selftest":
        return selftest(args[1])
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
