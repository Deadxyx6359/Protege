"""Antialiased shapes for the Tk canvas.

Tk's canvas primitives have no antialiasing whatsoever. `create_oval` steps its
edge pixel by pixel, so every circle in the app -- the knowledge web's nodes,
the + button -- arrives visibly staircased, and thin outlines make it worse
because a 2px jagged ring reads as jagged twice.

There is no flag for this. The only way to get a smooth edge is to compute
coverage yourself and hand Tk a finished bitmap.

Coverage is computed from a signed distance rather than by supersampling. For
the shapes here -- discs, rings, diamonds, rounded bars -- the distance to the
edge is a closed form, so a pixel's coverage is `clamp(distance + 0.5, 0, 1)`:
one arithmetic pass instead of sixteen point-in-shape tests, and *smoother*,
because supersampling at 4x can only ever produce seventeen distinct alpha
values while this produces a continuum. Building a 56px sprite drops from
roughly four hundred thousand Python-level calls to a few thousand.

Shapes are composited against the known background colour. The canvas is
always one flat theme colour behind them, so carrying real alpha through to Tk
(which its PhotoImage does not support anyway) would buy nothing.

Every entry point takes the widget that will draw the sprite. That is not
decoration: a PhotoImage belongs to one Tcl interpreter, and `tk.PhotoImage()`
with no master silently attaches to whichever root tkinter happened to create
first. In a process with two interpreters -- which the test suite has, and
which caught this -- the canvas is then handed an image its own interpreter has
never heard of, and the draw fails.

The cache is stored on each interpreter's root widget for the same reason. A
module-level dict would hand interpreter A's images to interpreter B, and would
outlive the interpreter that owns them; hanging it off the root means it is
per-interpreter by construction and is collected along with it.
"""

from __future__ import annotations

import math
import tkinter as tk

from . import theme

# Half the width of the transition band, in pixels. 0.5 is exactly one pixel
# of softening, which is what a box filter over the pixel's own area gives.
_EDGE = 0.5

_ROOT2 = math.sqrt(2.0)

_CACHE_ATTR = "_protege_sprite_cache"


def _cache_for(master: tk.Misc) -> dict[tuple, tk.PhotoImage]:
    """This interpreter's sprite cache, created on first use.

    Keyed by the interpreter rather than the widget: sprites are shared freely
    between the knowledge web and the FAB, but never across interpreters.
    """
    root = master.nametowidget(".")
    cache = getattr(root, _CACHE_ATTR, None)
    if cache is None:
        cache = {}
        setattr(root, _CACHE_ATTR, cache)
    return cache


def _to_rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return int(colour[0:2], 16), int(colour[2:4], 16), int(colour[4:6], 16)


def _blend(top: tuple[int, int, int], bottom: tuple[int, int, int],
           alpha: float) -> tuple[int, int, int]:
    return tuple(int(round(t * alpha + b * (1 - alpha))) for t, b in zip(top, bottom))


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % rgb


def blend(top: str, bottom: str, alpha: float) -> str:
    """`top` laid over `bottom` at `alpha`, as a hex colour Tk will accept."""
    return _hex(_blend(_to_rgb(top), _to_rgb(bottom), alpha))


def _clamp(value: float) -> float:
    if value <= 0.0:
        return 0.0
    if value >= 1.0:
        return 1.0
    return value


# -- coverage functions -------------------------------------------------------
#
# Each returns `coverage(x, y) -> float in [0, 1]` over the sprite's own pixel
# coordinate space, where (x, y) is a pixel centre.


def _disc(cx: float, cy: float, r: float):
    def coverage(x: float, y: float) -> float:
        distance = math.hypot(x - cx, y - cy)
        return _clamp(r - distance + _EDGE)

    return coverage


def _ring(cx: float, cy: float, outer: float, inner: float):
    def coverage(x: float, y: float) -> float:
        distance = math.hypot(x - cx, y - cy)
        outside = _clamp(outer - distance + _EDGE)
        if outside <= 0.0:
            return 0.0
        return min(outside, _clamp(distance - inner + _EDGE))

    return coverage


