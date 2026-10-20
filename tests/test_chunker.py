from lecture_tts.chunker import Chunker, split_long
from lecture_tts.pipeline import parse_text


def chunks_for(text, cfg, max_chars=400):
    return Chunker(cfg, max_chars).split(parse_text(text, cfg))


def test_section_boundary_always_splits(cfg):
    cs = chunks_for("## Slide 1: A\nShort.\n\n## Slide 2: B\nAlso short.", cfg)
    assert [c.section_index for c in cs] == [1, 2]


def test_short_sentences_merged(cfg):
    cs = chunks_for("Hi. Yes. This is a longer sentence that stands alone.", cfg)
    assert len(cs) == 1


def test_pause_splits_and_records_trailing(cfg):
    cs = chunks_for("Hello there everyone, welcome. [pause 2s] And now the next one.", cfg)
    assert len(cs) == 2 and cs[0].trailing_pause_ms == 2000


def test_paragraph_pause(cfg):
    cs = chunks_for("First paragraph is right here and long enough.\n\nSecond paragraph is here.", cfg)
    assert cs[0].trailing_pause_ms == cfg.audio.paragraph_pause_ms
    assert cs[-1].trailing_pause_ms == 0


def test_max_chars_respected(cfg):
    long = ", ".join(["this is a clause"] * 40) + "."
    cs = chunks_for(long, cfg, max_chars=100)
    assert len(cs) > 1 and all(len(c.text) <= 100 for c in cs)


def test_split_long_words():
    parts = split_long("word " * 100, 50)
    assert all(len(p) <= 50 for p in parts)


def test_speaker_voice_and_rate(cfg):
    cfg.engine.name = "kokoro"
    cs = chunks_for("Teacher talks here for a while. [speaker: student] Student asks something?", cfg)
    assert cs[0].voice == "af_heart"
    assert cs[1].voice == "am_michael" and cs[1].rate == 1.05
