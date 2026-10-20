import json

import soundfile as sf

from lecture_tts.cache import TTSCache
from lecture_tts.engines.fake_engine import FakeEngine
from lecture_tts.pipeline import (diff_sections, load_document, output_dir_for, plan_chunks, read_manifest,
                                  run_pipeline)
from lecture_tts.progress import CancelToken, ProgressReporter


async def test_full_build_outputs(cfg, sample_md):
    res = await run_pipeline(sample_md, cfg)
    out = res.out_dir
    assert res.merged_path and res.merged_path.exists()
    assert (out / "lec 강의_full.srt").exists() and (out / "lec 강의_full.vtt").exists()
    assert len(list((out / "sections").glob("*.wav"))) == 2
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert m["engine"] == "fake" and len(m["sections"]) == 2
    # 타임라인 정합성: 청크는 겹치지 않고 증가, 전체 길이 = 파일 길이
    times = [(c["start_ms"], c["end_ms"]) for s in m["sections"] for c in s["chunks"]]
    assert all(a < b for a, b in times)
    assert all(times[i][1] <= times[i + 1][0] for i in range(len(times) - 1))
    info = sf.info(str(res.merged_path))
    assert abs(info.duration * 1000 - m["total_duration_ms"]) < 5
    assert m["sections"][0]["chunks"][0]["text"] == "Hello everyone, and welcome to lecture three."
    assert "R-E-L-U" in (out / "normalized_script.txt").read_text(encoding="utf-8")


async def test_incremental_rebuild_only_changed(cfg, sample_md):
    eng = FakeEngine(cfg)
    await run_pipeline(sample_md, cfg, engine=eng)
    first_calls = len(eng.calls)
    text = sample_md.read_text(encoding="utf-8").replace("weighted sum", "weighted total")
    sample_md.write_text(text, encoding="utf-8")
    eng.calls.clear()
    res = await run_pipeline(sample_md, cfg, engine=eng)
    assert len(eng.calls) == 1 and first_calls > 1
    assert res.cached == first_calls - 1


async def test_section_status_and_partial_build(cfg, sample_md):
    eng = FakeEngine(cfg)
    res = await run_pipeline(sample_md, cfg, engine=eng, sections=[2])
    assert res.merged_path is None and 2 in res.section_files and 1 not in res.section_files
    out = output_dir_for(sample_md, cfg)
    doc = load_document(sample_md, cfg)
    chunks = plan_chunks(doc, cfg, eng)
    st = diff_sections(doc, chunks, read_manifest(out), TTSCache(cfg.cache_path()), out)
    assert st == {1: "new", 2: "done"}
    res = await run_pipeline(sample_md, cfg, engine=eng, sections=[1])
    assert res.merged_path is not None


async def test_cancel_keeps_cache(cfg, sample_md):
    token = CancelToken()

    class StopAfterFirst(ProgressReporter):
        def chunk_done(self, *a):
            token.cancel()

    res = await run_pipeline(sample_md, cfg, reporter=StopAfterFirst(), cancel=token)
    assert res.cancelled and res.synthesized >= 1
    res2 = await run_pipeline(sample_md, cfg)
    assert res2.cached >= 1 and res2.merged_path


async def test_mp3_export_if_ffmpeg(cfg, sample_md):
    from lecture_tts import paths
    if not paths.find_ffmpeg():
        return
    cfg.audio.format = "mp3"
    res = await run_pipeline(sample_md, cfg)
    assert res.merged_path.suffix == ".mp3" and res.merged_path.stat().st_size > 1000
