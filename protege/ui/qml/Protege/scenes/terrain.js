.pragma library

.import "world.js" as World
.import "sprites.js" as Sprites

/*!
    Builds the landscape a pixel at a time, then compresses it into horizontal
    runs for the scene graph.

    Two earlier approaches were wrong in ways worth recording.

    A \c Canvas rasterises into its own image at the item's size *times the
    device pixel ratio* — 480×270 on a 1.25× display for a 384×216 item — and
    that image is then resampled into the scene's texture. Every sprite pixel
    arrives as an average of its neighbours: hard-edged, because the final
    upscale is nearest-neighbour, but muddy. Pixel art in name only.

    Emitting one Rectangle per pixel fixes the muddiness and replaces it with
    eighty thousand scene-graph nodes.

    So: paint into a plain grid, then run-length encode each row. Solid bands
    become one rectangle; dithered areas cost more, which is the right price
    to pay in the right place. A detailed scene lands around six thousand runs,
    built once when the season turns and cached with \c {layer.enabled}.
*/

// -- grid ---------------------------------------------------------------

function _grid(w, h) {
    var g = new Array(h);
    for (var y = 0; y < h; y++) {
        g[y] = new Array(w);
        for (var x = 0; x < w; x++)
            g[y][x] = null;
    }
    return g;
}

function _set(g, x, y, c) {
    if (y < 0 || y >= g.length) return;
    var row = g[y];
    if (x < 0 || x >= row.length) return;
    row[x] = c;
}

function _column(g, x, y0, y1, c) {
    for (var y = Math.max(0, Math.round(y0)); y < Math.min(g.length, Math.round(y1)); y++)
        _set(g, x, y, c);
}

/*! Compress the grid into \c {{x, y, w, c}} horizontal runs. */
function _runs(g) {
    var out = [];
    for (var y = 0; y < g.length; y++) {
        var row = g[y];
        var start = -1, colour = null;
        for (var x = 0; x <= row.length; x++) {
            var c = x < row.length ? row[x] : null;
            if (c !== colour) {
                if (colour !== null)
                    out.push({ x: start, y: y, w: x - start, c: colour });
                colour = c;
                start = x;
            }
        }
    }
    return out;
}

// -- pieces -------------------------------------------------------------

/*!
    A mountain range.

    Snow sits above a snowline that itself wobbles, and the boundary is
    dithered rather than cut — a hard line between rock and snow reads as a
    sticker. Slopes facing the light get the lighter rock tone, which is what
    gives the range any shape at all.
*/
function _range(g, W, H, opts) {
    for (var x = 0; x < W; x++) {
        var n = World.fbm(x / opts.scale, opts.seed, 5);

        /*  Raised to a power before use. Plain noise gives rolling hills of
            roughly equal height; exponentiating pushes the low ground down and
            leaves a few summits standing, which is what makes a range read as
            mountains rather than as a wavy band.  */
        var peak = Math.pow(n, opts.sharp || 1.0);
        var top = Math.round(opts.base - peak * opts.relief);

        /*  Which faces catch the light, as a broad low-frequency field.

            Two earlier attempts both produced a skyline of buildings. The
            first used a boolean "is this face lit" with a fixed band beneath
            the ridge, which drew upright rectangles of pale stone. The second
            used the slope derivative, which flips between neighbouring
            columns and striped the range vertically.

            Lighting is a property of large faces, not of single columns, so it
            comes from noise at roughly half the terrain's frequency. Broad
            regions fall into sun or shade together, the way a mountainside
            actually does.  */
        var lightField = World.fbm(x / (opts.scale * 0.55), opts.seed + 500, 3);
        var lit = Math.max(0, Math.min(1, (lightField - 0.42) * 2.6));

        for (var y = top; y < opts.floor; y++) {
            var depth = y - top;
            var c = opts.body;

            if (opts.shaded && depth < 34) {
                // Shading fades out with distance below the ridge, so the
                // lower slopes settle into the body tone with no seam.
                var fade = 1 - depth / 34;
                if (World.dither(x, y, lit * fade * 0.85))
                    c = opts.rockLight;
                else if (World.dither(x, y, fade * 0.42))
                    c = opts.rock;
            }

            /*  Snow sits on summits, not along a contour. Measuring it from
                the ridge top at this column — and only where the column is
                actually high — gives caps that follow the peaks. Measuring it
                from a fixed altitude drew a white stripe straight across the
                whole range.  */
            if (opts.snow && peak > opts.snowAbove) {
                var cap = (peak - opts.snowAbove) / (1 - opts.snowAbove) * opts.snowMax;
                if (depth < cap) {
                    var edge = (cap - depth) / 5;
                    if (edge > 1 || World.dither(x, y, edge))
                        c = opts.snow;
                }
            }

            _set(g, x, y, c);
        }
    }
}

