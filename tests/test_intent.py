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
    ("What is the capital of Australia?", Intent.EVERYDAY),
    ("Can you help me write a birthday card for my sister?", Intent.EVERYDAY),
    ("In 2026 I want to plant more beans.", Intent.EVERYDAY),
    ("Is it too late to phone a shop that shuts at 6pm?", Intent.EVERYDAY),
    ("Compare these two recipes for me", Intent.EVERYDAY),
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
