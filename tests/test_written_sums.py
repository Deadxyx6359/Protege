"""Sums written out in an agent's answer are checked, not trusted."""

from __future__ import annotations

import pytest

from akira.core.tools.builtin.maths import wrong_sums


def test_a_wrong_total_is_found_with_its_right_answer():
    """A gatherer that had read the spreadsheet added it up to £70.7; it is £81.1."""
    text = ("spent £12.5 (Seed potatoes) + £6.8 (Onion sets) + £30.0 (Manure) + "
            "£22.4 (Netting) + £9.4 (Canes) = £70.7. Then")
    [(written, right)] = wrong_sums(text)
    assert written.endswith("= £70.7") and right == "81.1"


@pytest.mark.parametrize("text", [
    "0.17 × 46.80 = 7.956, so 46.80 + 7.96 = 54.76 and 54.76 / 3 = 18.25",
    "180 × 9/5 + 32 = 356",
    "10 / 3 = 3.33, or about 3",
    "1,200 + 300 = 1,500 and 3 x 4 = 12",
    "£120 - £81.1 = £38.9",
    "17% of 240 = 40.8",  # not an expression it can read, so not judged
    "on 2026-09-26 = today",
])
def test_right_or_rounded_sums_and_other_text_are_left_alone(text):
    assert wrong_sums(text) == []


def test_each_wrong_sum_is_reported():
    assert wrong_sums("2 + 2 = 5, 3 × 4 = 12, 7 - 2 = 4") == [("2 + 2 = 5", "4"),
                                                               ("7 - 2 = 4", "5")]


def test_the_end_of_a_longer_sum_is_not_taken_for_the_whole():
    # "(72 - 32) × 5/9 = 22.2" was corrected as "5/9 = 22.2 is wrong; it comes to 0.56".
    assert wrong_sums("(72 - 32) × 5/9 = 22.2°C") == []
    assert wrong_sums("so 2 + 3 × 4 = 99") == [("2 + 3 × 4 = 99", "14")]


def test_a_step_whose_result_is_a_fraction_is_not_corrected():
    # "40 × 5/9 = 200/9" was corrected to 22.22 as if it claimed 200: it was right.
    assert wrong_sums("40 × 5/9 = 200/9 ≈ 22.22") == []
    assert wrong_sums("so 3 × 4 = 12 / 2 = 6") == []
    assert wrong_sums("40 × 5/9 = 23") == [("40 × 5/9 = 23", "22.22")]
