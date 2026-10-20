"""QMediaPlayer 기반 플레이어. 재생 위치를 '전체 타임라인 기준 ms'로 알려 문장 하이라이트에 쓴다."""
from __future__ import annotations

from PySide6.QtCore import QUrl, Qt, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QToolButton, QWidget


def fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60:02d}:{s % 60:02d}"


class PlayerBar(QWidget):
    timelinePosition = Signal(object)    # 전체 타임라인 기준 ms (임시 소스면 None)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(0.8)
        self._sources: list[tuple[str, str, int | None]] = []   # (라벨, 경로, 타임라인 offset)
        self._pending_seek: int | None = None
        self._seeking = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        self.btn_play = QToolButton()
        self.btn_play.setText("▶")
        self.btn_stop = QToolButton()
        self.btn_stop.setText("■")
        self.source = QComboBox()
        self.source.setMinimumWidth(180)
        self.pos_label = QLabel("00:00")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.dur_label = QLabel("00:00")
        vol_icon = QLabel("🔊")
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setMaximumWidth(90)
        for w in (self.btn_play, self.btn_stop, self.source, self.pos_label):
            lay.addWidget(w)
        lay.addWidget(self.slider, 1)
        for w in (self.dur_label, vol_icon, self.volume):
            lay.addWidget(w)

        self.btn_play.clicked.connect(self.toggle)
        self.btn_stop.clicked.connect(self.stop)
        self.source.activated.connect(lambda i: self._load(i, autoplay=True))
        self.slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.slider.sliderReleased.connect(self._seek_release)
        self.volume.valueChanged.connect(lambda v: self.audio.setVolume(v / 100))
        self.player.positionChanged.connect(self._pos)
        self.player.durationChanged.connect(self._dur)
        self.player.playbackStateChanged.connect(self._state)
        self.player.mediaStatusChanged.connect(self._status)

    # --- 소스 관리 -------------------------------------------------------------
    def set_sources(self, sources: list[tuple[str, str, int | None]]) -> None:
        cur = self.source.currentText()
        self._sources = list(sources)
        self.source.blockSignals(True)
        self.source.clear()
        for label, _, _ in sources:
            self.source.addItem(label)
        i = self.source.findText(cur)
        self.source.setCurrentIndex(i if i >= 0 else 0)
        self.source.blockSignals(False)

    def unload(self) -> None:
        """파일 잠금 해제 (재생성 전 덮어쓰기 가능하도록)."""
        self.player.stop()
        self.player.setSource(QUrl())

    def _load(self, i: int, autoplay=False, seek_ms: int | None = None) -> None:
        if not (0 <= i < len(self._sources)):
            return
        _, path, _ = self._sources[i]
        url = QUrl.fromLocalFile(path)
        if self.player.source() != url:
            self.player.setSource(url)
        if seek_ms is not None:
            self._pending_seek = seek_ms
            self.player.setPosition(seek_ms)
        if autoplay:
            self.player.play()

    def play_index(self, i: int, seek_ms: int | None = None) -> None:
        self.source.setCurrentIndex(i)
        self._load(i, autoplay=True, seek_ms=seek_ms)

    def play_label(self, label: str, seek_ms: int | None = None) -> bool:
        for i, (lb, _, _) in enumerate(self._sources):
            if lb == label:
                self.play_index(i, seek_ms)
                return True
        return False

    def play_temp(self, label: str, path: str) -> None:
        self._sources = [s for s in self._sources if s[2] is not None] + [(label, path, None)]
        self.set_sources(self._sources)
        self.play_index(len(self._sources) - 1)

    def current_offset(self) -> int | None:
        i = self.source.currentIndex()
        return self._sources[i][2] if 0 <= i < len(self._sources) else None

    # --- 재생 제어 -------------------------------------------------------------
    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.source().isEmpty():
                self._load(self.source.currentIndex())
            self.player.play()

    def stop(self) -> None:
        self.player.stop()
        self.timelinePosition.emit(None)

    def _seek_release(self) -> None:
        self._seeking = False
        self.player.setPosition(self.slider.value())

    def _pos(self, ms: int) -> None:
        if not self._seeking:
            self.slider.setValue(ms)
        self.pos_label.setText(fmt_ms(ms))
        off = self.current_offset()
        if self.player.playbackState() != QMediaPlayer.PlaybackState.StoppedState:
            self.timelinePosition.emit(None if off is None else off + ms)

    def _dur(self, ms: int) -> None:
        self.slider.setRange(0, ms)
        self.dur_label.setText(fmt_ms(ms))

    def _state(self, st) -> None:
        self.btn_play.setText("❚❚" if st == QMediaPlayer.PlaybackState.PlayingState else "▶")
        if st == QMediaPlayer.PlaybackState.StoppedState:
            self.timelinePosition.emit(None)

    def _status(self, st) -> None:
        if st in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia) \
                and self._pending_seek is not None:
            self.player.setPosition(self._pending_seek)
            self._pending_seek = None
