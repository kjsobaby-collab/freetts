"""설정 로드/검증.

우선순위: CLI 옵션 > --config 파일 > 사용자 설정(settings.yaml) > 기본값(data/default.yaml)
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from . import paths

SCHEMA_VERSION = 1


class EngineSelection(BaseModel):
    name: str = "kokoro"
    fallback_engine: str | None = "kokoro"
    rate: float = Field(1.0, gt=0.25, le=4.0)


class KokoroConfig(BaseModel):
    lang_code: str = "a"
    voice: str = "af_heart"
    max_chars: int = 400
    device: str = "auto"          # auto | cpu | cuda | mps
    repo_id: str = "hexgrad/Kokoro-82M"


class PiperConfig(BaseModel):
    voice: str = "en_US-lessac-high"
    model_path: str | None = None  # None이면 사용자 모델 폴더의 {voice}.onnx
    max_chars: int = 400


class AzureConfig(BaseModel):
    voice: str = "en-US-JennyNeural"
    region_env: str = "AZURE_SPEECH_REGION"
    key_env: str = "AZURE_SPEECH_KEY"
    monthly_char_limit: int = 500_000
    warn_at_ratio: float = 0.8
    max_chars: int = 3000


class FakeConfig(BaseModel):
    voice: str = "sine"
    ms_per_char: int = 55
    max_chars: int = 400


class EnginesConfig(BaseModel):
    kokoro: KokoroConfig = KokoroConfig()
    piper: PiperConfig = PiperConfig()
    azure: AzureConfig = AzureConfig()
    fake: FakeConfig = FakeConfig()


class SpeakerConfig(BaseModel):
    voice: str | None = None       # None이면 엔진 기본 음성
    rate: float = 1.0


class ParsingConfig(BaseModel):
    section_patterns: list[str] = [
        r"^##\s*Slide\s*(\d+)\s*[:.]?\s*(.*)$",
        r"^\[SLIDE\s*(\d+)\]\s*(.*)$",
        r"^Slide\s+(\d+)\s*[.:)]\s*(.*)$",
        r"^##\s+(?!#)(.+)$",
    ]
    title_pattern: str = r"^#\s+(?!#)(.+)$"
    read_title: bool = False
    read_section_titles: bool = False
    read_preamble: bool = False    # 첫 섹션 마커 이전 텍스트를 읽을지
    default_pause_ms: int = 1000   # 길이 없는 [pause]
    on_invalid_directive: Literal["warn", "error", "keep_text"] = "warn"


class NormalizationConfig(BaseModel):
    lexicon: str | None = None     # None이면 사용자 데이터 폴더의 lexicon.yaml
    spell_out_acronyms: bool = True
    read_urls: bool = True


class ChunkingConfig(BaseModel):
    strategy: Literal["sentence", "paragraph"] = "sentence"
    min_chars: int = 30
    max_chars: int | None = None


class AudioConfig(BaseModel):
    format: Literal["mp3", "wav"] = "mp3"
    bitrate: str = "128k"
    sample_rate: int = 24000
    paragraph_pause_ms: int = 600
    section_padding_ms: int = 1000
    loudness_lufs: float = -16.0
    export_sections: bool = True
    export_merged: bool = True


class SubtitlesConfig(BaseModel):
    formats: list[Literal["srt", "vtt"]] = ["srt", "vtt"]
    max_line_chars: int = 42


class RuntimeConfig(BaseModel):
    concurrency: int = Field(1, ge=1, le=16)
    max_retries: int = 3
    cache_dir: str | None = None   # None이면 사용자 데이터 폴더
    output_dir: str | None = None  # None이면 스크립트 폴더/output


class AppConfig(BaseModel):
    schema_version: int = SCHEMA_VERSION
    engine: EngineSelection = EngineSelection()
    engines: EnginesConfig = EnginesConfig()
    speakers: dict[str, SpeakerConfig] = {
        "default": SpeakerConfig(),
        "student": SpeakerConfig(voice="am_michael", rate=1.05),
    }
    parsing: ParsingConfig = ParsingConfig()
    normalization: NormalizationConfig = NormalizationConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    audio: AudioConfig = AudioConfig()
    subtitles: SubtitlesConfig = SubtitlesConfig()
    runtime: RuntimeConfig = RuntimeConfig()

    # --- 편의 메서드 -------------------------------------------------------
    def engine_cfg(self, name: str | None = None) -> BaseModel:
        return getattr(self.engines, name or self.engine.name)

    @property
    def voice(self) -> str:
        return self.engine_cfg().voice  # type: ignore[attr-defined]

    def set_voice(self, voice: str) -> None:
        cfg = self.engine_cfg()
        cfg.voice = voice  # type: ignore[attr-defined]
        if self.engine.name == "kokoro" and voice[:1] in ("a", "b"):
            self.engines.kokoro.lang_code = voice[0]

    def cache_path(self) -> Path:
        return Path(self.runtime.cache_dir) if self.runtime.cache_dir else paths.default_cache_dir()

    def lexicon_path(self) -> Path:
        return Path(self.normalization.lexicon) if self.normalization.lexicon else paths.user_lexicon_path()

    def output_root(self, script_path: Path) -> Path:
        if self.runtime.output_dir:
            return Path(self.runtime.output_dir)
        return script_path.resolve().parent / "output"


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"설정 파일 형식 오류: {path}")
    return data


def load_config(
    config_file: Path | None = None,
    overrides: dict[str, Any] | None = None,
    *,
    use_user_settings: bool = True,
) -> AppConfig:
    data = read_yaml(paths.data_file("default.yaml"))
    if use_user_settings:
        data = deep_merge(data, read_yaml(paths.user_settings_path()))
    if config_file:
        if not Path(config_file).exists():
            raise FileNotFoundError(f"설정 파일이 없습니다: {config_file}")
        data = deep_merge(data, read_yaml(Path(config_file)))
    if overrides:
        data = deep_merge(data, overrides)
    return AppConfig.model_validate(data)


def save_user_settings(data: dict) -> None:
    data = dict(data)
    data["schema_version"] = SCHEMA_VERSION
    paths.user_settings_path().write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def load_lexicon(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def save_lexicon(path: Path, entries: dict[str, str]) -> None:
    text = "# 표기: 읽기\n" + yaml.safe_dump(entries, allow_unicode=True, sort_keys=True)
    path.write_text(text, encoding="utf-8")
