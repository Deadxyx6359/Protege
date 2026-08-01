"""The chat shell: DPI scaling, the FAB, the activity indicator, the sidebar.

Each of these encodes a bug that was found by looking at a screenshot rather
than by a failing test. Screenshots do not run in CI and I will not remember
these next month, so they are pinned here.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from protege import store
from protege.projects import ensure_project
from protege.schemas import Settings


@pytest.fixture
def root(clean_root):
    """The shared session-wide Tk interpreter (see conftest.py).

    Not a fresh `tk.Tk()` per module: several live interpreters in one process
    made Tk fail intermittently, and the fixture's TclError handler turned that
    into a silent skip of the whole module.
    """
    return clean_root


@pytest.fixture
def vault(tmp_path):
    root_path = tmp_path / "vault"
    root_path.mkdir()
    store.bootstrap_vault(root_path)
    ensure_project(root_path, "default")
    return root_path


# --- DPI scaling -------------------------------------------------------------


def test_px_scales_with_the_display():
    from protege.ui import theme

    factor = theme.scale()
    assert factor >= 1.0
    assert theme.px(100) == max(1, round(100 * factor))
    # Never collapses a real measurement to zero.
    assert theme.px(1) >= 1


def test_enable_dpi_awareness_reports_a_factor():
    from protege.ui import theme

    factor = theme.enable_dpi_awareness()
    assert factor >= 1.0


def test_theme_scaling_is_applied_to_the_interpreter(root):
    """Tk sizes fonts in points against its own scaling factor; a DPI-aware
    process must set it or every font renders physically small."""
    scaling = float(root.tk.call("tk", "scaling"))
    assert scaling > 1.0


# --- palette -----------------------------------------------------------------


def test_body_text_is_pure_white():
    from protege.ui import theme

    assert theme.FG == "#ffffff"


def test_ground_is_darker_than_panels_which_are_darker_than_raised():
    """The three-step depth ramp is what stops the UI reading as one flat
    black rectangle."""
    from protege.ui import theme

    def luminance(hex_colour: str) -> int:
        return sum(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))

    assert luminance(theme.BG) < luminance(theme.BG_PANEL) < luminance(theme.BG_RAISED)


# --- the floating action button ----------------------------------------------


def _fab(root):
    from protege.ui.fab import FloatingActionButton

    fired: list[str] = []
    host = tk.Frame(root, width=600, height=400)
    host.pack(fill="both", expand=True)
    button = FloatingActionButton(
        host,
        [
            ("New skill", "have the model write a tool", lambda: fired.append("skill")),
            ("Attach file", "add a file", lambda: fired.append("attach")),
        ],
    )
    button.place(relx=1.0, rely=1.0, x=-20, y=-20, anchor="se")
    root.update_idletasks()
    return host, button, fired


def test_fab_opens_and_closes(root):
    host, button, _ = _fab(root)
    try:
        assert button._card is None
        button.open()
        root.update_idletasks()
        assert button._card is not None
        assert button._card.winfo_exists()
        button.close()
        assert button._card is None
    finally:
        host.destroy()


def test_fab_card_is_an_in_window_frame_not_a_toplevel(root):
    """A Toplevel with overrideredirect ignores geometry() on Windows and
    parks itself at the top-left of the display regardless of the coordinates
    it is handed. An in-window frame cannot drift."""
    host, button, _ = _fab(root)
    try:
        button.open()
        root.update_idletasks()
        assert isinstance(button._card, tk.Frame)
        assert not isinstance(button._card, tk.Toplevel)
    finally:
        host.destroy()


def test_fab_card_sits_inside_the_window_near_the_button(root):
    host, button, _ = _fab(root)
    try:
        button.open()
        root.update_idletasks()
        card = button._card
        # Placed relative to the shared parent, anchored bottom-right.
        assert card.winfo_x() > 0
        assert card.winfo_y() > 0
        assert card.winfo_x() + card.winfo_width() <= host.winfo_width() + 4
    finally:
        host.destroy()


def test_fab_toggle_is_idempotent(root):
    host, button, _ = _fab(root)
    try:
        button.open()
        button.open()          # second open must not orphan the first card
        root.update_idletasks()
        button.close()
        button.close()         # closing twice must not raise
        assert button._card is None
    finally:
        host.destroy()


def test_fab_with_no_actions_does_nothing(root):
    from protege.ui.fab import FloatingActionButton

    host = tk.Frame(root)
    host.pack()
    button = FloatingActionButton(host, [])
    button.pack()
    try:
        button.open()
        assert button._card is None
    finally:
        host.destroy()


# --- activity indicator -------------------------------------------------------


def test_activity_reports_stages_in_plain_language(root):
    from protege.ui.activity import STAGE_TEXT, ActivityIndicator

    indicator = ActivityIndicator(root)
    indicator.pack()
    try:
        indicator.start("retrieving")
        root.update_idletasks()
        assert indicator.label.cget("text") == STAGE_TEXT["retrieving"]

        indicator.set_stage("checking")
        root.update_idletasks()
        assert indicator.label.cget("text") == STAGE_TEXT["checking"]
        # Internal pipeline names must never reach the user.
        assert indicator.label.cget("text") != "checking"
    finally:
        indicator.stop()
        indicator.destroy()


def test_activity_covers_every_stage_the_pipeline_emits():
    """The pipeline's `on_stage` strings and the indicator's vocabulary must
    not drift apart -- an unmapped stage shows a raw identifier."""
    from protege.ui.activity import STAGE_TEXT

    emitted = {"retrieving", "assembling", "generating", "checking",
               "summarizing", "generating questions", "checking for other locked topics"}
    assert emitted <= set(STAGE_TEXT)


def test_activity_stops_cleanly(root):
    from protege.ui.activity import ActivityIndicator

    indicator = ActivityIndicator(root)
    indicator.pack()
    indicator.start()
    root.update_idletasks()
    indicator.stop()
    assert indicator._after is None
    indicator.destroy()


def test_activity_shows_an_elapsed_clock(root):
    from protege.ui.activity import ActivityIndicator

    indicator = ActivityIndicator(root)
    indicator.pack()
    try:
        indicator.start()
        root.update()
        assert ":" in indicator.clock.cget("text")
    finally:
        indicator.stop()
        indicator.destroy()


def test_slow_stages_gain_an_explanation(root):
    """A 40-second wait with no explanation is indistinguishable from a hang."""
    from protege.ui.activity import STAGE_HINT

    assert "generating" in STAGE_HINT
    assert "checking" in STAGE_HINT


# --- sidebar ------------------------------------------------------------------


def test_sidebar_is_short(root):
    """It listed thirteen rows once -- a menu bar wearing a sidebar's clothes.
    Creation actions belong to the + button; this is navigation only."""
    from protege.ui.sidebar import NAV_ITEMS

    assert len(NAV_ITEMS) <= 6
    keys = {key for key, _, _ in NAV_ITEMS}
    # Creation actions must not have crept back in.
    assert not keys & {"attach", "import", "unlock", "attachments", "prompt"}


def test_sidebar_builds_and_marks_the_current_project(root):
    from protege.ui import theme
    from protege.ui.sidebar import Sidebar

    bar = Sidebar(
        root, actions={"new_session": lambda: None, "settings": lambda: None},
        projects=["alpha", "beta"], current_project="beta",
        on_switch_project=lambda n: None, on_new_project=lambda: None,
    )
    bar.pack()
    root.update_idletasks()
    try:
        assert set(bar._project_rows) == {"alpha", "beta"}
        assert str(bar._project_rows["beta"].cget("bg")) == theme.PURPLE_DEEP
        bar.set_status("Tier 2\n7 topics")
        assert "Tier 2" in bar.status.cget("text")
    finally:
        bar.destroy()


# --- the chat shell -----------------------------------------------------------


def test_main_window_layout(vault, tk_available):
    """Chat is a fixed-width column with rain either side, so a wider window
    yields more rain rather than longer, less readable lines."""
    from protege.ui import theme
    from protege.ui.app import CHAT_COLUMN_WIDTH, ProtegeWindow

    try:
        win = ProtegeWindow(vault, store.load_manifest(vault), Settings(),
                            store.load_personality(vault))
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")
    win.withdraw()
    win.update_idletasks()
    try:
        assert win._column.winfo_reqwidth() == theme.px(CHAT_COLUMN_WIDTH)
        assert win.rain_left.winfo_exists()
        assert win.rain_right.winfo_exists()
        assert win.fab.winfo_exists()
        # No menu bar: Windows draws it and ignores the theme.
        assert win.cget("menu") == ""
    finally:
        win.manager.close()
        win.destroy()


def test_activity_is_hidden_at_rest_and_shown_while_busy(vault, tk_available):
    from protege.ui.app import ProtegeWindow

    try:
        win = ProtegeWindow(vault, store.load_manifest(vault), Settings(),
                            store.load_personality(vault))
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")
    win.withdraw()
    win.update_idletasks()
    try:
        assert not win.activity.winfo_ismapped()
        win._set_busy(True)
        win.update_idletasks()
        assert win.activity.winfo_manager() == "pack"
        # Above the composer -- where the answer appears, not below the input.
        siblings = win._column.pack_slaves()
        assert siblings.index(win.activity) < siblings.index(win._composer)
        win._set_busy(False)
        win.update_idletasks()
        assert not win.activity.winfo_ismapped()
    finally:
        win.manager.close()
        win.destroy()


def test_px_preserves_the_sign_of_an_offset():
    """`px` floors to one pixel so hairlines survive, but on the magnitude.

    `place(x=px(-26))` is an inset from the right edge, not a size. Flooring
    the raw value at 1 turned that into +1 and pushed the floating action
    button and its menu a pixel past the corner of the window, so the button
    was shaved along two edges on every launch.
    """
    from protege.ui import theme

    assert theme.px(-26) < 0
    assert theme.px(-26) == -theme.px(26)
    assert theme.px(0) == 0
    # The floor still applies: a hairline must not round away to nothing.
    assert theme.px(0.1) == 1
    assert theme.px(-0.1) == -1


def test_the_fab_and_its_card_stay_inside_the_window(vault, tk_available):
    """The corner controls must sit inside the frame they float over."""
    from protege.ui.app import ProtegeWindow

    try:
        win = ProtegeWindow(vault, store.load_manifest(vault), Settings(),
                            store.load_personality(vault))
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")
    try:
        win.geometry("1200x800")
        win.update()
        parent = win.fab.master
        right = parent.winfo_rootx() + parent.winfo_width()
        bottom = parent.winfo_rooty() + parent.winfo_height()

        fab_right = win.fab.winfo_rootx() + win.fab.winfo_width()
        fab_bottom = win.fab.winfo_rooty() + win.fab.winfo_height()
        assert fab_right < right, "the + button hangs off the right edge"
        assert fab_bottom < bottom, "the + button hangs off the bottom edge"

        win.fab.open()
        win.update()
        card = win.fab._card
        card_right = card.winfo_rootx() + card.winfo_width()
        assert card_right <= right, "the action card hangs off the right edge"
        assert card.winfo_rootx() >= parent.winfo_rootx()
    finally:
        try:
            win.manager.close()
        except Exception:
            pass
        win.destroy()
