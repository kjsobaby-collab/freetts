"""CLI 진입점 (Typer). GUI와 같은 core 파이프라인을 사용한다."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from . import __version__, paths
from .config import AppConfig, load_config

app = typer.Typer(help="Lecture Script → English TTS 생성기", no_args_is_help=True, add_completion=False)
cache_app = typer.Typer(help="합성 캐시 관리")
app.add_typer(cache_app, name="cache")
console = Console()
log = logging.getLogger("lecture_tts")


def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    log.setLevel(logging.DEBUG)
    log.handlers = [h for h in log.handlers if not isinstance(h, RichHandler)]
    h = RichHandler(console=console, show_path=False, show_time=False)
    h.setLevel(level)
    log.addHandler(h)


def parse_sections(spec: str | None) -> list[int] | None:
    """'2,5-7' → [2, 5, 6, 7]"""
    if not spec:
        return None
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def _cfg(config: Optional[Path], engine: Optional[str] = None, voice: Optional[str] = None,
         rate: Optional[float] = None, fmt: Optional[str] = None, output: Optional[Path] = None) -> AppConfig:
    over: dict = {}
    if engine:
        over.setdefault("engine", {})["name"] = engine
    if rate:
        over.setdefault("engine", {})["rate"] = rate
    if fmt:
        over.setdefault("audio", {})["format"] = fmt
    if output:
        over.setdefault("runtime", {})["output_dir"] = str(output)
    cfg = load_config(config, over)
    if voice:
        cfg.set_voice(voice)
    return cfg


class RichReporter:
    def __init__(self, progress: Progress):
        self.p = progress
        self.task = None

    def plan_ready(self, total_chunks, total_chars, cached_chunks):
        self.task = self.p.add_task("합성", total=total_chunks)

    def section_started(self, index, total_chunks):
        self.p.update(self.task, description=f"섹션 {index}")

    def chunk_done(self, section, chunk_id, cached, chars, seconds):
        self.p.advance(self.task)

    def section_done(self, index, audio_path): ...

    def message(self, level, text): ...  # pipeline이 이미 로그로 남김

    def error(self, where, message): ...


def _build_one(input_file: Path, cfg: AppConfig, sections, no_cache: bool, engine=None):
    from .pipeline import run_pipeline

    with Progress(TextColumn("[bold]{task.description}"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  TimeRemainingColumn(), console=console) as progress:
        return asyncio.run(run_pipeline(input_file, cfg, sections=sections, reporter=RichReporter(progress),
                                        use_cache=not no_cache, engine=engine))


@app.command()
def build(
    input_file: Path = typer.Argument(..., exists=True, dir_okay=False, help="스크립트 파일 (.md/.txt/.docx/.srt)"),
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="설정 YAML"),
    engine: Optional[str] = typer.Option(None, "--engine", "-e", help="kokoro | piper | azure | fake"),
    voice: Optional[str] = typer.Option(None, "--voice", "-v"),
    rate: Optional[float] = typer.Option(None, "--rate", "-r", help="말하기 속도 (1.0 = 기본)"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f", help="mp3 | wav"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="출력 폴더 (그 아래 스크립트 이름 폴더 생성)"),
    sections: Optional[str] = typer.Option(None, "--sections", "-s", help="예: 2,5-7"),
    no_cache: bool = typer.Option(False, "--no-cache", help="캐시를 무시하고 모두 다시 합성"),
    resume: bool = typer.Option(False, "--resume", help="실패·중지된 빌드 이어서 처리 (캐시 재사용)"),
    verbose: bool = typer.Option(False, "--verbose"),
    quiet: bool = typer.Option(False, "--quiet"),
):
    """스크립트 → 섹션별/전체 오디오 + 자막 + manifest 생성."""
    _setup_logging(verbose, quiet)
    cfg = _cfg(config, engine, voice, rate, fmt, output)
    t0 = time.perf_counter()
    try:
        res = _build_one(input_file, cfg, parse_sections(sections), no_cache and not resume)
    except Exception as e:
        console.print(f"[red]오류:[/red] {escape(str(e))}")
        raise typer.Exit(1)
    console.print(f"[green]완료[/green] ({time.perf_counter() - t0:.1f}s) 합성 {res.synthesized} · 캐시 {res.cached}")
    console.print(f"출력: {res.out_dir}")
    if res.merged_path:
        console.print(f"전체: {res.merged_path}  ({res.total_duration_ms / 1000:.1f}s)")
    if res.failed:
        console.print(f"[yellow]실패 {len(res.failed)}개 — `--resume`으로 다시 실행하세요.[/yellow]")
        raise typer.Exit(2)


@app.command()
def batch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False),
    glob: str = typer.Option("*.md", "--glob"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    engine: Optional[str] = typer.Option(None, "--engine", "-e"),
    voice: Optional[str] = typer.Option(None, "--voice", "-v"),
    fmt: Optional[str] = typer.Option(None, "--format", "-f"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
):
    """폴더 일괄 처리 (엔진 모델은 1회만 로드)."""
    from .engines import create_engine

    _setup_logging(False, False)
    cfg = _cfg(config, engine, voice, None, fmt, output)
    eng = create_engine(cfg)
    files = sorted(folder.glob(glob))
    if not files:
        console.print("처리할 파일이 없습니다.")
        raise typer.Exit(1)
    failed = 0
    for f in files:
        console.rule(str(f.name))
        try:
            _build_one(f, cfg, None, False, engine=eng)
        except Exception as e:
            failed += 1
            console.print(f"[red]{f.name}: {e}[/red]")
    console.print(f"{len(files) - failed}/{len(files)} 완료")


@app.command()
def preview(
    input_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    show: str = typer.Option("normalized", "--show", help="normalized | chunks"),
    estimate_cost: bool = typer.Option(False, "--estimate-cost", help="글자 수·Azure 한도 대비 표시"),
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
    engine: Optional[str] = typer.Option(None, "--engine", "-e"),
):
    """합성 없이 정규화 결과 / 청크 / 예상 사용량 확인 (드라이런)."""
    from .cache import TTSCache
    from .engines import create_engine
    from .pipeline import load_document, normalized_script, plan_chunks

    cfg = _cfg(config, engine)
    doc = load_document(input_file, cfg)
    eng = create_engine(cfg)
    chunks = plan_chunks(doc, cfg, eng)
    for w in doc.warnings:
        console.print(f"[yellow]경고:[/yellow] {escape(w.message)}")
    if show == "chunks":
        cache = TTSCache(cfg.cache_path())
        t = Table("id", "chars", "pause", "cache", "text")
        for c in chunks:
            t.add_row(c.id, str(len(c.text)), str(c.trailing_pause_ms), "✓" if cache.has(c.cache_key) else "",
                      c.text)
        console.print(t)
    else:
        console.print(normalized_script(doc), markup=False, highlight=False)
    if estimate_cost:
        chars = sum(len(c.text) for c in chunks)
        console.print(f"섹션 {len(doc.sections)} · 청크 {len(chunks)} · {chars:,}자 · 예상 길이 약 {chars / 15 / 60:.1f}분")
        from .engines.azure_engine import UsageTracker, build_ssml
        ssml = sum(len(build_ssml(c.text, c.voice, c.rate)) for c in chunks)
        limit = cfg.engines.azure.monthly_char_limit
        used = UsageTracker().used()
        console.print(f"Azure 기준 SSML 포함 {ssml:,}자 — 이번 달 사용 {used:,} / 한도 {limit:,} "
                      f"({(used + ssml) / limit:.0%} 예상)")


@app.command()
def setup(
    engine: str = typer.Argument("kokoro", help="kokoro | piper"),
    voice: Optional[str] = typer.Option(None, "--voice", help="piper 음성 / kokoro는 쉼표로 여러 개"),
):
    """로컬 모델 사전 다운로드 (최초 1회)."""
    _setup_logging(False, False)
    if engine == "kokoro":
        from .engines.kokoro_engine import download_model
        voices = voice.split(",") if voice else None
        download_model(voices=voices, progress=lambda i, n, f: console.print(f"[{i}/{n}] {f}"))
        console.print("[green]Kokoro 모델 준비 완료[/green]")
    elif engine == "piper":
        from .engines.piper_engine import download_voice
        p = download_voice(voice or "en_US-lessac-high")
        console.print(f"[green]Piper 음성 저장: {p}[/green]")
    else:
        console.print("setup 대상: kokoro | piper")
        raise typer.Exit(1)


@app.command()
def voices(engine: str = typer.Option("kokoro", "--engine", "-e")):
    """엔진의 음성 목록."""
    from .engines import create_engine
    eng = create_engine(load_config(), engine)
    for v in eng.list_voices():
        console.print(v)


@app.command()
def audition(
    voices: str = typer.Option("af_heart,af_bella,am_michael,am_fenrir,bf_emma,bm_george", "--voices"),
    rates: str = typer.Option("0.9,1.0", "--rates"),
    text_file: Optional[Path] = typer.Option(None, "--text", help="샘플 단락 파일"),
    output: Path = typer.Option(Path("auditions"), "--output", "-o"),
    engine: Optional[str] = typer.Option(None, "--engine", "-e"),
):
    """후보 음성 × 속도 비교 샘플 생성."""
    from .assembler import export_audio
    from .engines import create_engine
    from .pipeline import synthesize_text
    from .samples import AUDITION_TEXT

    _setup_logging(False, False)
    cfg = _cfg(None, engine)
    text = text_file.read_text(encoding="utf-8") if text_file else AUDITION_TEXT
    eng = create_engine(cfg)
    for v in voices.split(","):
        for r in rates.split(","):
            c = cfg.model_copy(deep=True)
            c.set_voice(v.strip())
            c.engine.rate = float(r)
            try:
                audio, sr = asyncio.run(synthesize_text(text, c, eng))
            except Exception as e:
                console.print(f"[yellow][skip][/yellow] {v} @ {r}: {e}")
                continue
            p = export_audio(audio, sr, output / f"{v.strip()}_{r.strip()}", c.audio.format, c.audio.bitrate)
            console.print(f"[green][ok][/green] {p} ({len(audio) / sr:.1f}s)")


@app.command()
def usage(engine: str = typer.Option("azure", "--engine", "-e")):
    """Azure 무료 티어 이번 달 사용량."""
    from .engines.azure_engine import UsageTracker
    cfg = load_config()
    used, limit = UsageTracker().used(), cfg.engines.azure.monthly_char_limit
    console.print(f"이번 달 사용 {used:,}자 / {limit:,}자 ({used / limit:.1%})")


@app.command()
def gui(script: Optional[Path] = typer.Argument(None)):
    """GUI 앱 실행."""
    from .gui.app import main as gui_main
    sys.exit(gui_main([str(script)] if script else []))


@app.command()
def version():
    console.print(f"lecture-tts {__version__}")


@cache_app.command("clear")
def cache_clear(config: Optional[Path] = typer.Option(None, "--config", "-c")):
    from .cache import TTSCache
    cfg = load_config(config)
    TTSCache(cfg.cache_path()).clear()
    console.print(f"캐시 삭제: {cfg.cache_path()}")


@cache_app.command("info")
def cache_info(config: Optional[Path] = typer.Option(None, "--config", "-c")):
    from .cache import TTSCache
    cfg = load_config(config)
    console.print(f"{cfg.cache_path()} — {TTSCache(cfg.cache_path()).size_bytes() / 1e6:.1f} MB")


def main() -> None:
    paths.setup_runtime_env()
    app()


if __name__ == "__main__":
    main()