/*!
    A single conifer, drawn as stacked tiers.

    Built rather than stamped from a sprite so that height, width and lean can
    vary per tree. A forest of one identical sprite reads as wallpaper.
*/
function _pine(g, x, base, height, pal, dark) {
    var light = dark ? pal.pineMid : pal.pineLight;
    var mid = dark ? pal.pineDark : pal.pineMid;
    var shade = dark ? pal.pineDeep : pal.pineDark;

    var tiers = Math.max(3, Math.round(height / 3));
    for (var t = 0; t < tiers; t++) {
        var ty = base - height + Math.round(t * height / tiers);
        var spread = Math.round(1 + (t / tiers) * (height / 3.4));
        var rows = Math.max(1, Math.round(height / tiers));
        for (var r = 0; r < rows; r++) {
            var yy = ty + r;
            var wHere = Math.max(0, spread - Math.round((rows - r - 1) * 0.35));
            for (var dx = -wHere; dx <= wHere; dx++) {
                // Light from the left: the left of each tier is lit, the right
                // falls away, and the underside of every tier is dark.
                var c = dx < -wHere * 0.35 ? light : (dx > wHere * 0.4 ? shade : mid);
                if (r === rows - 1)
                    c = shade;
                _set(g, x + dx, yy, c);
            }
        }
    }
    // Trunk, only where it would actually show.
    _column(g, x, base - 2, base + 1, pal.trunkDark);
}

/*!
    A broadleaf tree: a rounded crown over a short trunk.

    Mixed into the conifer forest so the season has somewhere to show. Conifers
    stay green all year — if the whole hillside is pine, autumn has nothing to
    turn, and the only seasonal signal left is the grass.
*/
function _broadleaf(g, x, base, height, pal, dark) {
    var light = dark ? pal.leafMid : pal.leafLight;
    var mid = dark ? pal.leafDark : pal.leafMid;
    var shade = pal.leafDark;

    var r = Math.max(2, Math.round(height * 0.42));
    var cy = base - height + r;

    for (var dy = -r; dy <= r; dy++) {
        // Slightly wider than tall: a perfect circle reads as a lollipop.
        var span = Math.round(Math.sqrt(Math.max(0, r * r - dy * dy)) * 1.15);
        for (var dx = -span; dx <= span; dx++) {
            var c = mid;
            // Light from the upper left.
            if (dx < -span * 0.25 && dy < 0) c = light;
            else if (dx > span * 0.35 || dy > r * 0.45) c = shade;
            _set(g, x + dx, cy + dy, c);
        }
    }
    _column(g, x, cy + r - 1, base + 1, pal.trunkDark);
}

