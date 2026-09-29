"""LaTeX maths in a reply, shown as plain text; prices and code left as they are."""

from __future__ import annotations

import pytest

from akira.core.plain_maths import plain_maths


@pytest.mark.parametrize("written, shown", [
    # As the chat model wrote them, asked to solve x^2 - 5x + 6 = 0 and the bat and ball.
    ("To solve $ x^2 - 5x + 6 = 0 $, factor:", "To solve x^2 - 5x + 6 = 0, factor:"),
    ("   $ (x - 2)(x - 3) = 0 $", "   (x - 2)(x - 3) = 0"),
    ("Let the cost of the ball be $ x $.", "Let the cost of the ball be x."),
    ("Simplify: $ 2x + 1.00 = 1.10 $.", "Simplify: 2x + 1.00 = 1.10."),
    (r"\( \frac{200}{9} \approx 22.22 \)", "200/9 ≈ 22.22"),
    (r"$$x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$$", "x = (-b ± √(b^2-4ac))/(2a)"),
    (r"\[ 40 \times \frac{5}{9} \]", "40 × 5/9"),
    (r"$x^{2}$ and $T = 100^\circ C$", "x^2 and T = 100° C"),
])
def test_maths_is_shown_plainly(written, shown):
    assert plain_maths(written) == shown


@pytest.mark.parametrize("text", [
    "The ball costs $0.05 and the bat $1.05.",
    "It costs $5 and $10 each.",
    "between $3 and $4 a pound",
    "Use `$HOME` and `\\frac` in code.",
    "```\nprice = \"$ x $\"\nprint(r'\\frac')\n```",
    "Plain words with no maths at all.",
])
def test_prices_code_and_words_are_left_alone(text):
    assert plain_maths(text) == text
