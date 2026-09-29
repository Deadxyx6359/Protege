"""Amounts asked for in another unit are converted for the model, not left to it."""

from __future__ import annotations

import pytest

from akira.core.context.units import unit_lines


@pytest.mark.parametrize("message, line", [
    # The model wrote (°F - 32) × 9/5 and said 72°F is 72°C.
    ("Convert 72°F to Celsius.", "- 72°F = 22.22°C ((72 - 32) × 5/9)"),
    ("What is 20 C in Fahrenheit?", "- 20°C = 68°F (20 × 9/5 + 32)"),
    ("convert -40 F to C", "- -40°F = -40°C"),
    ("what is 100 degrees fahrenheit in celsius", "- 100°F = 37.78°C"),
    ("how many miles is 10 km", "- 10 km = 6.21 mi"),
    ("Convert 5 miles to kilometres", "- 5 mi = 8.05 km"),
    ("what is 150 lbs in kg", "- 150 lb = 68.04 kg"),
    ("I weigh 70 kg, what is that in pounds?", "- 70 kg = 154.32 lb"),
    ("I am 11 stone, what is that in kg", "- 11 st = 69.85 kg"),
    ("how many feet is 3 metres", "- 3 m = 9.84 ft"),
    ("6 ft in cm?", "- 6 ft = 182.88 cm (6 × 30.48)"),
    ("convert 12 inches to cm", "- 12 in = 30.48 cm (12 × 2.54)"),
    ("what is 350 g in ounces", "- 350 g = 12.35 oz"),
])
def test_an_amount_asked_for_in_another_unit_is_converted(message, line):
    lines = unit_lines(message)
    assert lines.startswith("Amounts in the message, converted (use these, do not work them "
                            "out again):")
    assert line in lines


@pytest.mark.parametrize("message", [
    "I ran 5 km today",           # no other unit asked for
    "It costs 5 pounds",
    "What is £20 in kg?",         # money, not weight
    "Is 72°F hot?",
    "the meeting is at 5 in room 3",
    "plan B, 3 F to go",
    "",
])
def test_nothing_is_added_unless_another_unit_is_asked_for(message):
    assert unit_lines(message) == ""
