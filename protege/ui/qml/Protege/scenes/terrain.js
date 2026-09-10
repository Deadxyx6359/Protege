.pragma library

.import "world.js" as World
.import "sprites.js" as Sprites

/*!
    Builds the landscape as geometry rather than painting it.

    This started as a \c Canvas, which was wrong in a way worth recording. A
    Canvas rasterises into its own image at the item's size *times the device
    pixel ratio* — 320×180 on a 1.25× display for a 256×144 item. That image
    is then resampled down into the scene's texture, and every sprite pixel
    comes out as an average of its neighbours. The result still had hard edges,
    because the final upscale was nearest-neighbour, but each "pixel" was a
    muddy blend: pixel art in name only.

    Emitting rectangles instead puts the geometry straight into the scene graph
    at the texture's own resolution, with no intermediate raster to resample.

    Two shapes come out:
      \c columns  {x, y, h, c} — vertical runs. Hills, ground, snow.
      \c pixels   {x, y, c}    — single cells. Sprites.

    Both are consumed by a Repeater. The whole layer is cached with
    \c {layer.enabled}, so the cost is paid when the season turns, not per
    frame.
*/

/*! Height of a ridge at column \a i. Two frequencies, so it does not read as
    a sine wave. */
function _ridge(i, base, a, af, b, bf, phase) {
    return Math.round(base - Math.sin(i * af + phase) * a
                           - Math.sin(i * bf + phase * 0.6) * b);
}

/*!
    Build the landscape.

    \a season is one of world.js's season names, \a pal its palette. Layout is
    seeded from fixed integers so the same landscape comes back every launch.
*/
function build(W, H, horizon, season, pal) {
    var columns = [];
    var pixels = [];
    var i, x, y;

    // -- ridges ----------------------------------------------------------
    for (i = 0; i < W; i++) {
        y = _ridge(i, horizon - 16, 8, 0.031, 5, 0.011, 1.7);
        columns.push({ x: i, y: y, h: H - y, c: pal.hillFar });
    }
    for (i = 0; i < W; i++) {
        y = _ridge(i, horizon - 6, 5, 0.047, 3, 0.019, 0.4);
        columns.push({ x: i, y: y, h: H - y, c: pal.hillMid });
    }

    // -- ground ----------------------------------------------------------
    columns.push({ x: 0, y: horizon, h: H - horizon, c: pal.grassDark, w: W });
    columns.push({ x: 0, y: horizon, h: 3, c: pal.grassLight, w: W });

    // A snow blanket laid *over* the ground rather than replacing it, so the
    // grass still shows at the edges and the land keeps its shape.
    if (pal.snow) {
        for (i = 0; i < W; i++) {
            var d = 2 + Math.round(Math.sin(i * 0.09) * 1.5 + 1.5);
            columns.push({ x: i, y: horizon - 1, h: d, c: pal.snow });
        }
    }

    // -- planting --------------------------------------------------------
    var winter = season === "winter";
    var spring = season === "spring";

    var key = {
        L: pal.leafLight, D: pal.leafDark, T: pal.trunk,
        B: pal.blossom, G: pal.grassLight, S: pal.snow || "#ffffff"
    };

    function stamp(sprite, px, py) {
        for (var row = 0; row < sprite.length; row++) {
            var line = sprite[row];
            for (var col = 0; col < line.length; col++) {
                var ch = line.charAt(col);
                if (ch === ".")
                    continue;
                var colour = key[ch];
                if (!colour)
                    continue;
                pixels.push({ x: px + col, y: py + row, c: colour });
            }
        }
    }

    // Spread across the width rather than at fixed coordinates, so the
    // resolution can change without re-placing the wood by hand.
    var count = 9;
    var step = W / count;

    for (i = 0; i < count; i++) {
        var seed = i * 8 + 3;
        var jitter = Math.round(World.rand(seed) * (step * 0.5))
                     - Math.round(step * 0.25);
        var tx = Math.round(i * step + step * 0.2 + jitter);

        // Every third tree is an evergreen. That is what keeps a winter
        // landscape from reading as a dead one.
        var evergreen = (i % 3) === 1;
        var sprite = evergreen ? Sprites.PINE
                               : (winter ? Sprites.TREE_BARE : Sprites.TREE_FULL);
        var ty = horizon - sprite.length + 2;

        stamp(sprite, tx, ty);

        if (spring && !evergreen) {
            // Blossom, scattered deterministically over the canopy.
            var n = 0;
            for (var r = 0; r < sprite.length; r++) {
                for (var c2 = 0; c2 < sprite[r].length; c2++) {
                    var ch2 = sprite[r].charAt(c2);
                    if (ch2 !== "L" && ch2 !== "D")
                        continue;
                    n++;
                    if (World.rand(seed * 31 + n) > 0.78)
                        pixels.push({ x: tx + c2, y: ty + r, c: pal.blossom });
                }
            }
        }
    }

    for (i = 0; i < 14; i++) {
        stamp(Sprites.BUSH,
              Math.round(World.rand(i * 23 + 9) * (W - 6)),
              horizon + 2 + Math.round(World.rand(i * 29 + 4) * 8));
    }

    if (!winter) {
        for (i = 0; i < 22; i++) {
            stamp(Sprites.FLOWER,
                  Math.round(World.rand(i * 31 + 13) * (W - 4)),
                  horizon + 4 + Math.round(World.rand(i * 37 + 6) * 14));
        }
    }

    return { columns: columns, pixels: pixels };
}