/*!
    A band of forest following a ridge.

    Density and size fall off with distance, and the far edge is dithered into
    the hillside so the treeline is a texture rather than a border.
*/
function _forest(g, W, H, opts) {
    var pal = opts.pal;
    var count = opts.count;
    for (var i = 0; i < count; i++) {
        var t = i / count;
        var x = Math.round(World.rand(opts.seed + i * 3) * (W + 20)) - 10;
        var jitter = World.rand(opts.seed + i * 7 + 1);

        var n = World.fbm(x / opts.scale, opts.ridgeSeed, 5);
        var ridge = Math.round(opts.base - n * opts.relief);

        var base = ridge + Math.round(jitter * opts.depth);
        var height = Math.round(opts.minHeight
                                + World.rand(opts.seed + i * 11 + 5)
                                  * (opts.maxHeight - opts.minHeight));

        // Trees lower down the slope are nearer, so they are drawn larger and
        // darker; the ones on the skyline recede.
        var near = (base - ridge) / Math.max(1, opts.depth);
        height = Math.round(height * (0.75 + near * 0.5));

        // Roughly a third broadleaf. Enough for autumn to read as autumn
        // without the hillside stopping being a conifer forest.
        if (World.rand(opts.seed + i * 13 + 2) < (opts.broadleaf === undefined ? 0.34 : opts.broadleaf))
            _broadleaf(g, x, base, height, pal, near < 0.35);
        else
            _pine(g, x, base, height, pal, near < 0.35);
    }
}

/*!
    The river.

    Widens toward the viewer and carries a lighter band along its far edge,
    which is where the sky reflects.
*/
function _river(g, W, H, opts) {
    var pal = opts.pal;
    for (var y = opts.from; y < opts.to; y++) {
        var t = (y - opts.from) / (opts.to - opts.from);
        var centre = opts.startX + (opts.endX - opts.startX) * t
                     + World.fbm(y / 11, opts.seed, 3) * 18 - 9;
        var halfWidth = opts.width * (0.25 + t * t * 1.9);

        for (var x = Math.round(centre - halfWidth); x <= Math.round(centre + halfWidth); x++) {
            var edge = Math.abs(x - centre) / Math.max(1, halfWidth);
            var c = pal.water;
            if (edge > 0.82) c = pal.waterDark;
            // A broken highlight rather than a solid line: still water is not
            // a mirror, and a continuous stripe reads as a road marking.
            else if (edge < 0.45 && World.rand(x * 3 + y * 17) > 0.55) c = pal.waterLight;
            _set(g, x, y, c);
        }
    }
}

/*!
    The meadow.

    Three grass tones in dithered bands, then stalks, then flowers — each layer
    denser toward the bottom of the frame, which is the whole of the depth cue.
*/
function _meadowShaped(g, W, H, opts) {
    var pal = opts.pal;
    var x, y;

    for (x = 0; x < W; x++) {
        var top = opts.line(x);
        for (y = top; y < H; y++) {
            var t = (y - top) / Math.max(1, H - top);
            // Two dithered transitions: far→mid, then mid→near.
            var c;
            if (t < 0.34) {
                c = World.dither(x, y, 1 - t / 0.34) ? pal.grassLight : pal.grassMid;
            } else if (t < 0.72) {
                c = World.dither(x, y, 1 - (t - 0.34) / 0.38) ? pal.grassMid : pal.grassDark;
            } else {
                c = World.dither(x, y, 1 - (t - 0.72) / 0.28) ? pal.grassDark : pal.grassDeep;
            }
            _set(g, x, y, c);
        }
    }

    // Stalks: short vertical strokes, taller and more frequent toward the
    // foreground. This is most of what makes the field read as grass rather
    // than as a green gradient.
    var stalks = opts.stalks;
    for (var i = 0; i < stalks; i++) {
        var sx = Math.round(World.rand(opts.seed + i * 5) * W);
        var sTop = opts.line(sx);
        var bias = World.rand(opts.seed + i * 5 + 2);
        var sy = Math.round(sTop + Math.pow(bias, 0.55) * (H - sTop));
        var len = 1 + Math.round(World.rand(opts.seed + i * 5 + 3)
                                 * (1 + ((sy - sTop) / Math.max(1, H - sTop)) * 5));
        var tone = World.rand(opts.seed + i * 5 + 4) > 0.5 ? pal.grassLight : pal.grassMid;
        _column(g, sx, sy - len, sy, tone);
    }

    // Flowers. Drawn as a stem with a two-pixel head so they read as flowers
    // rather than as noise, and scaled up toward the viewer.
    var flowers = opts.flowers;
    var palette = pal.flowers;
    for (i = 0; i < flowers; i++) {
        var fx = Math.round(World.rand(opts.seed + 900 + i * 7) * W);
        var fTop = opts.line(fx);
        var fbias = World.rand(opts.seed + 900 + i * 7 + 1);
        var fy = Math.round(fTop + Math.pow(fbias, 0.5) * (H - fTop));
        var depth = (fy - fTop) / Math.max(1, H - fTop);
        var colour = palette[Math.floor(World.rand(opts.seed + 900 + i * 7 + 2)
                                        * palette.length) % palette.length];

        var stem = 1 + Math.round(depth * 4);
        _column(g, fx, fy - stem, fy, pal.grassDark);
        _set(g, fx, fy - stem - 1, colour);
        if (depth > 0.32) {
            _set(g, fx - 1, fy - stem - 1, colour);
            _set(g, fx + 1, fy - stem - 1, colour);
            _set(g, fx, fy - stem - 2, colour);
        }
    }
}

