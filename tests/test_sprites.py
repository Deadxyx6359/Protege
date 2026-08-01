"""The antialiased sprite renderer.

Tk cannot antialias anything it draws, so every circle in the app was visibly
staircased. `protege.ui.sprites` works around that by rasterising shapes itself
from a signed distance and handing Tk a finished bitmap.

Two classes of thing are worth testing here. The first is that the edges are
actually graded -- a renderer that quietly produced hard edges would look
exactly like the bug it replaced, and nobody would notice from a green suite.
The second is interpreter ownership, which is where this module's one real bug
lived: `tk.PhotoImage()` with no master attaches to whichever root tkinter
built first, so a sprite handed to a canvas in a *second* interpreter cannot be
drawn. It failed silently, as nineteen tests skipping with "no display
available".
"""

from __future__ import annotations

import tkinter as tk

import pytest

from protege.ui import sprites, theme


@pytest.fixture
def root(clean_root):
    return clean_root


def colours_of(image: tk.PhotoImage) -> set:
    return {
        image.get(x, y)
        for y in range(image.height())
        for x in range(image.width())
    }


# --- edges are actually soft -------------------------------------------------


def test_a_node_edge_is_graded_not_stepped(root):
    """The whole point. A hard edge means we reimplemented `create_oval`.

    A disc drawn in one colour on one background can only ever contain two
    colours if it is aliased. Every additional colour is a partially covered
    pixel, which is what makes the curve read as smooth.
    """
    image = sprites.node_sprite(root, 24, fill=theme.PURPLE,
                                outline=theme.PURPLE, width=1)
    assert len(colours_of(image)) > 8, (
        "the circle has almost no intermediate colours, so its edge is a "
        "staircase -- the renderer is not antialiasing"
    )


def test_intermediate_pixels_lie_between_fill_and_background(root):
    """Soft pixels must be blends, not stray colours from a rounding bug."""
    image = sprites.node_sprite(root, 20, fill="#ffffff", outline="#ffffff",
                                width=1, background="#000000")
    for r, g, b in colours_of(image):
        assert r == g == b, "a white-on-black disc produced a colour cast"


def test_a_diamond_edge_is_graded_too(root):
    """Hubs are diamonds, and a 45-degree edge is the worst case for aliasing.

    Counting colours is the wrong test here. A diamond's edges are all at
    exactly 45 degrees, so every boundary pixel has the *same* partial
    coverage and correct antialiasing produces one uniform half-tone band, not
    a spread. What matters is that the band exists at all.
    """
    outline, background = "#ffffff", "#000000"
    image = sprites.diamond_sprite(root, 18, outline=outline, fill=background,
                                   background=background)
    greys = {c[0] for c in colours_of(image)}
    assert greys - {0, 255}, (
        "the diamond is pure black and white, so its 45-degree edges are a "
        "staircase with no partial coverage at all"
    )


