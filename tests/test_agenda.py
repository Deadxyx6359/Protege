"""The calendar in the chat: what is on is read for the model, and an event is added on a yes."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from akira.core import agenda
from akira.core.permissions import Policy
from akira.core.planner import PlannerStore, draft

NOW = datetime(2026, 9, 30, 10, 0)          # a Wednesday
TODAY = NOW.date()


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


# -- asked to add ------------------------------------------------------------------------------------


@pytest.mark.parametrize("text, title, start, end", [
    ("Add dentist to my calendar on Friday at 3pm", "Dentist",
     datetime(2026, 10, 2, 15, 0), datetime(2026, 10, 2, 16, 0)),
    ("put lunch with Sam in my calendar for tomorrow at 12:30", "Lunch with Sam",
     datetime(2026, 10, 1, 12, 30), datetime(2026, 10, 1, 13, 30)),
    # A day with no time is all day.
    ("Can you add Mum's birthday to the calendar on 5 October", "Mum's birthday",
     date(2026, 10, 5), None),
    ("add flight to my calendar on Friday all day", "Flight", date(2026, 10, 2), None),
    ("add an event: team meeting Monday 9:30-11", "Team meeting",
     datetime(2026, 10, 5, 9, 30), datetime(2026, 10, 5, 11, 0)),
    # "3 to 4pm" is three in the afternoon.
    ("Add a calendar event for the plumber tomorrow from 3 to 4pm", "The plumber",
     datetime(2026, 10, 1, 15, 0), datetime(2026, 10, 1, 16, 0)),
    ("please put the MOT in my diary on 14 November at 8:30am for 2 hours", "The MOT",
     datetime(2026, 11, 14, 8, 30), datetime(2026, 11, 14, 10, 30)),
    # "at 6" with no day: today, in the evening.
    ("add gym to my calendar at 6", "Gym",
     datetime(2026, 9, 30, 18, 0), datetime(2026, 9, 30, 19, 0)),
    # The date was once read as a span of times, 10 to 13.
    ("new event parents evening 2026-10-13 18:00 to 19:30", "Parents evening",
     datetime(2026, 10, 13, 18, 0), datetime(2026, 10, 13, 19, 30)),
    ("schedule a call with Alex in my calendar next Tuesday at 2pm", "A call with Alex",
     datetime(2026, 10, 6, 14, 0), datetime(2026, 10, 6, 15, 0)),
    ("add holiday to my calendar", "Holiday", None, None),
])
def test_what_and_when_are_read_as_said(text, title, start, end):
    assert agenda.asks_to_add(text)
    assert agenda.read(text, NOW) == agenda.Asked(title, start, end)


@pytest.mark.parametrize("text", [
    "Add a calendar widget to my website",
    "what's in my calendar today",
    "how do I add a calendar to Outlook?",
    "remind me to call mum at 5",
    "Add 2 and 2",
])
def test_only_a_request_for_an_event_is_one(text):
    assert not agenda.asks_to_add(text)


def test_the_offer_says_the_whole_of_it():
    asked = agenda.read("Add dentist to my calendar on Friday at 3pm", NOW)
    assert agenda.offer(asked) == ("Add to your calendar: Dentist, Fri 2 Oct 2026, 15:00 to "
                                   "16:00? Say yes to add it, or no.")


# -- asked what is on --------------------------------------------------------------------------------


@pytest.mark.parametrize("message, first, last", [
    ("What's on my calendar this week?", date(2026, 9, 30), date(2026, 10, 6)),
    ("Am I free on Friday?", date(2026, 10, 2), date(2026, 10, 2)),
    ("what do I have on tomorrow", date(2026, 10, 1), date(2026, 10, 1)),
    ("Do I have anything this weekend?", date(2026, 10, 3), date(2026, 10, 4)),
    ("What's on next month?", date(2026, 10, 1), date(2026, 10, 31)),
    ("what is on 5 October", date(2026, 10, 5), date(2026, 10, 5)),
    ("do I have any meetings next week", date(2026, 10, 5), date(2026, 10, 11)),
    ("What's my schedule today?", TODAY, TODAY),
    # Looking for one thing: further ahead.
    ("When is my dentist appointment?", TODAY, date(2026, 11, 30)),
    ("What's in my diary?", TODAY, date(2026, 10, 13)),
    # Asked in the app and not read as about the calendar at all.
    ("what do i have going on tomorrow?", date(2026, 10, 1), date(2026, 10, 1)),
    ("look at my calander", TODAY, date(2026, 10, 13)),
    ("check my calender", TODAY, date(2026, 10, 13)),
    ("What am I doing on Friday?", date(2026, 10, 2), date(2026, 10, 2)),
    ("what's happening tomorrow?", date(2026, 10, 1), date(2026, 10, 1)),
    ("What does my week look like?", TODAY, date(2026, 10, 6)),
    ("what does my day look like", TODAY, TODAY),
    ("is there anything on tomorrow?", date(2026, 10, 1), date(2026, 10, 1)),
    ("whats on my schedual today", TODAY, TODAY),
])
def test_the_days_asked_about(message, first, last):
    assert agenda.asks_what_is_on(message)
    assert agenda.days_asked(message, TODAY) == (first, last)


@pytest.mark.parametrize("message", [
    "What's the capital of France?",
    "what's on TV tonight?",
    "what's happening in Ukraine",
    "show me the scheduled jobs",
    "Add dentist to my calendar on Friday at 3pm",
    "What do I have to do to fix this bug?",
    "what is going on with my code",
    "what am I doing wrong",
])
def test_other_questions_are_not_about_the_calendar(message):
    assert not agenda.asks_what_is_on(message)


def reads():
    policy = Policy()
    policy.grant("planner.read")
    return policy


def test_the_model_is_given_the_calendar_for_those_days(tmp_path):
    store = PlannerStore(tmp_path / "calendar.json")
    store.add(draft("Dentist", "2026-10-02T15:00", where="Leeds"))
    store.add(draft("Bins", "2026-09-28", repeat="weekly"))
    store.add(draft("Far off", "2027-01-01"))
    lines = agenda.agenda_lines("What's on my calendar this week?", reads(), today=TODAY,
                                store=store)
    assert lines.startswith("The person's calendar, kept in Akira, from Wednesday 30 September "
                            "to Tuesday 6 October 2026. This is all of it for those days")
    assert "- Fri 2 Oct, 15:00 to 16:00: Dentist, at Leeds" in lines
    assert "- Mon 5 Oct, all day: Bins (repeats every week)" in lines and "Far off" not in lines


def test_an_empty_day_is_said_to_be_empty_and_other_messages_add_nothing(tmp_path):
    store = PlannerStore(tmp_path / "calendar.json")
    lines = agenda.agenda_lines("Am I free on Friday?", reads(), today=TODAY, store=store)
    assert "nothing is in it on Friday 2 October 2026" in lines and "do not invent" in lines
    assert agenda.agenda_lines("What is the capital of France?", reads(), today=TODAY,
                               store=store) == ""


def test_without_the_permission_the_calendar_is_not_read_and_the_model_is_told(tmp_path):
    store = PlannerStore(tmp_path / "calendar.json")
    store.add(draft("Dentist", "2026-10-02T15:00"))
    lines = agenda.agenda_lines("What's on my calendar this week?", Policy(), today=TODAY,
                                store=store)
    assert "was not read" in lines and "Dentist" not in lines and "do not guess" in lines


# -- in the chat ---------------------------------------------------------------------------------------


@pytest.fixture
def chat(tmp_path):
    from PySide6.QtCore import QCoreApplication
    QCoreApplication.instance() or QCoreApplication([])
    from akira.core.config import AppConfig
    from akira.core.conversations import ConversationStore
    from akira.core.models import ModelRouter
    from akira.ui.bridge import ChatBridge

    store = PlannerStore(tmp_path / "calendar.json")
    config = AppConfig(models={})
    bridge = ChatBridge(ModelRouter(config), config, ConversationStore(tmp_path / "chats"),
                        remind=lambda what, at: "", notices=lambda: True, calendar=store)
    return bridge, store


def last(bridge):
    model = bridge.messages
    return model.data(model.index(model.rowCount() - 1, 0), model.TextRole)


def test_an_event_is_offered_and_added_only_on_yes(chat):
    """Asked to add one, a model said "Added" with nothing added."""
    bridge, store = chat
    bridge.send("Add lunch with Sam to my calendar on 5 October 2027 at 12:30")
    assert last(bridge) == ("Add to your calendar: Lunch with Sam, Tue 5 Oct 2027, 12:30 to "
                            "13:30? Say yes to add it, or no.")
    assert store.events() == []
    bridge.send("yes")
    assert last(bridge) == "Added to your calendar: Lunch with Sam, Tue 5 Oct 2027, 12:30 to 13:30."
    (event,) = store.events()
    assert (event.title, event.start) == ("Lunch with Sam", datetime(2027, 10, 5, 12, 30))


def test_no_adds_nothing_and_a_later_yes_is_not_taken_for_it(chat):
    bridge, store = chat
    bridge.send("Add dentist to my calendar on 5 October 2027 at 3pm")
    bridge.send("no")
    assert last(bridge) == "All right, nothing added."
    bridge.send("yes")
    assert store.events() == []


def test_with_no_day_it_asks_when_and_takes_the_answer(chat):
    bridge, store = chat
    bridge.send("add holiday to my calendar")
    assert last(bridge).startswith("When is it, Holiday?")
    bridge.send("5 October 2027")
    assert last(bridge) == ("Add to your calendar: Holiday, Tue 5 Oct 2027, all day? "
                            "Say yes to add it, or no.")
    bridge.send("yes please")
    assert [e.title for e in store.events()] == ["Holiday"]


def test_a_reminder_asked_for_meanwhile_is_not_mistaken_for_the_event(chat):
    bridge, store = chat
    bridge.send("Add dentist to my calendar on 5 October 2027 at 3pm")
    bridge.send("remind me to call mum tomorrow at 9")
    bridge.send("yes")
    assert last(bridge).startswith("Done. I'll remind you")
    bridge.send("yes")
    assert store.events() == []