/*! Stamp a character-grid sprite, honouring a colour key. */
function _stamp(g, sprite, x, y, key) {
    for (var row = 0; row < sprite.length; row++) {
        var line = sprite[row];
        for (var col = 0; col < line.length; col++) {
            var ch = line.charAt(col);
            if (ch === ".") continue;
            var c = key[ch];
            if (!c) continue;
            _set(g, x + col, y + row, c);
        }
    }
}

/*!
    What the season puts in the field.

    The point of these is that the landscape should tell you what time of year
    it is from across the room, before you have read the sky. Colour alone does
    not do that — a scarecrow does.
*/
function _props(g, W, H, season, pal, meadowTop) {
    var key = {
        L: pal.leafLight, D: pal.leafDark, T: pal.trunk, K: pal.trunkDark,
        B: pal.blossom, W: "#ffffff", O: "#e8863a", Y: "#f2c14e",
        R: "#c9483a", G: pal.grassDark, S: pal.snowCap, C: "#3a3a4a",
        P: "#d9762e", V: "#5a8f3a", N: "#f4a0b8", E: "#2b2b38"
    };

    var groundY = Math.round(meadowTop + (H - meadowTop) * 0.42);

    switch (season) {
    case "autumn":
        // A scarecrow, and pumpkins in the near field.
        _stamp(g, Sprites.SCARECROW, Math.round(W * 0.66), groundY - 16, key);
        var spots = [[0.20, 0.62], [0.27, 0.70], [0.44, 0.58], [0.79, 0.74], [0.86, 0.63]];
        for (var i = 0; i < spots.length; i++) {
            _stamp(g, Sprites.PUMPKIN,
                   Math.round(W * spots[i][0]),
                   Math.round(meadowTop + (H - meadowTop) * spots[i][1]), key);
        }
        break;

    case "spring":
        _stamp(g, Sprites.BUNNY, Math.round(W * 0.31), groundY + 6, key);
        _stamp(g, Sprites.BUNNY, Math.round(W * 0.37), groundY + 14, key);
        _stamp(g, Sprites.BUNNY, Math.round(W * 0.72), groundY + 22, key);
        break;

    case "winter":
        _stamp(g, Sprites.SNOWMAN, Math.round(W * 0.60), groundY + 4, key);
        break;

    default: // summer
        // A haystack or two. Butterflies are animated and live in the scene.
        _stamp(g, Sprites.HAYSTACK, Math.round(W * 0.24), groundY + 10, key);
        _stamp(g, Sprites.HAYSTACK, Math.round(W * 0.81), groundY + 20, key);
        break;
    }
}

// -- the whole landscape ------------------------------------------------

