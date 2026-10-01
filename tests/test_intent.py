"""Sorting a message as everyday, code or research, and so choosing its model."""

from __future__ import annotations

import pytest

from akira.core.intent import MODES, Intent, choose
from akira.core.models import Route


@pytest.mark.parametrize("text, intent", [
    ("Write a Python function that reverses a string.", Intent.CODE),
    ("Why does my code throw KeyError: name?", Intent.CODE),
    ("Fix the bug in parser.py", Intent.CODE),
    ("```\nprint(1)\n```\nwhat does this print?", Intent.CODE),
    ("Look up the latest version of Python", Intent.RESEARCH),
    ("How did the JWST launch compare with Hubble? Check Wikipedia.", Intent.RESEARCH),
    ("What do my notes say about the committee meeting?", Intent.RESEARCH),
    ("How much have I spent according to budget.xlsx?", Intent.RESEARCH),
    ("Who won the 2026 World Cup?", Intent.RESEARCH),
    ("Search the web for tomato blight treatments", Intent.RESEARCH),
    ("What's the news today?", Intent.RESEARCH),
    ("What are the pros and cons of heat pumps? Find sources.", Intent.RESEARCH),
    # Facts that change, or that a local model will not have.
    ("How much does a Raspberry Pi 5 cost?", Intent.RESEARCH),
    ("What are the opening hours of the Louvre?", Intent.RESEARCH),
    ("Who is the current prime minister of Japan?", Intent.RESEARCH),
    ("When does the new Zelda come out?", Intent.RESEARCH),
    ("What is the weather like today?", Intent.EVERYDAY),  # the person's own, in context
    # The forecast is read from Open-Meteo into the context: searched for, it was not found.
    ("What is the weather in Paris?", Intent.EVERYDAY),
    ("What's the weather in Leeds tomorrow?", Intent.EVERYDAY),
    # When a place opens: answered from memory, the Louvre was "closed on Saturdays".
    ("What time does the Louvre open on Saturdays?", Intent.RESEARCH),
    ("Is the post office open on Sunday?", Intent.RESEARCH),
    # But not the person's own, which a search would send away.
    ("Is my dentist open on Friday?", Intent.EVERYDAY),
    ("What time is it?", Intent.EVERYDAY),
    # With the whole web to search, it said it could not search for videos.
    ("Find me a YouTube video about sourdough starters.", Intent.RESEARCH),
    ("Find me the bug in this code", Intent.CODE),
    # A page given is read: chat said it "cannot access external links".
    ("Read https://en.wikipedia.org/wiki/Alan_Turing and tell me where he was born.",
     Intent.RESEARCH),
    ("Summarise https://example.org/news/today.html", Intent.RESEARCH),
    ("Why does main.py fail? Traceback (most recent call last): see https://x.org/a",
     Intent.CODE),
    ("Write a function to compute the price of items", Intent.CODE),
    ("What is the capital of Australia?", Intent.EVERYDAY),
    ("Can you help me write a birthday card for my sister?", Intent.EVERYDAY),
    ("In 2026 I want to plant more beans.", Intent.EVERYDAY),
    ("Is it too late to phone a shop that shuts at 6pm?", Intent.EVERYDAY),
    ("Compare these two recipes for me", Intent.EVERYDAY),
    # Found by asking the real models: none of these is a search.
    ("What's on my screen right now?", Intent.EVERYDAY),
    ("How many days are there between March 3 and April 17, 2026?", Intent.EVERYDAY),
    ("A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. "
     "How much does the ball cost?", Intent.EVERYDAY),
    # And these still are.
    ("What's the price of bitcoin right now?", Intent.RESEARCH),
    ("Who is winning the election currently?", Intent.RESEARCH),
])
def test_a_message_is_sorted_by_what_it_asks(text, intent):
    assert choose(text).intent is intent


def test_each_kind_is_answered_on_its_own_model():
    assert choose("hello").route is Route.CHAT
    assert choose("fix this regex").route is Route.CODE
    # The strongest there is: the chat model unless a larger one is set up.
    assert choose("look it up online").route is Route.DEEP


@pytest.mark.parametrize("text, previous, intent", [
    ("and in Rust?", Intent.CODE, Intent.CODE),
    ("now make it ignore case", Intent.CODE, Intent.CODE),
    ("what about Webb?", Intent.RESEARCH, Intent.RESEARCH),
    # Not a question: the last answer is reworked, nothing is looked up again.
    ("Please make it shorter.", Intent.RESEARCH, Intent.EVERYDAY),
    ("Thanks!", Intent.RESEARCH, Intent.EVERYDAY),
    ("ok", Intent.CODE, Intent.EVERYDAY),
    ("x" * 200, Intent.CODE, Intent.EVERYDAY),
    ("What should I cook tonight?", Intent.CODE, Intent.EVERYDAY),
])
def test_a_short_follow_up_keeps_the_kind_before_it(text, previous, intent):
    assert choose(text, previous=previous).intent is intent


def test_a_kind_the_person_pinned_is_taken_as_it_is():
    assert MODES == ("auto", "everyday", "code", "research")
    pinned = choose("hello there", mode="research")
    assert pinned.intent is Intent.RESEARCH and pinned.why == "chosen"
    assert choose("fix this regex", mode="everyday").route is Route.CHAT
    assert choose("fix this regex", mode="nonsense").intent is Intent.CODE
