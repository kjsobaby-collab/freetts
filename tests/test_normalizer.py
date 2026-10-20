import pytest

from lecture_tts.normalizer import Normalizer
from lecture_tts.parser import PROTECT_END, PROTECT_START

N = Normalizer(lexicon={"PyTorch": "pie torch", "SQL": "sequel"})


@pytest.mark.parametrize("src, expected", [
    ("3.14", "three point one four"),
    ("the 3rd item", "the third item"),
    ("In 2026, we", "In twenty twenty-six, we"),
    ("1702 words", "one thousand, seven hundred and two words"),
    ("25%", "twenty-five percent"),
    ("$1.5M", "one point five million dollars"),
    ("5–10", "five to ten"),
    ("pages 1-10", "pages one to ten"),
    ("e.g. dropout", "for example, dropout"),
    ("i.e., this", "that is, this"),
    ("apples, etc.", "apples, et cetera."),
    ("the API and GPUs", "the A P I and G P U's"),
    ("x^2", "x squared"),
    ("a ≤ b", "a less than or equal to b"),
    ("approx ≈ 3", "approx approximately three"),
    ("snake_case", "snake case"),
    ("call getValue()", "call get value"),
    ("visit example.com", "visit example dot com"),
    ("World War II", "World War II"),
    ("NASA rocket", "NASA rocket"),
    ("use PyTorch and SQL", "use pie torch and sequel"),
    ("Body ① text", "Body one text"),
    ("18 slides · 1702 words", "eighteen slides, one thousand, seven hundred and two words"),
    ("the 1990s", "the nineteen nineties"),
    ("at 10:30", "at ten thirty"),
])
def test_rules(src, expected):
    assert N.normalize(src) == expected


def test_protected_override_not_normalized():
    text = f"We use {PROTECT_START}R-E-L-U 2{PROTECT_END} here"
    assert N.normalize(text) == "We use R-E-L-U 2 here"


def test_all_caps_heading_not_spelled():
    assert N.normalize("WELCOME TO THE COURSE") == "WELCOME TO THE COURSE"
