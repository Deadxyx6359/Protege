"""Generate the Akira application icon: a tree, in the theme palette.

Run: python tools/make_icon.py

Writes `akira/ui/assets/akira.ico` as a genuine multi-resolution ICO
(16/24/32/48/64/128/256) so Windows picks the right size for the taskbar, the
title bar, and Explorer instead of scaling one bitmap badly.

Written with only the standard library -- no Pillow. The project's dependency
policy requires justifying every package, and a build-time-only image library
is not worth a permanent entry in requirements.txt for one asset. So the icon
is drawn into raw BGRA pixel buffers and the ICO container is assembled by
hand; the format is a small header plus PNG-or-BMP payloads, and PNG is easy
enough to emit with `zlib`.

The design: a trunk splitting into branches with glowing nodes at the tips --
literally the knowledge web, which is what the application is about. Purple
gradient on transparent, so it reads on both light and dark taskbars.
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "akira" / "ui" / "assets" / "akira.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Theme palette, as RGB.
# The badge is near-opaque and dark rather than a soft halo: a translucent
# glow disappears on a dark taskbar and washes the mark out on a light one,
# whereas a solid dark disc gives the purple tree the same contrast everywhere.
BADGE = (0x12, 0x08, 0x22)
BADGE_EDGE = (0x5A, 0x18, 0x9A)
TRUNK = (0x7B, 0x2C, 0xBF)
BRANCH = (0x9D, 0x4E, 0xDD)
NODE = (0xC7, 0x7D, 0xFF)
NODE_HOT = (0xE7, 0xD7, 0xFF)


class Canvas:
    """A tiny RGBA raster with the two primitives this icon needs.

    Supersampled by the caller (drawn at 4x then box-filtered down), which is
    what keeps the diagonal branches from looking like staircases at 16px.
    """

    def __init__(self, size: int) -> None:
        self.size = size
        self.px = bytearray(size * size * 4)

    def _blend(self, x: int, y: int, rgb: tuple[int, int, int], alpha: float) -> None:
        if not (0 <= x < self.size and 0 <= y < self.size) or alpha <= 0:
            return
        i = (y * self.size + x) * 4
        alpha = min(1.0, alpha)
        old_a = self.px[i + 3] / 255
        new_a = alpha + old_a * (1 - alpha)
        if new_a <= 0:
            return
        for c in range(3):
            src = rgb[c] / 255
            dst = self.px[i + c] / 255
            out = (src * alpha + dst * old_a * (1 - alpha)) / new_a
            self.px[i + c] = int(round(out * 255))
        self.px[i + 3] = int(round(new_a * 255))

    def disc(self, cx: float, cy: float, r: float, rgb: tuple[int, int, int], alpha: float = 1.0) -> None:
        for y in range(int(cy - r) - 1, int(cy + r) + 2):
            for x in range(int(cx - r) - 1, int(cx + r) + 2):
                d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
                if d <= r:
                    self._blend(x, y, rgb, alpha)

    def line(self, x0: float, y0: float, x1: float, y1: float, width: float,
             rgb: tuple[int, int, int], alpha: float = 1.0) -> None:
        steps = int(max(abs(x1 - x0), abs(y1 - y0)) * 2) + 2
        for step in range(steps + 1):
            t = step / steps
            self.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, width / 2, rgb, alpha)

    def downsample(self, factor: int) -> "Canvas":
        out = Canvas(self.size // factor)
        for y in range(out.size):
            for x in range(out.size):
                r = g = b = a = 0
                for dy in range(factor):
                    for dx in range(factor):
                        i = ((y * factor + dy) * self.size + (x * factor + dx)) * 4
                        pa = self.px[i + 3]
                        r += self.px[i] * pa
                        g += self.px[i + 1] * pa
                        b += self.px[i + 2] * pa
                        a += pa
                j = (y * out.size + x) * 4
                if a:
                    out.px[j] = r // a
                    out.px[j + 1] = g // a
                    out.px[j + 2] = b // a
                out.px[j + 3] = a // (factor * factor)
        return out

    def to_png(self) -> bytes:
        raw = bytearray()
        stride = self.size * 4
        for y in range(self.size):
            raw.append(0)  # filter type: none
            raw.extend(self.px[y * stride:(y + 1) * stride])

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

        header = struct.pack(">IIBBBBB", self.size, self.size, 8, 6, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


def draw_tree(size: int) -> Canvas:
    """A branching tree with glowing tips, scaled to `size`."""
    c = Canvas(size)
    s = size / 256  # design at 256, scale everything

    def px(v: float) -> float:
        return v * s

    # Dark badge with a purple rim.
    c.disc(px(128), px(128), px(124), BADGE_EDGE, 1.0)
    c.disc(px(128), px(128), px(118), BADGE, 1.0)

    # Trunk, tapering upward.
    c.line(px(128), px(214), px(128), px(146), px(24), TRUNK)
    c.line(px(128), px(176), px(128), px(136), px(17), BRANCH)

    # Two generations of branches. Angles chosen so the silhouette stays
    # legible when the whole thing is 16 pixels wide.
    primaries = ((-52, 74), (52, 74), (-24, 92), (24, 92))
    tips: list[tuple[float, float]] = []
    for degrees, length in primaries:
        rad = math.radians(degrees - 90)
        x1 = px(128) + math.cos(rad) * px(length)
        y1 = px(150) + math.sin(rad) * px(length)
        c.line(px(128), px(150), x1, y1, px(13), BRANCH)

        for delta in (-26, 26):
            rad2 = math.radians(degrees + delta - 90)
            x2 = x1 + math.cos(rad2) * px(34)
            y2 = y1 + math.sin(rad2) * px(34)
            c.line(x1, y1, x2, y2, px(8), BRANCH)
            tips.append((x2, y2))

    # Glowing nodes at the tips -- the unlocked-topic look from the knowledge web.
    for x, y in tips:
        c.disc(x, y, px(15), NODE, 0.28)
        c.disc(x, y, px(9), NODE, 0.85)
        c.disc(x, y, px(5), NODE_HOT)

    # Root node.
    c.disc(px(128), px(232), px(14), NODE, 0.5)
    c.disc(px(128), px(232), px(8), NODE_HOT)
    return c


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images: list[tuple[int, bytes]] = []
    for size in SIZES:
        # 4x supersample, then box-filter -- the cheap way to antialias.
        images.append((size, draw_tree(size * 4).downsample(4).to_png()))

    # ICO container: 6-byte header, 16-byte directory entry per image, payloads.
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries = bytearray()
    payloads = bytearray()
    for size, png in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,  # 0 means 256 in the ICO format
            0 if size >= 256 else size,
            0, 0, 1, 32, len(png), offset,
        )
        payloads += png
        offset += len(png)

    OUT.write_bytes(header + bytes(entries) + bytes(payloads))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(images)} sizes)")


if __name__ == "__main__":
    build()
