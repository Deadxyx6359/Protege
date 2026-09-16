"""Shared test fixtures.

The important one is `tk_root`: a **single** Tk interpreter for the whole
session.

Every UI module used to create its own `tk.Tk()`. Tk tolerates several live
interpreters in one process badly, and the symptom was not a crash but a
silent one: a module's root would fail to initialise, its fixture would catch
`TclError`, call `pytest.skip("no display available")`, and fifteen tests would
quietly stop running. The suite still said "passed". That is the same
looks-fine-isn't failure mode this project keeps finding in its own UI, and it
is worse in the test harness, because the harness is what is supposed to catch
it.

One root, created once, reused everywhere. If it genuinely cannot be created --
a headless machine -- every UI test skips together and visibly, rather than a
random subset vanishing.

The mechanism behind that old flake is now pinned down, and it is not Tk's
fault: under pytest's **default fd-level capture** a second `tk.Tk()` in the
same process can fail to initialise, reporting "Can't find a usable init.tcl"
about a file that plainly exists. The same test passes under `-s` or
`--capture=sys`. Modules that must build their own root (AkiraWindow is one)
therefore live with a real risk of a spurious `TclError` -- which is exactly
why they must not translate one into a skip. See `tk_available`.
"""

from __future__ import annotations

import gc
import tkinter as tk

import pytest

_root: tk.Tk | None = None
_failed = False


def _ensure_root() -> tk.Tk | None:
    """Build the shared interpreter once. None means Tk genuinely will not start."""
    global _root, _failed
    if _failed:
        return None
    if _root is None:
        try:
            widget = tk.Tk()
        except tk.TclError:
            _failed = True
            return None
        from akira.ui import theme

        theme.install(widget)
        widget.geometry("900x620+4000+4000")
        widget.update()
        _root = widget
    return _root


@pytest.fixture(scope="session", autouse=True)
def _own_the_default_root():
    """Build the shared interpreter before any test can build one of its own.

    Tkinter keeps a module-level `_default_root`: the first `tk.Tk()` created
    in the process. Any widget built without an explicit master is parented to
    it. `AkiraWindow` is its own `tk.Tk`, so whichever test touched Tk first
    decided who the default root was -- and when that test destroyed its
    window, `_default_root` was left pointing at a dead interpreter. Every
    later test that built an unmastered widget then failed with "application
    has been destroyed", which test, and whether it happened at all, depended
    entirely on the order pytest chose that run.

    Claiming the seat here, once, before collection gets going, removes the
    ordering from the question. The shared root is never destroyed.
    """
    _ensure_root()
    yield


@pytest.fixture(scope="module", autouse=True)
def _collect_on_the_main_thread():
    """Finalise what a test module dropped, here, on the main thread.

    A Tk interpreter a test made and let go of is destroyed whenever the garbage
    collector next runs, on whichever thread happens to be allocating then. When
    that is a background thread — a bridge's worker, the browser's proxy, a
    stand-in server — Tcl aborts the whole run: "Tcl_AsyncDelete: async handler
    deleted by the wrong thread". Which test it lands in depends only on timing,
    so it looks like a crash in something unrelated. Collecting as each module
    ends means it is this thread, before the next module's threads start. Once a
    module rather than once a test, because a full collection after each of two
    thousand tests added over a minute to the run.
    """
    yield
    gc.collect()


@pytest.fixture(scope="session")
def tk_available() -> bool:
    """Whether Tk works at all in this process.

    Modules that build their own `tk.Tk` (AkiraWindow is one) used to catch
    every `TclError` and skip with "no display available". That is only ever
    true of a headless machine, and on a machine with a display it turned real
    bugs into green runs -- most recently a sprite created against the wrong
    interpreter, which silently disabled nineteen tests.

    So: ask once whether Tk works. If it does, a later `TclError` is a defect
    and must be raised, not excused.
    """
    return _ensure_root() is not None


@pytest.fixture(scope="session")
def tk_root():
    """The one Tk interpreter, themed and parked off-screen.

    Mapped rather than withdrawn: a transient Toplevel whose master is
    withdrawn is never mapped by Windows, which breaks any test that measures
    a dialog's real geometry.
    """
    widget = _ensure_root()
    if widget is None:
        pytest.skip("Tk is unavailable in this environment")
    yield widget


@pytest.fixture
def clean_root(tk_root):
    """The shared root with any leftover children destroyed.

    Guards against cross-test contamination: a widget a previous test forgot
    to destroy would otherwise still be packed and could satisfy or break an
    unrelated assertion.
    """
    for child in list(tk_root.winfo_children()):
        try:
            child.destroy()
        except tk.TclError:
            pass
    tk_root.update_idletasks()
    yield tk_root