/*!
    Build the landscape.

    Returns \c {{runs, sway}} — \c runs is the static scene as horizontal
    rectangles, \c sway lists the foreground trees the scene animates in the
    wind. Those are kept out of the grid because the cached layer must not be
    rebuilt sixty times a second.
*/
function build(W, H, season, pal) {
    var g = _grid(W, H);

    /*  The meadow edge is not a horizontal line. It falls to the left, where
        the valley and the river are, and rises to the right, where the field
        comes toward the viewer. That single diagonal is most of what gives the
        frame depth — a straight horizon reads as a stage backdrop.  */
    function meadowLine(x) {
        var t = x / W;
        return Math.round(H * 0.70 - t * H * 0.13
                          + World.fbm(x / 55, 77, 3) * 9 - 4);
    }

    var meadowMid = meadowLine(Math.round(W / 2));

    // ---- ranges, farthest first ----
    _range(g, W, H, {
        base: H * 0.36, relief: 52, scale: 52, seed: 3, sharp: 1.5,
        body: pal.ridgeFar, floor: H
    });

    _range(g, W, H, {
        base: H * 0.44, relief: 66, scale: 34, seed: 11, sharp: 2.1,
        body: pal.ridgeMid, floor: H,
        shaded: true, rock: pal.rock, rockLight: pal.rockLight,
        snow: pal.snowCap, snowAbove: 0.42, snowMax: 26
    });

    _range(g, W, H, {
        base: H * 0.52, relief: 38, scale: 26, seed: 23, sharp: 1.7,
        body: pal.ridgeNear, floor: H
    });

    // ---- forested hills, draped over the near ridge ----
    _forest(g, W, H, {
        pal: pal, count: 300, seed: 101, ridgeSeed: 31,
        base: H * 0.57, relief: 30, scale: 22, depth: 30,
        minHeight: 7, maxHeight: 13, broadleaf: 0.30
    });

    _forest(g, W, H, {
        pal: pal, count: 220, seed: 211, ridgeSeed: 47,
        base: H * 0.64, relief: 22, scale: 17, depth: 24,
        minHeight: 10, maxHeight: 19, broadleaf: 0.40
    });

    // ---- meadow, filling below its own edge ----
    _meadowShaped(g, W, H, {
        pal: pal, line: meadowLine, seed: 401,
        stalks: 1100, flowers: 420
    });

    /*  The river last, so it cuts through the meadow rather than being buried
        under it. An earlier version ran from the treeline *down* to a y above
        where it started, so the loop never executed and there was simply no
        water in the scene.  */
    _river(g, W, H, {
        pal: pal, seed: 61,
        from: Math.round(H * 0.60), to: H,
        startX: W * 0.40, endX: W * 0.02, width: 7
    });

    _props(g, W, H, season, pal, meadowMid);

    /*  Foreground trees are returned rather than painted: they are the only
        things close enough for wind to be visible on, and they have to live
        outside the cached layer to move.  */
    var sway = [
        { x: Math.round(W * 0.92), base: meadowLine(Math.round(W * 0.92)) + 16,
          height: 78, dark: true, lean: 1.0 },
        { x: Math.round(W * 0.99), base: meadowLine(Math.round(W * 0.99)) + 30,
          height: 58, dark: true, lean: 1.2 },
        { x: Math.round(W * 0.85), base: meadowLine(Math.round(W * 0.85)) + 4,
          height: 46, dark: false, lean: 0.85 }
    ];

    return { runs: _runs(g), sway: sway };
}

/*!
    Build one foreground conifer as pixels, for the animated layer.

    Returned in tree-local coordinates with the trunk base at the origin, so
    the scene can lean it without recomputing anything.
*/
function swayTree(height, pal, dark) {
    var g = _grid(Math.round(height * 0.9) * 2 + 6, height + 6);
    var cx = Math.round(g[0].length / 2);
    _pine(g, cx, height + 2, height, pal, dark);

    var pixels = [];
    for (var y = 0; y < g.length; y++) {
        for (var x = 0; x < g[y].length; x++) {
            if (g[y][x] !== null)
                pixels.push({ x: x - cx, y: y - (height + 2), c: g[y][x] });
        }
    }
    return pixels;
}
