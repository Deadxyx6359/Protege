"""Akira by the clock: the window closed, Akira still running.

Closing the window hides it, and Akira goes on from its icon in the notification
area, by the clock, so that reminders, watches and scheduled jobs keep working.
While no Akira window is open it keeps out of the way of whatever else is
running, a game above all:

- the language model leaves the graphics card and memory as soon as nothing is
  answering, and the speech models go too; the model loads again when the
  window opens;
- the process runs in Windows' background mode, behind every other program;
- a scheduled job that needs a model waits while a game or another full-screen
  program has the screen, or another program has the card (`akira.core.quiet`);
  everything else, a reminder included, runs on time;
- notices, and a job waiting for a yes or no, become Windows notifications,
  since there is no window to show them in. Windows holds those back itself
  during a game.

Quitting, from the icon's menu, from Settings or with Ctrl+Q, ends Akira and
every program it started (`akira.core.processes`). With "Keep running when
closed" off, closing the window quits, as it always did.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PySide6.QtCore import (QCoreApplication, QMetaObject, QObject, Qt, QTimer, Property,
                            Signal, Slot)

from akira.core import quiet
from akira.core.config import AppConfig
from akira.core.models import ModelRouter, Route

#: How often, while hidden, a model still held is looked at again, in case what
#: kept it (a reply still being written, a job between steps) has finished.
LET_GO_EVERY_MS = 20_000

#: How long a let-go waits for the model to be free before trying again later.
LET_GO_WAIT_S = 1.0

#: How long a notification stays up, in milliseconds. Windows may keep it longer.
NOTIFICATION_MS = 10_000


class BackgroundBridge(QObject):
    """Whether Akira keeps running when its window closes, and what it does then.

    Built with everything else, so the window can read `keepRunning`; the icon by
    the clock, and watching the windows, start with `attach`, in the application
    alone.
    """

    keepRunningChanged = Signal()
    quittingChanged = Signal()
    hiddenChanged = Signal()

    #: Private: from another Akira's launch, on a worker thread, to this one.
    _called = Signal()

    def __init__(self, config: AppConfig, router: ModelRouter, *, voice: Any = None,
                 chat: Any = None, agents: Any = None, scheduler: Any = None,
                 persist: bool = True, card: quiet.CardWatch | None = None,
                 priority: Callable[[bool], Any] = quiet.background_priority,
                 leave: Callable[[int], Any] = QCoreApplication.exit,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._router = router
        self._voice = voice
        self._chat = chat
        self._agents = agents
        self._scheduler = scheduler
        self._persist = persist
        self._card = card if card is not None else quiet.CardWatch()
        self._priority = priority
        self._leave = leave
        self._app: Any = None
        self._window: Any = None
        self._call_window: Any = None
        self._instance: Any = None
        self._tray: Any = None
        self._hidden = False
        self._quitting = False
        self._letting_go = threading.Lock()
        self._retry = QTimer(self)
        self._retry.setInterval(LET_GO_EVERY_MS)
        self._retry.timeout.connect(self._let_go)
        self._called.connect(self.showWindow)
        if chat is not None:
            chat.busyChanged.connect(self._let_go)

    # -- what QML reads -----------------------------------------------------------------------

    @Property(bool, notify=keepRunningChanged)
    def keepRunning(self) -> bool:
        """The setting: closing the window leaves Akira running by the clock."""
        return self._config.keep_running

    @keepRunning.setter
    def keepRunning(self, on: bool) -> None:
        on = bool(on)
        if on == self._config.keep_running:
            return
        self._config.keep_running = on
        self._save()
        self._follow_setting()
        self.keepRunningChanged.emit()

    @Property(bool, notify=keepRunningChanged)
    def hidesOnClose(self) -> bool:
        """Whether closing the window hides it now: the setting is on, there is an
        icon by the clock to come back from, and Akira is not quitting."""
        return self._config.keep_running and self._tray is not None and not self._quitting

    @Property(bool, notify=quittingChanged)
    def quitting(self) -> bool:
        return self._quitting

    @Property(bool, notify=hiddenChanged)
    def hidden(self) -> bool:
        """Whether no Akira window is open, and Akira is keeping out of the way."""
        return self._hidden

    # -- starting -----------------------------------------------------------------------------

    def attach(self, app: Any, window: Any, *, call_window: Any = None, instance: Any = None,
               tray: Any = None, monitor: Any = None, confirm: Any = None, allow: Any = None,
               schedule: Any = None) -> None:
        """Watch \a window (and the call's), and put Akira's icon by the clock.

        \a tray is for tests; the application's own is made here when Windows has
        a notification area. The request signals are shown as notifications while
        Akira is hidden.
        """
        self._app, self._window, self._call_window = app, window, call_window
        self._instance = instance
        self._tray = tray if tray is not None else _make_tray(self, app)
        for watched in (window, call_window):
            if watched is not None:
                watched.visibleChanged.connect(self._on_visibility)
        if instance is not None:
            instance.listen(self._called.emit)
        if monitor is not None:
            monitor.noticed.connect(self._notify)
        if confirm is not None:
            confirm.requested.connect(lambda _token, _summary: self._notify(
                "Akira is waiting for your answer",
                "Something needs your yes or no. Open Akira to answer; nobody answering "
                "is a no."))
        if allow is not None:
            allow.requested.connect(lambda _token, _request: self._notify(
                "Akira is asking first",
                "Something needs your permission. Open Akira to answer."))
        if schedule is not None:
            schedule.criticalFound.connect(lambda _count: self._notify(
                "The security review found a problem", "Open Akira to see what it found."))
        self._follow_setting()
        self.keepRunningChanged.emit()

    def _follow_setting(self) -> None:
        # With the window hiding on close, the last window never closes; a menu
        # from the icon closing must not be taken for it either.
        if self._app is not None:
            self._app.setQuitOnLastWindowClosed(not self.hidesOnClose)

    # -- the window ---------------------------------------------------------------------------

    @Slot()
    def windowClosed(self) -> None:
        """The window was closed into the background. The first time, say so."""
        if self._config.told_keeps_running or self._tray is None:
            return
        self._config.told_keeps_running = True
        self._save()
        self._notify("Akira is still running",
                     "Reminders, watches and scheduled jobs keep working, and the model has "
                     "left the graphics card. To quit, right-click Akira's icon by the clock "
                     "(it may be under the ^ arrow) and choose Quit Akira.", always=True)

    @Slot()
    def showWindow(self) -> None:
        """Bring the window back, as it was, in front."""
        window = self._window
        if window is None or self._quitting:
            return
        if not window.isVisible():
            window.show()
        if window.windowStates() & Qt.WindowState.WindowMinimized:
            window.setWindowStates(window.windowStates() & ~Qt.WindowState.WindowMinimized)
        window.raise_()
        window.requestActivate()

    @Slot()
    def newChat(self) -> None:
        self.showWindow()
        if self._window is not None:
            QMetaObject.invokeMethod(self._window, "newChat")

    @Slot()
    def quit(self) -> None:
        """End Akira: the windows go at once, and everything else closes behind them."""
        if self._quitting:
            return
        self._quitting = True
        self._retry.stop()
        if self._instance is not None:
            self._instance.release()
        if self._tray is not None:
            self._tray.hide()
        self.quittingChanged.emit()
        self.keepRunningChanged.emit()
        for window in (self._call_window, self._window):
            if window is not None:
                window.hide()
        # `exit` rather than `quit`: Qt's quit asks each window to close first,
        # and the window would refuse, hiding itself instead.
        self._leave(0)

    def _on_visibility(self, *_args) -> None:
        if self._quitting:
            return
        shown = any(w is not None and w.isVisible() for w in (self._window, self._call_window))
        # Without hiding on close, the window going is Akira closing, which
        # should not be slowed by background mode.
        self._set_hidden(not shown and self.hidesOnClose)

    def _set_hidden(self, hidden: bool) -> None:
        if hidden == self._hidden:
            return
        self._hidden = hidden
        if hidden:
            self._priority(True)
            if self._voice is not None:
                self._voice.release()
            self._card.forget()
            self._let_go()
            self._retry.start()
        else:
            self._retry.stop()
            self._priority(False)
            self._warm()
            # Anything that waited for the card goes now.
            if self._scheduler is not None:
                self._scheduler.wake.set()
        self.hiddenChanged.emit()

    # -- the graphics card --------------------------------------------------------------------

    def card_busy(self) -> str:
        """For the scheduler: why a job needing a model should wait, or "".

        Only while hidden. With a window open the person is at Akira, and the
        model is theirs to use.
        """
        if not self._hidden or self._quitting:
            return ""
        return self._card.busy()

    def _busy(self) -> bool:
        return bool((self._chat is not None and self._chat.busy)
                    or (self._agents is not None and self._agents.busy)
                    or (self._scheduler is not None and self._scheduler.busy)
                    or self._router.generating)

    @Slot()
    def _let_go(self) -> None:
        """While hidden, unload the model once nothing is using it."""
        if not self._hidden or self._quitting or not self._router.loaded or self._busy():
            return
        if not self._letting_go.acquire(blocking=False):
            return

        def unload() -> None:
            try:
                self._router.unload_all(timeout=LET_GO_WAIT_S)
            finally:
                self._card.forget()
                self._letting_go.release()

        threading.Thread(target=unload, name="akira-let-go", daemon=True).start()

    def _warm(self) -> None:
        """Load the model again for the window, as at startup, if that is wanted."""
        if not self._config.preload or self._router.loaded or self._router.lent:
            return
        threading.Thread(target=self._router.warm,
                         args=(Route.parse(self._config.default_route),),
                         name="preload", daemon=True).start()

    # -- notifications ------------------------------------------------------------------------

    def _notify(self, title: str, text: str, *, always: bool = False) -> None:
        """A Windows notification, while there is no window to show it in."""
        if self._tray is None or self._quitting or not (self._hidden or always):
            return
        self._tray.showMessage(title, text, _information(), NOTIFICATION_MS)

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._config.save()
        except OSError:
            pass  # remembered for this run; asked again next time


def _information() -> Any:
    from PySide6.QtWidgets import QSystemTrayIcon

    return QSystemTrayIcon.MessageIcon.Information


def _make_tray(bridge: BackgroundBridge, app: Any) -> Any:
    """Akira's icon by the clock, with its menu. None where there can be none:
    without a widgets application, or a notification area."""
    try:
        from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    except ImportError:
        return None
    if not isinstance(app, QApplication) or not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(app.windowIcon(), bridge)
    tray.setToolTip("Akira")
    menu = QMenu()
    menu.addAction("Open Akira", bridge.showWindow)
    menu.addAction("New chat", bridge.newChat)
    menu.addSeparator()
    menu.addAction("Quit Akira", bridge.quit)
    tray.setContextMenu(menu)
    bridge._menu = menu  # a context menu is not owned by its icon; kept alive with it

    def activated(reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            bridge.showWindow()

    tray.activated.connect(activated)
    tray.messageClicked.connect(bridge.showWindow)
    tray.show()
    return tray