def _diamond(cx: float, cy: float, r: float, thickness: float | None = None):
    """An L1 ball. Perpendicular distance to its edge is the L1 gap over root 2."""

    def coverage(x: float, y: float) -> float:
        d = abs(x - cx) + abs(y - cy)
        inside = _clamp((r - d) / _ROOT2 + _EDGE)
        if thickness is None or inside <= 0.0:
            return inside
        return min(inside, _clamp((d - (r - thickness)) / _ROOT2 + _EDGE))

    return coverage


def _bar(cx: float, cy: float, half_length: float, half_width: float,
         angle: float, horizontal: bool):
    """A rectangle rotated about (cx, cy) -- one stroke of the + glyph."""
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    def coverage(x: float, y: float) -> float:
        dx, dy = x - cx, y - cy
        # Rotate the sample into the bar's own frame.
        rx = dx * cos_a + dy * sin_a
        ry = -dx * sin_a + dy * cos_a
        along, across = (rx, ry) if horizontal else (ry, rx)
        return _clamp(min(half_length - abs(along), half_width - abs(across)) + _EDGE)

    return coverage


# -- rasterising --------------------------------------------------------------


def _render(master: tk.Misc, size: int, layers, background: str) -> tk.PhotoImage:
    """Composite `layers` -- (coverage_fn, colour), back to front -- onto a bitmap."""
    base = _to_rgb(background)
    pixels = [[base] * size for _ in range(size)]

    for coverage, colour in layers:
        rgb = _to_rgb(colour)
        for row in range(size):
            y = row + 0.5
            line = pixels[row]
            for col in range(size):
                alpha = coverage(col + 0.5, y)
                if alpha > 0.0:
                    line[col] = rgb if alpha >= 1.0 else _blend(rgb, line[col], alpha)

    image = tk.PhotoImage(master=master, width=size, height=size)
    # One `put` per row: a call per pixel is orders of magnitude slower, and
    # this runs during a redraw.
    for row in range(size):
        image.put("{" + " ".join(_hex(p) for p in pixels[row]) + "}", to=(0, row))
    return image


# -- the shapes the app actually draws ----------------------------------------


def _selection_pad(selected: bool, otherwise: int) -> int:
    return max(otherwise, theme.px(16)) if selected else otherwise


def _selection_ring(centre: float, radius: int):
    """The marquee around the selected node.

    Baked into the node's own sprite rather than drawn over it: a separate
    image would be a rectangle of opaque background pixels and would erase the
    node underneath. Everything that overlaps has to share one bitmap.
    """
    outer = radius + theme.px(13)
    return (_ring(centre, centre, outer, outer - 1.2), theme.FG)


def node_sprite(
    master: tk.Misc,
    radius: int,
    *,
    fill: str,
    outline: str,
    width: int = 2,
    glow: bool = False,
    selected: bool = False,
    background: str | None = None,
) -> tk.PhotoImage:
    """A filled, outlined circle -- the knowledge web's topic nodes.

    `glow` adds two faint concentric rings, which is how an unlocked topic is
    distinguished from a locked one. Tk cannot blur, so the halo is faked with
    rings; with a soft edge on each they read as light rather than as circles.
    """
    background = background or theme.BG
    cache = _cache_for(master)
    key = ("node", radius, fill, outline, width, glow, selected, background)
    cached = cache.get(key)
    if cached is not None:
        return cached

    pad = _selection_pad(selected, theme.px(11) if glow else theme.px(3))
    size = radius * 2 + pad * 2
    centre = size / 2

    layers = []
    if glow:
        layers.append((_ring(centre, centre, radius + theme.px(9),
                             radius + theme.px(8)), theme.PURPLE_GHOST))
        layers.append((_ring(centre, centre, radius + theme.px(5),
                             radius + theme.px(4)), theme.PURPLE_DIM))
    layers.append((_disc(centre, centre, radius), fill))
    layers.append((_ring(centre, centre, radius, radius - width), outline))
    if selected:
        layers.append(_selection_ring(centre, radius))

    image = _render(master, size, layers, background)
    cache[key] = image
    return image


