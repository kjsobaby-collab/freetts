"""전체 흐름 조립: Loader → Parser → Normalizer → Chunker → (Cache/Engine) → Assembler → Exporter."""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import __version__
from .assembler import AudioAssembler, SectionAudio, export_audio, load_clip, normalize_loudness
from .cache import TTSCache, make_cache_key
from .chunker import Chunker
from .config import AppConfig, load_lexicon
from .engines import EngineNotReady, TTSEngine, create_engine
from .loaders import load_file
from .models import AudioClip, Chunk, LectureDocument, Section
from .normalizer import Normalizer
from .parser import Parser
from .progress import BuildCancelled, CancelToken, ProgressReporter
from .subtitles import make_cues, write_subtitles
from .synthesizer import Synthesizer

log = logging.getLogger("lecture_tts")
MANIFEST = "manifest.json"


@dataclass
class BuildResult:
    out_dir: Path
    merged_path: Path | None = None
    manifest_path: Path | None = None
    section_files: dict[int, Path] = field(default_factory=dict)
    failed: list[tuple[str, str]] = field(default_factory=list)
    synthesized: int = 0
    cached: int = 0
    cancelled: bool = False
    total_duration_ms: int = 0
    messages: list[str] = field(default_factory=list)


# --- 문서·청크 준비 (합성 없이 가능: preview, GUI 상태 계산) ---------------------
def parse_text(text: str, cfg: AppConfig, source_path: str = "") -> LectureDocument:
    doc = Parser(cfg.parsing).parse(text, source_path=source_path)
    return Normalizer(cfg.normalization, load_lexicon(cfg.lexicon_path())).apply(doc)


def load_document(path: Path, cfg: AppConfig) -> LectureDocument:
    return parse_text(load_file(Path(path)), cfg, str(path))


def plan_chunks(doc: LectureDocument, cfg: AppConfig, engine: TTSEngine) -> list[Chunk]:
    voices = set(engine.list_voices()) or None
    chunks = Chunker(cfg, engine.max_chars, voices).split(doc)
    for c in chunks:
        c.cache_key = make_cache_key(engine.name, engine.version, c, engine.sample_rate)
    return chunks


def slugify(text: str | None, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)[:max_len].strip("-")


def section_slug(sec: Section) -> str:
    s = slugify(sec.title)
    return f"{sec.index:02d}_{s}" if s else f"{sec.index:02d}"


def output_dir_for(script_path: Path, cfg: AppConfig) -> Path:
    return cfg.output_root(Path(script_path)) / Path(script_path).stem


def read_manifest(out_dir: Path) -> dict | None:
    p = Path(out_dir) / MANIFEST
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def diff_sections(doc: LectureDocument, chunks: list[Chunk], manifest: dict | None,
                  cache: TTSCache, out_dir: Path) -> dict[int, str]:
    """섹션별 상태: done(최신) / changed(이전 결과와 다름·일부만 캐시) / new(미생성)."""
    by_sec: dict[int, list[str]] = {s.index: [] for s in doc.sections}
    for c in chunks:
        by_sec.setdefault(c.section_index, []).append(c.cache_key)
    built = {}
    for s in (manifest or {}).get("sections", []):
        f = out_dir / s.get("file", "")
        if s.get("file") and f.exists():
            built[s["index"]] = s.get("chunk_keys", [])
    status = {}
    for idx, keys in by_sec.items():
        if idx in built and built[idx] == keys:
            status[idx] = "done"
        elif idx in built or any(cache.has(k) for k in keys):
            status[idx] = "changed"
        else:
            status[idx] = "new"
    return status