def test_the_fab_glyph_is_part_of_the_sprite(root):
    """The + is punched out in the sprite, not drawn as two aliased lines.

    Rotating it to an x is what exposed this: diagonal `create_line` strokes
    were the roughest edges in the window.
    """
    plus = sprites.fab_sprite(root, 56, hover=False, rotated=False)
    cross = sprites.fab_sprite(root, 56, hover=False, rotated=True)
    assert colours_of(plus) != colours_of(cross) or plus is not cross
    # The glyph is cut in the background colour, so the centre is background.
    background = tuple(int(theme.BG.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    assert plus.get(28, 28) == background


# --- caching -----------------------------------------------------------------


def test_identical_requests_share_one_image(root):
    """Rasterising is Python-level pixel work; a redraw must not repeat it."""
    first = sprites.node_sprite(root, 22, fill=theme.PURPLE, outline=theme.PURPLE_BRIGHT)
    second = sprites.node_sprite(root, 22, fill=theme.PURPLE, outline=theme.PURPLE_BRIGHT)
    assert first is second


def test_selection_changes_the_cache_key(root):
    """A selected node carries a marquee, so it cannot reuse the plain sprite."""
    plain = sprites.node_sprite(root, 22, fill=theme.PURPLE, outline=theme.PURPLE_BRIGHT)
    picked = sprites.node_sprite(root, 22, fill=theme.PURPLE,
                                 outline=theme.PURPLE_BRIGHT, selected=True)
    assert plain is not picked
    assert picked.width() > plain.width(), "the marquee needs room outside the node"


def test_clear_cache_forces_a_rebuild(root):
    first = sprites.node_sprite(root, 15, fill=theme.PURPLE, outline=theme.PURPLE)
    sprites.clear_cache(root)
    assert sprites.node_sprite(root, 15, fill=theme.PURPLE, outline=theme.PURPLE) is not first


# --- interpreter ownership: the bug this module actually shipped -------------


def test_a_sprite_belongs_to_the_interpreter_that_will_draw_it(root):
    """The regression test for the real defect.

    `tk.PhotoImage(...)` with no master binds to tkinter's *default* root --
    whichever one was created first. A ProtegeWindow is its own `tk.Tk`, so
    every sprite built for one belonged to the wrong interpreter and
    `create_image` failed with "image doesn't exist". The UI fixtures caught
    the TclError and skipped with "no display available", so the suite stayed
    green while nineteen tests quietly stopped running.

    Asserted as an invariant rather than by standing up a second `tk.Tk`:
    pytest's default fd-level capture makes a second interpreter fail to
    initialise on its own (`-s` and `--capture=sys` are fine), so a test built
    that way would fail for a reason that has nothing to do with this code.
    `image.tk` is the interpreter the image lives in, and it has to be the
    canvas's.
    """
    canvas = tk.Canvas(root, width=80, height=80)
    image = sprites.node_sprite(canvas, 20, fill=theme.PURPLE,
                                outline=theme.PURPLE_BRIGHT, glow=True)
    assert image.tk is canvas.tk, (
        "the sprite was created against tkinter's default root instead of the "
        "widget that draws it -- it will not render in any other interpreter"
    )
    canvas.create_image(40, 40, image=image)
    root.update_idletasks()


def test_the_cache_lives_on_the_interpreter_not_the_module(root):
    """A module-level dict would hand interpreter A's images to interpreter B.

    Hanging it off the root widget makes the cache per-interpreter by
    construction, and lets it be collected with the interpreter it belongs to.
    """
    sprites.clear_cache(root)
    sprites.node_sprite(root, 19, fill=theme.PURPLE, outline=theme.PURPLE)
    cache = getattr(root.nametowidget("."), "_protege_sprite_cache", None)
    assert cache, "the sprite was cached somewhere other than the interpreter root"


# --- lines -------------------------------------------------------------------


def test_a_diagonal_line_is_flanked(root):
    """Edges run at arbitrary angles and are too long to sprite, so they are
    softened with two dimmer neighbours instead."""
    canvas = tk.Canvas(root, width=200, height=200)
    sprites.draw_line(canvas, 10, 10, 150, 90, colour=theme.PURPLE, width=2)
    assert len(canvas.find_all()) == 3


def test_an_axis_aligned_line_is_left_alone(root):
    """A vertical line has no staircase; a halo would only smear it."""
    canvas = tk.Canvas(root, width=200, height=200)
    sprites.draw_line(canvas, 10, 10, 10, 150, colour=theme.PURPLE, width=2)
    sprites.draw_line(canvas, 10, 10, 150, 10, colour=theme.PURPLE, width=2)
    assert len(canvas.find_all()) == 2


def test_a_dashed_line_is_left_alone(root):
    """Flanking a dash pattern produces visible fringing, not smoothing."""
    canvas = tk.Canvas(root, width=200, height=200)
    sprites.draw_line(canvas, 10, 10, 150, 90, colour=theme.PURPLE_GHOST, dash=(2, 5))
    assert len(canvas.find_all()) == 1


def test_a_zero_length_line_does_not_divide_by_zero(root):
    """Two topics can land on the same point mid-layout."""
    canvas = tk.Canvas(root, width=200, height=200)
    sprites.draw_line(canvas, 40, 40, 40, 40, colour=theme.PURPLE)
    assert len(canvas.find_all()) == 1


def test_the_halo_sits_between_the_line_and_the_background(root):
    blended = sprites.blend("#ffffff", "#000000", 0.5)
    assert blended in ("#7f7f7f", "#808080")