def diamond_sprite(master: tk.Misc, radius: int, *, outline: str, fill: str,
                   width: int = 2, selected: bool = False,
                   background: str | None = None) -> tk.PhotoImage:
    """A hollow diamond -- the web's synthetic domain hubs."""
    background = background or theme.BG
    cache = _cache_for(master)
    key = ("diamond", radius, outline, fill, width, selected, background)
    cached = cache.get(key)
    if cached is not None:
        return cached

    pad = _selection_pad(selected, theme.px(3))
    size = radius * 2 + pad * 2
    centre = size / 2
    layers = [
        (_diamond(centre, centre, radius), fill),
        (_diamond(centre, centre, radius, width), outline),
    ]
    if selected:
        layers.append(_selection_ring(centre, radius))
    image = _render(master, size, layers, background)
    cache[key] = image
    return image


def fab_sprite(master: tk.Misc, diameter: int, *, hover: bool, rotated: bool,
               background: str | None = None) -> tk.PhotoImage:
    """The circular + button, with its glyph baked in.

    The glyph is part of the sprite rather than a canvas line so that it is
    antialiased too -- the diagonal strokes of the x, once the + rotates, were
    the worst-looking edges in the window.
    """
    background = background or theme.BG
    cache = _cache_for(master)
    key = ("fab", diameter, hover, rotated, background)
    cached = cache.get(key)
    if cached is not None:
        return cached

    size = diameter
    centre = size / 2
    core = size / 2 - theme.px(6)
    fill = theme.PURPLE_BRIGHT if hover else theme.PURPLE

    layers = [
        (_ring(centre, centre, size / 2, size / 2 - 1.2), theme.PURPLE_GHOST),
        (_ring(centre, centre, size / 2 - theme.px(3),
               size / 2 - theme.px(3) - 1.2), theme.PURPLE_DIM),
        (_disc(centre, centre, core), fill),
        (_ring(centre, centre, core, core - theme.px(2)), theme.PURPLE_BRIGHT),
    ]

    arm = theme.px(10)
    half = max(theme.px(1.5), 1.0)
    angle = math.pi / 4 if rotated else 0.0
    # The glyph is punched out in the background colour rather than drawn in
    # ivory: a hole reads as engraved, which suits a button whose whole job is
    # to look like part of the surface until you reach for it.
    layers.append((_bar(centre, centre, arm, half, angle, True), background))
    layers.append((_bar(centre, centre, arm, half, angle, False), background))

    image = _render(master, size, layers, background)
    cache[key] = image
    return image


def draw_line(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, *,
              colour: str, background: str | None = None, width: int = 1,
              dash: tuple[int, ...] | None = None) -> None:
    """A canvas line with its staircase softened.

    Sprites are the right answer for shapes that repeat; they are the wrong
    answer for these edges. An edge can be hundreds of pixels long, every one
    is a different length and angle, and they all move on every resize -- the
    cache would never hit twice and each redraw would rasterise a megapixel in
    Python.

    So the edge is flanked instead: two dimmer one-pixel lines offset half a
    stroke to either side, filling the notches of the staircase with an
    intermediate colour. It is not coverage antialiasing, but at these
    contrasts the eye cannot tell, and it costs three canvas items.

    Axis-aligned and dashed lines are drawn plain. A vertical line has no
    staircase to hide and a halo would only smear it; a dashed one reads as a
    texture, where flanking strokes turn into visible fringing.
    """
    background = background or theme.BG
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    axis_aligned = abs(dx) < 1 or abs(dy) < 1

    if dash is None and length > 0 and not axis_aligned:
        # Perpendicular unit vector, one flank each side.
        nx, ny = -dy / length, dx / length
        offset = width / 2 + 0.5
        halo = blend(colour, background, 0.45)
        for sign in (-1, 1):
            ox, oy = nx * offset * sign, ny * offset * sign
            canvas.create_line(x1 + ox, y1 + oy, x2 + ox, y2 + oy, fill=halo, width=1)

    canvas.create_line(x1, y1, x2, y2, fill=colour, width=width,
                       **({"dash": dash} if dash else {}))


def clear_cache(master: tk.Misc) -> None:
    """Drop this interpreter's cached sprites, if the palette changes at runtime."""
    _cache_for(master).clear()
