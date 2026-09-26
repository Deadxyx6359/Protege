"""Counting days to and from a date, for chat, which has nothing to count with."""

from __future__ import annotations

from datetime import date

import pytest

from akira.core.context.dates import asks_for_a_span, dates_in, span_lines

TODAY = date(2026, 9, 26)


@pytest.mark.parametrize("message, asks", [
    ("how many days is that from today?", True),
    ("How long until the open day?", True),
    ("weeks left before the MOT", True),
    ("how many weeks since I serviced the car", True),
    ("What day of the week was 1 January 2000?", True),
    ("which day is the open day", True),
    ("when is the open day?", False),
    ("what did the committee decide", False),
])
def test_a_question_about_a_span_is_recognised(message, asks):
    assert asks_for_a_span(message) is asks


def test_dates_are_read_as_written_and_a_time_is_not_a_day():
    found = dates_in("Open day Saturday 10 Oct 11:00; then Oct 20; 2026-05-10; "
                     "Nov 3rd, 2027; 18 Sept 2026; 31 Feb.", TODAY)
    assert found == [("10 Oct", date(2026, 10, 10)), ("Oct 20", date(2026, 10, 20)),
                     ("2026-05-10", date(2026, 5, 10)), ("Nov 3rd, 2027", date(2027, 11, 3)),
                     ("18 Sept 2026", date(2026, 9, 18))]


def test_a_date_without_a_year_is_the_next_one():
    assert dates_in("birthday 3 March", TODAY) == [("3 March", date(2027, 3, 3))]
    assert dates_in("10 October", TODAY) == [("10 October", date(2026, 10, 10))]


def test_the_counts_are_exact_across_month_ends():
    lines = span_lines("how many days until my MOT?",
                       ["MOT due 14 November 2026. Last service 2 February 2026."], TODAY)
    assert "- 14 November 2026 (Saturday 14 November 2026): in 49 days, which is 7 weeks" in lines
    assert "2 February 2026 (Monday 2 February 2026): 236 days ago, which is 33 weeks and 5 days" \
        in lines
    assert span_lines("how long until today, 26 September 2026?", [], TODAY).endswith(": today")


def test_nothing_is_added_unless_a_span_is_asked_for_and_a_date_is_given():
    assert span_lines("when is my MOT?", ["MOT due 14 November 2026."], TODAY) == ""
    assert span_lines("how long until the open day?", ["No date yet."], TODAY) == ""


def test_the_message_comes_first_and_the_count_is_capped():
    notes = [" ".join(f"{day} October" for day in range(1, 20))]
    lines = span_lines("how many days until 30 December?", notes, TODAY).splitlines()
    assert lines[1].startswith("- 30 December")
    assert len(lines) == 1 + 6


def test_days_known_by_name_are_counted_too():
    found = dict((written, day) for written, day in dates_in(
        "Christmas, Christmas Eve, New Year’s Eve, new years day, Valentine's Day, Easter",
        TODAY))
    assert found == {"Christmas": date(2026, 12, 25), "Christmas Eve": date(2026, 12, 24),
                     "New Year’s Eve": date(2026, 12, 31), "new years day": date(2027, 1, 1),
                     "Valentine's Day": date(2027, 2, 14), "Easter": date(2027, 3, 28)}
    assert "in 90 days" in span_lines("How many days until Christmas?", [], TODAY)


@pytest.mark.parametrize("year, easter", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                          (2026, date(2026, 4, 5)), (2038, date(2038, 4, 25))])
def test_easter_is_worked_out(year, easter):
    from akira.core.context.dates import _easter

    assert _easter(year) == easter


def test_clock_times_in_a_message_are_counted_from_now():
    """Told 17:11, the model said a shop shutting at 6pm had shut nine minutes before."""
    from datetime import datetime

    from akira.core.context.dates import clock_lines

    now = datetime(2026, 9, 26, 17, 11)
    lines = clock_lines("Is it too late to phone a shop that shuts at 6pm?", now)
    assert lines.startswith("Clock times in the message, counted from now (17:11)")
    assert "- 6pm (18:00): in 49 minutes" in lines
    lines = clock_lines("between 9:30am and 18:00, or at noon or 5 p.m.", now)
    assert "- 9:30am (09:30): 7 hours 41 minutes ago" in lines
    assert "- 18:00 (18:00): in 49 minutes" in lines and "(12:00)" in lines
    assert "- 5 p.m. (17:00): 11 minutes ago" in lines
    assert lines.count("09:30") == 1, "9:30am was counted twice"
    assert clock_lines("at 12am or 12pm", now).count("\n- ") == 2
    assert clock_lines("no times, a ratio of 3:1, 24:00 or 7:75", now) == ""
