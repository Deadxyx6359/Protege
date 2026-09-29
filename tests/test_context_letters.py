"""Letters in a word are counted for the model, not left to it."""

from __future__ import annotations

import pytest

from akira.core.context.letters import letter_lines


@pytest.mark.parametrize("message, line", [
    # The small model spelled p-o-s-s-e-s-s-i-o-n and then said three.
    ("How many letter s's are in the word possession?", "“possession” has 4 of the letter s"),
    ("how many r's in strawberry", "“strawberry” has 3 of the letter r"),
    ("how many s in possession", "“possession” has 4 of the letter s"),
    ("How many a's are there in banana?", "“banana” has 3 of the letter a"),
    ('How many times does the letter e appear in "excellence"?',
     "“excellence” has 4 of the letter e"),
    ("count the r's in strawberry", "“strawberry” has 3 of the letter r"),
    ("How many letters are in possession?", "“possession” has 10 letters"),
    ("how many letters does mississippi have", "“mississippi” has 11 letters"),
])
def test_a_letter_asked_about_is_counted(message, line):
    lines = letter_lines(message)
    assert lines.startswith("Letters counted in the message (use these, do not count again):")
    assert line in lines


def test_the_word_is_spelt_out_with_the_count():
    assert "p-o-s-s-e-s-s-i-o-n" in letter_lines("how many s's in possession?")


@pytest.mark.parametrize("message", [
    "How many people are in the room?",
    "How many days until Christmas?",
    "How many letters should I send?",
    "",
])
def test_other_questions_add_nothing(message):
    assert letter_lines(message) == ""
