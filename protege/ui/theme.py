"""The Protege theme: black, purple, ivory.

One palette, defined once, applied through Tk's option database so every widget
created after `install()` inherits it -- including Toplevel dialogs, which share
the interpreter-wide option database. Individual modules take colors from here
and never write a hex literal of their own; a second source of truth is how a
theme drifts into a patchwork.

Design intent, so future edits stay coherent:

* **Black is the ground, purple is the signal.** Backgrounds are near-black
  with a violet cast; purple appears on interactive and structural elements
  (buttons, selection, headings, the rain), never as body text.
* **Ivory is for reading.** All prose is ivory on black -- the highest-contrast
  pairing in the palette -- because a themed app you cannot comfortably read is
  a screensaver, not a tool.
* **The danger/warning colors stay loud.** Blocked responses and disabled-layer
  warnings exist to interrupt; they are the two places the theme defers to
  legibility over aesthetics.

The font is Cascadia Mono -- monospace, ships with Windows 11, reads as
terminal-native without being a novelty font -- falling back to Consolas, then
Courier New, so the app degrades sanely on an older machine.

NOTE (deliberate departure): the original project brief specified "system
default widgets, no theming". The user overrode that with an explicit visual
direction, and this module is that direction. The *structure* of the brief's
rule survives: plain `tk` widgets, no third-party styling packages, no images,
no icons -- everything here is colors, fonts, and the option database.
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

# --- palette ---------------------------------------------------------------

BG = "#08080d"            # near-black, slight violet cast; main ground
BG_PANEL = "#101018"      # sidebar and panels -- one step up from ground
BG_ENTRY = "#14141d"      # text entry fields
BG_RAISED = "#191925"     # cards, the composer, hovered rows
FG = "#ffffff"            # pure white: all body text, maximum contrast on black
FG_SOFT = "#d8d4e4"       # slightly recessed prose (system lines)
FG_DIM = "#8d86a3"        # muted lavender-grey: secondary text, hints

PURPLE = "#9d4edd"        # primary accent: buttons, headings, prefixes
PURPLE_BRIGHT = "#c77dff" # links, hover, the rain's head glyphs
PURPLE_DIM = "#5a189a"    # borders, troughs, inactive accents
PURPLE_DEEP = "#2d0a54"   # selection background
PURPLE_GHOST = "#3c096c"  # rain mid-trail, subtle structure lines

DANGER = "#ff5d8f"        # blocked responses; readable pink-red on black
WARNING_BG = "#332600"    # warning strip ground (dark amber)
WARNING_FG = "#ffd60a"    # warning strip text (bright amber)

PURPLE_MID = "#7b2cbf"    # between PURPLE and PURPLE_DIM, for gradients
PURPLE_PALE = "#e7d7ff"   # near-white lavender: brightest point of a ramp
PURPLE_FAINT = "#1d0a38"  # barely above the ground; end of the rain trail

# Rain trail, head first. The head is near-white lavender so it reads as a
# light source; the tail sinks toward the background rather than to grey.
RAIN_COLORS = (PURPLE_PALE, PURPLE_BRIGHT, PURPLE, PURPLE_MID, PURPLE_DIM,
               PURPLE_GHOST, PURPLE_FAINT)

# Dim -> bright ramp for the working indicator's pulse.
PULSE_RAMP = (PURPLE_GHOST, PURPLE_DIM, PURPLE_MID, PURPLE, PURPLE_BRIGHT, PURPLE_PALE)

# Two font roles, deliberately split. All-mono-everything at 10pt is what made
# the first cut of this theme read as "low res and old": interface prose set in
# a terminal face looks like a screenshot of a config file. Segoe UI carries
# labels, buttons and menus; the monospace face is reserved for the places the
# terminal look is the point -- chat text, the rain, the wordmark, and lists
# whose column alignment depends on fixed width.
MONO_CANDIDATES = ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New")
UI_CANDIDATES = ("Segoe UI Variable Text", "Segoe UI", "Tahoma", "Arial")

MONO_SIZE = 11
UI_SIZE = 10

_resolved: dict[str, str] = {}


def enable_dpi_awareness() -> float:
    """Tell Windows this process scales itself. Call BEFORE creating the root.

    This is the real fix for text that looks soft or "low res", and it has
    nothing to do with the typeface. On a display running at 125% (this one:
    3440 physical pixels reported to unaware apps as 2752 logical), Windows
    renders a non-aware window at the smaller size and then bitmap-stretches it
    by 1.25x. Every glyph gets resampled, so even a crisp font arrives blurry.
    Declaring awareness makes Tk draw at native resolution and the blur is gone.

    Returns the scaling factor so the caller can size fonts to match; 1.0 if
    awareness could not be set (non-Windows, or an old build).
    """
    try:
        import ctypes

        # 2 == PROCESS_PER_MONITOR_DPI_AWARE. Preferred, Windows 8.1+.
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:  # noqa: BLE001 - fall back to the Vista-era call
            ctypes.windll.user32.SetProcessDPIAware()

        dc = ctypes.windll.user32.GetDC(0)
        try:
            # LOGPIXELSX; 96 is the unscaled baseline.
            dpi = ctypes.windll.gdi32.GetDeviceCaps(dc, 88)
        finally:
            ctypes.windll.user32.ReleaseDC(0, dc)
        return (dpi or 96) / 96.0
    except Exception:  # noqa: BLE001 - cosmetic; never block startup
        return 1.0


_scale = 1.0


def scale() -> float:
    """The display scaling factor discovered at startup."""
    return _scale


def px(value: float) -> int:
    """Scale a pixel measurement for the current display.

    Fonts are handled by Tk's own scaling; explicit pixel geometry (widget
    widths, canvas cells, dialog sizes) is not, so anything measured in pixels
    has to go through here or it comes out physically smaller on a scaled
    display than it was designed to be.

    The floor of one pixel keeps a hairline from rounding away to nothing on a
    small scale factor. It is applied to the *magnitude*, because these are not
    all sizes: `place(x=px(-26))` is an inset from the right edge, and folding
    that to +1 pushed the floating action button and its menu one pixel past
    the corner of the window instead of 26 inside it. The button looked shaved
    off along two edges and nothing said why.
    """
    scaled = value * _scale
    if scaled == 0:
        return 0
    magnitude = max(1, int(round(abs(scaled))))
    return magnitude if scaled > 0 else -magnitude


def _resolve(kind: str, candidates: tuple[str, ...], root: tk.Misc | None) -> str:
    if kind in _resolved:
        return _resolved[kind]
    available: set[str] = set()
    if root is not None:
        try:
            available = set(tkfont.families(root))
        except tk.TclError:
            available = set()
    for candidate in candidates:
        if candidate in available:
            _resolved[kind] = candidate
            return candidate
    _resolved[kind] = candidates[-1]
    return _resolved[kind]


def font_family(root: tk.Misc | None = None) -> str:
    """The monospace family. Name kept from the all-mono era; existing callers
    all use it for chat tags, the rain, and wordmarks -- the places that stay
    mono on purpose."""
    return _resolve("mono", MONO_CANDIDATES, root)


def ui_family(root: tk.Misc | None = None) -> str:
    return _resolve("ui", UI_CANDIDATES, root)


def font(root: tk.Misc | None = None, size: int = MONO_SIZE, *, bold: bool = False) -> tuple:
    return (font_family(root), size, "bold" if bold else "normal")


def ui_font(root: tk.Misc | None = None, size: int = UI_SIZE, *, bold: bool = False) -> tuple:
    return (ui_family(root), size, "bold" if bold else "normal")


def install(root: tk.Tk) -> None:
    """Apply the theme to the whole interpreter.

    Must run before any themed widget is constructed -- the option database
    only affects widgets created after the entry is added. `run_app` calls this
    immediately after creating the root and before building anything.
    """
    global _scale
    # Tk measures font sizes in points and applies its own scaling factor; a
    # DPI-aware process must tell it the real one or every font comes out
    # physically small on a scaled display.
    try:
        dpi = root.winfo_fpixels("1i")
        root.tk.call("tk", "scaling", dpi / 72.0)
        _scale = dpi / 96.0
    except tk.TclError:
        _scale = 1.0

    mono = font_family(root)
    ui = ui_family(root)
    root.configure(bg=BG)

    add = root.option_add
    # Ground rules for every classic widget. Interface text is Segoe UI;
    # mono is opted into per-class below.
    add("*background", BG)
    add("*foreground", FG)
    add("*font", f"{{{ui}}} {UI_SIZE}")
    add("*highlightBackground", BG)
    add("*highlightColor", PURPLE_DIM)
    add("*highlightThickness", 0)

    # Text-bearing widgets: panel ground, ivory ink, purple caret/selection.
    # Text and Entry carry conversation and paths -- mono at a size where
    # Cascadia renders crisply. Listbox stays mono because the skills and
    # attachment lists align columns with spaces.
    for cls in ("Text", "Entry", "Listbox", "Spinbox"):
        add(f"*{cls}.background", BG_ENTRY)
        add(f"*{cls}.foreground", FG)
        add(f"*{cls}.insertBackground", PURPLE_BRIGHT)
        add(f"*{cls}.selectBackground", PURPLE_DEEP)
        add(f"*{cls}.selectForeground", FG)
        add(f"*{cls}.highlightThickness", 1)
        add(f"*{cls}.highlightBackground", PURPLE_GHOST)
        add(f"*{cls}.highlightColor", PURPLE)
        add(f"*{cls}.relief", "flat")
        add(f"*{cls}.font", f"{{{mono}}} {MONO_SIZE}")
    add("*Listbox.font", f"{{{mono}}} {UI_SIZE}")

    # Buttons: purple as the interactive signal.
    add("*Button.background", BG_PANEL)
    add("*Button.foreground", PURPLE_BRIGHT)
    add("*Button.activeBackground", PURPLE_DEEP)
    add("*Button.activeForeground", FG)
    add("*Button.relief", "flat")
    add("*Button.borderWidth", 1)
    add("*Checkbutton.activeBackground", BG)
    add("*Checkbutton.activeForeground", FG)
    add("*Checkbutton.selectColor", BG_ENTRY)
    add("*Radiobutton.activeBackground", BG)
    add("*Radiobutton.activeForeground", FG)
    add("*Radiobutton.selectColor", BG_ENTRY)

    # Menus. The menubar itself is drawn by Windows and ignores most of this;
    # the dropdown panes honor it.
    add("*Menu.background", BG_PANEL)
    add("*Menu.foreground", FG)
    add("*Menu.activeBackground", PURPLE_DEEP)
    add("*Menu.activeForeground", FG)
    add("*Menu.relief", "flat")

    # Sliders (the personality bands).
    add("*Scale.background", BG)
    add("*Scale.foreground", FG)
    add("*Scale.troughColor", PURPLE_GHOST)
    add("*Scale.activeBackground", PURPLE_BRIGHT)
    add("*Scale.highlightThickness", 0)

    add("*Labelframe.foreground", PURPLE)
    add("*OptionMenu.background", BG_PANEL)
    add("*Canvas.background", BG)
    add("*Canvas.highlightThickness", 0)

    _style_ttk(root)


def _style_ttk(root: tk.Misc) -> None:
    """Theme the two ttk widgets in use: Notebook (Settings) and Scrollbar.

    'clam' is the only built-in ttk theme whose every element accepts color
    configuration; the Windows-native themes ignore most of it.
    """
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        return

    ui = ui_family(root)
    style.configure(".", background=BG, foreground=FG, font=(ui, UI_SIZE))
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BG_PANEL,
        foreground=FG_DIM,
        font=(ui, UI_SIZE),
        padding=(12, 5),
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", PURPLE_DEEP)],
        foreground=[("selected", FG)],
    )
    # 'clam' draws a scrollbar as a bevelled 3D block, and the bevel is not
    # `background` -- it is bordercolor/lightcolor/darkcolor, which default to
    # near-white. Setting only the background left a purple bar with a bright
    # ivory outline and a grey grip down the side of a black window: the single
    # most out-of-place thing in the UI. Every one of those has to be named.
    for orient in ("Vertical", "Horizontal"):
        style.configure(
            f"{orient}.TScrollbar",
            background=PURPLE_DEEP,
            troughcolor=BG,
            bordercolor=BG,
            lightcolor=BG,
            darkcolor=BG,
            arrowcolor=PURPLE_DIM,
            gripcount=0,
            borderwidth=0,
            relief="flat",
            width=px(10),
        )
        style.map(
            f"{orient}.TScrollbar",
            background=[("pressed", PURPLE_BRIGHT), ("active", PURPLE)],
        )

    # Drop the stepper arrows. They are two more pieces of chrome nobody has
    # clicked since scroll wheels arrived, and a bare thumb in a dark trough is
    # what every application the user already has looks like.
    style.layout("Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"}),
        ]}),
    ])
    style.layout("Horizontal.TScrollbar", [
        ("Horizontal.Scrollbar.trough", {"sticky": "ew", "children": [
            ("Horizontal.Scrollbar.thumb", {"expand": 1, "sticky": "nswe"}),
        ]}),
    ])


def darken_titlebar(window: tk.Misc) -> None:
    """Ask Windows 11's DWM to draw this window's title bar dark.

    Best-effort and Windows-only: attribute 20 (DWMWA_USE_IMMERSIVE_DARK_MODE)
    on Windows 11 and late Windows 10, attribute 19 on earlier builds. Failure
    means a white title bar, not a broken app, so every error is swallowed.

    Must be called after the window has an OS handle -- in practice, after
    `update_idletasks()` or on first map. Callers here invoke it right after
    construction plus once on <Map>, because Tk occasionally recreates the
    frame window when a Toplevel is first shown.
    """
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            return
        value = ctypes.c_int(1)
        for attribute in (20, 19):
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:  # noqa: BLE001 - cosmetic; never let it break a window
        pass


APP_ID = "Protege.LocalAssistant.1"


def set_app_id() -> None:
    """Give Windows an explicit AppUserModelID.

    Without one, the taskbar groups this window under the Python interpreter
    and shows Python's icon there no matter what `iconbitmap` says -- the
    window icon and the taskbar icon are resolved separately, and the taskbar
    follows the AppUserModelID. Must be called before the first window is
    created.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001 - cosmetic, and non-Windows has no shell32
        pass


def icon_path():
    from pathlib import Path

    path = Path(__file__).with_name("assets") / "protege.ico"
    return path if path.is_file() else None


def apply_window_chrome(window: tk.Misc) -> None:
    """Dark title bar now and again on first map; app icon if the asset exists."""
    darken_titlebar(window)
    window.bind("<Map>", lambda _e: darken_titlebar(window), add="+")
    try:
        icon = icon_path()
        if icon is not None:
            # default=True so every Toplevel inherits it without repeating.
            window.iconbitmap(default=str(icon))
    except Exception:  # noqa: BLE001 - cosmetic
        pass
