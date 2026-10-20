from lecture_tts.config import ParsingConfig
from lecture_tts.parser import Parser, split_sentences


def parse(text, **kw):
    return Parser(ParsingConfig(**kw)).parse(text)


def test_markdown_slides_and_title():
    doc = parse("# Lecture 3\n\n## Slide 1: Welcome\nHello.\n\n## Slide 2: Intro\nWorld.\n")
    assert doc.title == "Lecture 3"
    assert [s.title for s in doc.sections] == ["Welcome", "Intro"]
    assert [s.number for s in doc.sections] == ["1", "2"]


def test_bracket_and_plain_slide_markers():
    doc = parse("[SLIDE 1] Start\nA.\n[SLIDE 2]\nB.\n")
    assert len(doc.sections) == 2
    doc = parse("Course header line\nSlide 1. Title: Hello\nText one.\nSlide 2. Next\nText two.\n")
    assert [s.title for s in doc.sections] == ["Title: Hello", "Next"]
    assert doc.title == "Course header line"  # 첫 마커 이전 줄은 제목으로만 사용, 읽지 않음


def test_no_markers_single_section():
    doc = parse("Just one paragraph. Two sentences.")
    assert len(doc.sections) == 1
    assert len(doc.sections[0].paragraphs[0].segments) == 2


def test_comment_removed_and_offsets_preserved():
    text = "## Slide 1: A\n<!-- secret -->Hello there.\n"
    doc = parse(text)
    seg = doc.sections[0].paragraphs[0].segments[0]
    assert seg.display_text == "Hello there."
    assert text[seg.src_start:seg.src_end] == "Hello there."


def test_pause_override_emphasis():
    doc = parse("Hello. [pause 1s] We use {ReLU|R-E-L-U} and *this*. [pause 250ms] Bye. [pause]")
    segs = doc.sections[0].paragraphs[0].segments
    assert segs[0].pause_after_ms == 1000
    assert segs[1].display_text == "We use ReLU and this."
    assert "R-E-L-U" in segs[1].spoken_text
    assert segs[1].pause_after_ms == 250
    assert segs[2].pause_after_ms == 1000  # [pause] 기본 길이


def test_speaker_and_rate_split_paragraphs():
    doc = parse("Hi. [speaker: student] Question? [rate 0.8] Slow answer.")
    paras = doc.sections[0].paragraphs
    assert [(p.speaker, p.rate) for p in paras] == [("default", 1.0), ("student", 1.0), ("student", 0.8)]


def test_invalid_directive_warns_and_is_dropped():
    doc = parse("Hello [pause abc] world.")
    assert doc.warnings and "잘못된 지시어" in doc.warnings[0].message
    assert "pause" not in doc.sections[0].paragraphs[0].segments[0].display_text


def test_sentence_split_respects_abbreviations():
    text = "We use e.g. dropout. Dr. Kim agrees. Values like 3.14 matter! Next one?"
    parts = [text[s:e] for s, e in split_sentences(text)]
    assert parts == ["We use e.g. dropout.", "Dr. Kim agrees.", "Values like 3.14 matter!", "Next one?"]
