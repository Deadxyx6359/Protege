"""Akira by the clock: what happens when its windows close, and when it quits.

The windows, the icon by the clock, the model router and the rest are fakes;
`test_qml_background.py` closes the real window, and `test_processes.py` and
`test_quiet.py` test what keeps Akira out of a game's way.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal  # noqa: E402

from akira.core.config import AppConfig  # noqa: E402
from akira.ui.background import BackgroundBridge  # noqa: E402


@pytest.fixture
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


class FakeWindow(QObject):
    visibleChanged = Signal(bool)

    def __init__(self, visible=True):
        super().__init__()
        self._visible, self.raised, self.states = visible, 0, Qt.WindowState.WindowNoState

    def isVisible(self):
        return self._visible

    def show(self):
        self._visible = True
        self.visibleChanged.emit(True)

    def hide(self):
        self._visible = False
        self.visibleChanged.emit(False)

    def windowStates(self):
        return self.states

    def setWindowStates(self, states):
        self.states = states

    def raise_(self):
        self.raised += 1

    def requestActivate(self):
        pass


class FakeRouter:
    def __init__(self):
        self.loaded, self.generating, self.lent = True, False, ""
        self.unloads, self.warmed = 0, []

    def unload_all(self, timeout=30.0):
        self.unloads += 1
        self.loaded = False
        return True

    def warm(self, route):
        self.warmed.append(route)
        self.loaded = True
        return True


class FakeChat(QObject):
    busyChanged = Signal()

    def __init__(self):
        super().__init__()
        self.busy = False


class FakeTray:
    def __init__(self):
        self.messages, self.hidden = [], False

    def showMessage(self, title, text, icon, msecs):
        self.messages.append((title, text))

    def hide(self):
        self.hidden = True


class FakeCard:
    def __init__(self, why=""):
        self.why, self.forgotten = why, 0

    def busy(self):
        return self.why

    def forget(self):
        self.forgotten += 1


class Requests(QObject):
    noticed = Signal(str, str)
    requested = Signal(str, str)
    asked = Signal(str, "QVariantMap")
    criticalFound = Signal(int)


class FakeApp:
    def __init__(self):
        self.quit_on_last = True

    def setQuitOnLastWindowClosed(self, on):
        self.quit_on_last = on


def background(app, *, tray=True, keep_running=True, card="", **parts):
    config = AppConfig(keep_running=keep_running)
    router, chat = FakeRouter(), FakeChat()
    voice = types.SimpleNamespace(released=0)
    voice.release = lambda: setattr(voice, "released", voice.released + 1)
    scheduler = types.SimpleNamespace(busy=False, wake=threading.Event())
    priorities, exits = [], []
    bridge = BackgroundBridge(config, router, voice=voice, chat=chat, scheduler=scheduler,
                              persist=False, card=FakeCard(card), priority=priorities.append,
                              leave=exits.append)
    window, call = FakeWindow(), FakeWindow(visible=False)
    requests = Requests()
    fake_app, fake_tray = FakeApp(), FakeTray() if tray else None
    instance = types.SimpleNamespace(released=False, listen=lambda on_called: None)
    instance.release = lambda: setattr(instance, "released", True)
    bridge.attach(fake_app, window, call_window=call, instance=instance, tray=fake_tray,
                  monitor=requests, confirm=requests, schedule=requests)
    return types.SimpleNamespace(bridge=bridge, config=config, router=router, chat=chat,
                                 voice=voice, scheduler=scheduler, priorities=priorities,
                                 window=window, call=call, requests=requests, app=fake_app,
                                 tray=fake_tray, instance=instance, exits=exits)


def test_closing_hides_the_window_when_akira_keeps_running(app):
    akira = background(app)
    assert akira.bridge.hidesOnClose
    assert not akira.app.quit_on_last, "a menu from the icon closing must not quit Akira"


def test_without_the_setting_or_an_icon_to_come_back_from_closing_quits(app):
    assert not background(app, keep_running=False).bridge.hidesOnClose
    off = background(app, tray=False)
    assert not off.bridge.hidesOnClose and off.app.quit_on_last


def test_the_setting_can_be_turned_off_and_on(app):
    akira = background(app)
    akira.bridge.keepRunning = False
    assert not akira.config.keep_running and not akira.bridge.hidesOnClose
    assert akira.app.quit_on_last
    akira.bridge.keepRunning = True
    assert akira.bridge.hidesOnClose and not akira.app.quit_on_last


def test_hidden_akira_gets_out_of_the_way(app):
    akira = background(app)

    akira.window.hide()

    assert akira.bridge.hidden
    assert akira.priorities == [True]
    assert akira.voice.released == 1
    assert pump_until(app, lambda: akira.router.unloads == 1), "the model left the card"


def test_with_closing_set_to_quit_the_window_going_is_not_the_background(app):
    akira = background(app, keep_running=False)
    akira.window.hide()
    assert not akira.bridge.hidden and akira.priorities == [] and akira.voice.released == 0


def test_the_model_waits_for_a_reply_still_being_written(app):
    akira = background(app)
    akira.chat.busy = True

    akira.window.hide()
    time.sleep(0.1)
    assert akira.router.unloads == 0

    akira.chat.busy = False
    akira.chat.busyChanged.emit()
    assert pump_until(app, lambda: akira.router.unloads == 1)


def test_a_running_job_keeps_the_model_between_its_steps(app):
    akira = background(app)
    akira.scheduler.busy = True
    akira.window.hide()
    time.sleep(0.1)
    assert akira.router.unloads == 0


def test_coming_back_loads_the_model_and_lets_waiting_jobs_go(app):
    akira = background(app)
    akira.window.hide()
    assert pump_until(app, lambda: not akira.router.loaded)

    akira.bridge.showWindow()

    assert not akira.bridge.hidden
    assert akira.priorities == [True, False]
    assert pump_until(app, lambda: akira.router.warmed), "loaded again for the window"
    assert akira.scheduler.wake.is_set()
    assert akira.window.raised == 1


def test_a_call_window_on_screen_is_not_the_background(app):
    akira = background(app)
    akira.call.show()
    akira.window.hide()
    assert not akira.bridge.hidden and akira.priorities == []
    akira.call.hide()
    assert akira.bridge.hidden


def test_bringing_it_back_undoes_minimising(app):
    akira = background(app)
    akira.window.states = Qt.WindowState.WindowMinimized
    akira.bridge.showWindow()
    assert not akira.window.states & Qt.WindowState.WindowMinimized


def test_jobs_needing_the_card_only_wait_while_hidden(app):
    akira = background(app, card="a game is running full screen")
    assert akira.bridge.card_busy() == ""
    akira.window.hide()
    assert akira.bridge.card_busy() == "a game is running full screen"


def test_notices_become_windows_notifications_only_while_hidden(app):
    akira = background(app)
    akira.requests.noticed.emit("Reminder", "Call the dentist")
    assert akira.tray.messages == []

    akira.window.hide()
    akira.requests.noticed.emit("Reminder", "Call the dentist")
    assert akira.tray.messages == [("Reminder", "Call the dentist")]


def test_a_question_waiting_says_so_without_saying_what_it_is(app):
    akira = background(app)
    akira.window.hide()

    akira.requests.requested.emit("token", "Send the email to Sam about the rent")
    akira.requests.criticalFound.emit(1)

    (title, text), (review, _) = akira.tray.messages
    assert title == "Akira is waiting for your answer"
    assert "Sam" not in text and "rent" not in text
    assert review == "The security review found a problem"


def test_the_first_close_explains_how_to_quit_once(app):
    akira = background(app)
    akira.window.hide()
    akira.bridge.windowClosed()
    akira.bridge.windowClosed()

    assert len(akira.tray.messages) == 1
    title, text = akira.tray.messages[0]
    assert title == "Akira is still running" and "Quit Akira" in text
    assert akira.config.told_keeps_running


def test_quitting_takes_everything_down_and_nothing_follows(app):
    akira = background(app)
    akira.call.show()

    akira.bridge.quit()

    assert akira.bridge.quitting and not akira.bridge.hidesOnClose
    assert not akira.window.isVisible() and not akira.call.isVisible()
    assert akira.tray.hidden and akira.instance.released
    assert akira.exits == [0]
    akira.bridge.quit()
    assert akira.exits == [0], "once"
    # The windows going is quitting, not the background: nothing is lowered or loaded.
    assert akira.priorities == [] and akira.router.unloads == 0
    akira.requests.noticed.emit("Reminder", "Too late")
    assert akira.tray.messages == []
