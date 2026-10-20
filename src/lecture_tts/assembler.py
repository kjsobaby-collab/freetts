"""청크 오디오 연결, 쉼 삽입, 음량 정규화, 파일 export, 타임라인 계산."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import soundfile as sf

from . import paths
from .config import AudioConfig
from .models import AudioClip, Chunk


@dataclass
class ChunkTiming:
    id: str
    start_ms: int
    end_ms: int
    text: str
    src_start: int = 0
    src_end: int = 0


@dataclass
class SectionAudio:
    index: int
    audio: np.ndarray
    chunks: list[ChunkTiming] = field(default_factory=list)   # 섹션 기준 시간


def resample(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    if src_sr == dst_sr or len(audio) == 0:
        return audio
    n = int(round(len(audio) * dst_sr / src_sr))
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


def load_clip(path: str, sr: int) -> np.ndarray:
    if not path:
        return np.zeros(0, dtype=np.float32)
    data, file_sr = sf.read(path, dtype="float32", always_2d=True)
    return resample(data.mean(axis=1), file_sr, sr)


def measure_loudness(audio: np.ndarray, sr: int) -> float | None:
    """BS.1770 방식의 게이팅 적용 근사 라우드니스 (K-가중치 생략)."""
    win, hop = int(0.4 * sr), int(0.1 * sr)
    if len(audio) < win:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(audio, win)[::hop]
    ms = (frames.astype(np.float64) ** 2).mean(axis=1)
    lufs = -0.691 + 10 * np.log10(ms + 1e-12)
    gated = ms[lufs > -70]
    if gated.size == 0:
        return None
    rel = -0.691 + 10 * np.log10(gated.mean()) - 10
    gated = ms[lufs > max(-70, rel)]
    return float(-0.691 + 10 * np.log10(gated.mean()))


def normalize_loudness(audio: np.ndarray, sr: int, target_lufs: float, peak_db: float = -1.0) -> np.ndarray:
    loud = measure_loudness(audio, sr)
    if loud is None:
        return audio
    out = audio * (10 ** ((target_lufs - loud) / 20))
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    limit = 10 ** (peak_db / 20)
    if peak > limit:
        out = out * (limit / peak)
    return out.astype(np.float32)


def export_audio(audio: np.ndarray, sr: int, path: Path, fmt: str, bitrate: str = "128k") -> Path:
    path = Path(path).with_suffix(f".{fmt}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "wav":
        sf.write(str(path), audio, sr, subtype="PCM_16")
        return path
    ffmpeg = paths.find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("mp3 출력에는 ffmpeg가 필요합니다. ffmpeg를 설치하거나 출력 포맷을 wav로 바꾸세요.")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1",
           "-i", "pipe:0", "-codec:a", "libmp3lame", "-b:a", bitrate, str(path)]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.run(cmd, input=np.ascontiguousarray(audio, dtype="<f4").tobytes(),
                          capture_output=True, creationflags=flags)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 오류: {proc.stderr.decode(errors='replace')[-500:]}")
    return path


class AudioAssembler:
    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self.sr = cfg.sample_rate

    def silence(self, ms: int) -> np.ndarray:
        return np.zeros(int(self.sr * ms / 1000), dtype=np.float32)

    def build_section(self, index: int, chunks: list[Chunk], clips: dict[str, AudioClip]) -> SectionAudio:
        parts: list[np.ndarray] = [self.silence(self.cfg.section_padding_ms)]
        pos = len(parts[0])
        timings: list[ChunkTiming] = []
        for c in chunks:
            audio = load_clip(clips[c.id].path, self.sr)
            start = pos
            parts.append(audio)
            pos += len(audio)
            if c.text:
                timings.append(ChunkTiming(c.id, self._ms(start), self._ms(pos), c.display_text,
                                           c.src_start, c.src_end))
            if c.trailing_pause_ms:
                gap = self.silence(c.trailing_pause_ms)
                parts.append(gap)
                pos += len(gap)
        parts.append(self.silence(self.cfg.section_padding_ms))
        audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        audio = normalize_loudness(audio, self.sr, self.cfg.loudness_lufs)
        return SectionAudio(index, audio, timings)

    def _ms(self, samples: int) -> int:
        return int(round(samples * 1000 / self.sr))

    def length_ms(self, sa: SectionAudio) -> int:
        return self._ms(len(sa.audio))