# --- 빌드 ------------------------------------------------------------------
async def run_pipeline(
    input_path: Path,
    cfg: AppConfig,
    *,
    sections: list[int] | None = None,
    reporter: ProgressReporter | None = None,
    cancel: CancelToken | None = None,
    engine: TTSEngine | None = None,
    use_cache: bool = True,
    out_dir: Path | None = None,
) -> BuildResult:
    reporter = reporter or ProgressReporter()
    input_path = Path(input_path)
    out_dir = Path(out_dir) if out_dir else output_dir_for(input_path, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(out_dir / "build.log", mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    try:
        return await _run(input_path, cfg, sections, reporter, cancel, engine, use_cache, out_dir)
    finally:
        log.removeHandler(handler)
        handler.close()


async def _run(input_path, cfg, sections, reporter, cancel, engine, use_cache, out_dir) -> BuildResult:
    t0 = time.perf_counter()
    result = BuildResult(out_dir=out_dir)

    def say(level: str, text: str) -> None:
        result.messages.append(text)
        log.log(logging.WARNING if level == "warning" else logging.INFO, text)
        reporter.message(level, text)

    doc = load_document(input_path, cfg)
    for w in doc.warnings:
        say("warning", w.message)
    engine = engine or create_engine(cfg)
    if not engine.loaded and (problems := engine.problems()):
        raise EngineNotReady("\n".join(problems))
    cache = TTSCache(cfg.cache_path(), enabled=use_cache)
    chunks = plan_chunks(doc, cfg, engine)

    engine, cfg = _maybe_fallback(engine, chunks, cache, cfg, say)
    chunks = plan_chunks(doc, cfg, engine)

    prev = read_manifest(out_dir)
    if prev and prev.get("engine") and prev["engine"] != engine.name:
        say("warning", f"이전 결과는 '{prev['engine']}' 엔진으로 생성됐습니다. 엔진이 섞이면 음색이 달라집니다.")

    wanted = set(sections) if sections else {s.index for s in doc.sections}
    targets = [c for c in chunks if c.section_index in wanted]
    cached_n = sum(1 for c in targets if c.text and cache.get(c.cache_key))
    reporter.plan_ready(len(targets), sum(len(c.text) for c in targets), cached_n)
    log.info("섹션 %d개, 청크 %d개 (캐시 %d) — 엔진 %s / 음성 %s", len(wanted), len(targets), cached_n,
             engine.name, cfg.voice)

    synth = Synthesizer(engine, cache, cfg.runtime, reporter, cancel)
    clips: dict[str, AudioClip] = {}
    try:
        for sec in doc.sections:
            if sec.index not in wanted:
                continue
            sec_chunks = [c for c in targets if c.section_index == sec.index]
            reporter.section_started(sec.index, len(sec_chunks))
            got, failures = await synth.run(sec_chunks)
            clips.update(got)
            for f in failures:
                result.failed.append((f.chunk.id, str(f.error)))
            if cancel and cancel.cancelled:
                raise BuildCancelled()
    except BuildCancelled:
        result.cancelled = True
        result.synthesized, result.cached = synth.synthesized, synth.cached
        say("info", "중지됨 — 완료된 문장은 캐시에 저장되어 다음 생성 때 재사용됩니다.")
        return result
    result.synthesized, result.cached = synth.synthesized, synth.cached

    # 캐시가 완전한 모든 섹션을 다시 조립·export (합성 없이 빠름) → manifest와 파일이 항상 일치
    _export(doc, chunks, clips, cache, cfg, out_dir, input_path, engine, result, reporter, say)
    if result.failed:
        (out_dir / "failed_chunks.json").write_text(
            json.dumps([{"id": i, "error": e} for i, e in result.failed], ensure_ascii=False, indent=2),
            encoding="utf-8")
        say("warning", f"{len(result.failed)}개 문장 합성 실패 — 다시 생성하면 실패한 문장만 재시도합니다.")
    else:
        (out_dir / "failed_chunks.json").unlink(missing_ok=True)
    log.info("완료: 합성 %d, 캐시 %d, %.1fs", result.synthesized, result.cached, time.perf_counter() - t0)
    return result


def _maybe_fallback(engine, chunks, cache, cfg, say):
    if engine.name != "azure":
        return engine, cfg
    from .engines.azure_engine import build_ssml
    need = sum(len(build_ssml(c.text, c.voice, c.rate)) for c in chunks if c.text and not cache.has(c.cache_key))
    remaining = engine.remaining_chars()
    limit = cfg.engines.azure.monthly_char_limit
    if need > remaining:
        fb = cfg.engine.fallback_engine
        if fb and fb != "azure":
            say("warning", f"Azure 월 한도 부족 (필요 {need:,}자, 남음 {remaining:,}자) → '{fb}' 엔진으로 전환합니다.")
            cfg = cfg.model_copy(deep=True)
            cfg.engine.name = fb
            return create_engine(cfg), cfg
        raise RuntimeError(f"Azure 월 한도 부족 (필요 {need:,}자, 남음 {remaining:,}자)")
    if (limit - remaining + need) >= limit * cfg.engines.azure.warn_at_ratio:
        say("warning", f"Azure 이번 달 사용량이 한도의 {cfg.engines.azure.warn_at_ratio:.0%}를 넘습니다.")
    return engine, cfg


def _export(doc, chunks, clips, cache, cfg, out_dir, input_path, engine, result, reporter, say) -> None:
    asm = AudioAssembler(cfg.audio)
    fmt = cfg.audio.format
    sec_dir = out_dir / "sections"
    sec_dir.mkdir(exist_ok=True)
    built: list[tuple[Section, SectionAudio, list[Chunk]]] = []
    missing: list[int] = []
    for sec in doc.sections:
        sec_chunks = [c for c in chunks if c.section_index == sec.index]
        sec_clips = {}
        for c in sec_chunks:
            clip = clips.get(c.id) or (AudioClip(c.id, "", 0) if not c.text else cache.get(c.cache_key, c.id)) \
                or _cache_any(cfg, c)
            if clip is None:
                break
            sec_clips[c.id] = clip
        else:
            built.append((sec, asm.build_section(sec.index, sec_chunks, sec_clips), sec_chunks))
            continue
        missing.append(sec.index)

    manifest_sections = []
    produced: set[Path] = set()
    offset = 0
    for sec, sa, sec_chunks in built:
        dur = asm.length_ms(sa)
        entry = {
            "index": sec.index, "number": sec.number, "title": sec.title,
            "start_ms": offset, "end_ms": offset + dur,
            "chunk_keys": [c.cache_key for c in sec_chunks],
            "chunks": [{"id": t.id, "start_ms": t.start_ms + offset, "end_ms": t.end_ms + offset,
                        "text": t.text, "src_start": t.src_start, "src_end": t.src_end} for t in sa.chunks],
        }
        if cfg.audio.export_sections:
            base = sec_dir / section_slug(sec)
            path = export_audio(sa.audio, asm.sr, base, fmt, cfg.audio.bitrate)
            produced.add(path)
            produced.update(write_subtitles(make_cues(sa.chunks, cfg.subtitles.max_line_chars), base,
                                            cfg.subtitles.formats))
            entry["file"] = path.relative_to(out_dir).as_posix()
            result.section_files[sec.index] = path
            reporter.section_done(sec.index, str(path))
        manifest_sections.append(entry)
        offset += dur
    for f in sec_dir.iterdir():  # 이름이 바뀌었거나 삭제된 섹션의 옛 파일 정리
        if f.is_file() and f not in produced and f.suffix in (".mp3", ".wav", ".srt", ".vtt"):
            f.unlink(missing_ok=True)

    stem = Path(input_path).stem
    merged_ok = built and not missing and not result.failed
    if missing:
        say("info", f"아직 생성되지 않은 섹션 {', '.join(map(str, missing))} — 전체 병합 파일은 모든 섹션 생성 후 만들어집니다.")
    if merged_ok and cfg.audio.export_merged:
        merged = np.concatenate([sa.audio for _, sa, _ in built])
        merged = normalize_loudness(merged, asm.sr, cfg.audio.loudness_lufs)
        base = out_dir / f"{stem}_full"
        result.merged_path = export_audio(merged, asm.sr, base, fmt, cfg.audio.bitrate)
        timings = [t for s in manifest_sections for t in s["chunks"]]
        from .assembler import ChunkTiming
        cues = make_cues([ChunkTiming(t["id"], t["start_ms"], t["end_ms"], t["text"]) for t in timings],
                         cfg.subtitles.max_line_chars)
        write_subtitles(cues, base, cfg.subtitles.formats)
        result.total_duration_ms = offset

    manifest = {
        "schema_version": 1, "app_version": __version__,
        "title": doc.title, "source": str(input_path),
        "engine": engine.name, "voice": cfg.voice, "rate": cfg.engine.rate, "format": fmt,
        "total_duration_ms": offset,
        "merged_file": result.merged_path.relative_to(out_dir).as_posix() if result.merged_path else None,
        "sections": manifest_sections,
    }
    result.manifest_path = out_dir / MANIFEST
    result.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "normalized_script.txt").write_text(normalized_script(doc), encoding="utf-8")


def _cache_any(cfg, c):  # no-cache 모드에서도 이번 실행에서 만든 파일은 사용
    p = TTSCache(cfg.cache_path(), enabled=True)
    return p.get(c.cache_key, c.id)


def normalized_script(doc: LectureDocument) -> str:
    lines = [f"# {doc.title}" if doc.title else ""]
    for sec in doc.sections:
        lines.append(f"\n## [{sec.index}] {sec.label}")
        for para in sec.paragraphs:
            lines.append(" ".join(s.spoken_text + (f" [pause {s.pause_after_ms}ms]" if s.pause_after_ms else "")
                                  for s in para.segments).strip() + "\n")
    return "\n".join(lines).strip() + "\n"


# --- 짧은 텍스트 즉시 합성 (선택 영역 듣기·음성 비교·발음 사전 듣기) ---------------
async def synthesize_text(text: str, cfg: AppConfig, engine: TTSEngine,
                          cancel: CancelToken | None = None) -> tuple[np.ndarray, int]:
    doc = parse_text(text, cfg)
    chunks = plan_chunks(doc, cfg, engine)
    cache = TTSCache(cfg.cache_path())
    synth = Synthesizer(engine, cache, cfg.runtime, cancel=cancel)
    clips, failures = await synth.run(chunks)
    if failures:
        raise failures[0].error
    asm = AudioAssembler(cfg.audio)
    parts = []
    for c in chunks:
        parts.append(load_clip(clips[c.id].path, asm.sr))
        parts.append(asm.silence(min(c.trailing_pause_ms, 2000)))
    audio = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return normalize_loudness(audio, asm.sr, cfg.audio.loudness_lufs), asm.sr
