.pragma library

.import "world.js" as World
.import "sprites.js" as Sprites

/*!
    The landscape, composed as a stack of bands.

    This replaces an approach that was scattering objects and hoping: trees
    placed by a seed with no knowledge of the ground beneath them, so some
    floated; a river drawn over whatever was already there, so it ran through
    trunks; mountains that faded with distance while the trees standing on them
    did not, because the trees were a separate thing that had never heard of
    haze.

    Every one of those is the same mistake — simulating parts instead of
    composing a picture. So the scene is now a short, ordered list of **bands**,
    back to front. Each band owns:

      - a \c skyline(x), which is its whole silhouette. Trees are not objects
        standing on a band; they are bumps in the band's own outline. That is
        why nothing can float and why a treeline recedes with the hill it is
        part of.
      - a single base colour, mixed toward the horizon haze by its distance.
        One rule, applied uniformly, and atmospheric perspective falls out.
      - a fill that runs from the skyline down to the band behind it.

    Detail is spent at one focal point per season, not spread evenly. An even
    scattering of interest is what makes a picture read as texture.
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

/*! Compress the grid into \c {{x, y, w, c}} horizontal runs.

    Flat bands become one rectangle per row, which is the whole reason the
    scene can afford to be a grid at all. */
function runs(g) {
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

// -- silhouettes --------------------------------------------------------

/*!
    A ridge line.

    Noise raised to a power, so a few summits stand rather than everything
    rolling at the same height.
*/
function ridge(cfg) {
    return function (x) {
        var n = World.fbm(x / cfg.scale, cfg.seed, 5);
        return Math.round(cfg.base - Math.pow(n, cfg.sharp || 1) * cfg.relief);
    };
}

/*!
    A treeline: a ground contour with trees bitten out of the sky above it.

    Trees are placed once, then the silhouette is sampled per column as the
    tallest tree covering that column. Because the result is one outline in one
    colour, a distant wood reads as a texture on a hillside instead of as a row
    of individual sprites — and it fades with the hill automatically.
*/
function treeline(cfg) {
    var ground = ridge(cfg);

    // Place the wood once. Spacing varies so the edge never falls into rhythm.
    var trees = [];
    var x = -8;
    var i = 0;
    while (x < cfg.width + 8) {
        var r1 = World.rand(cfg.seed * 31 + i * 7 + 1);
        var r2 = World.rand(cfg.seed * 31 + i * 7 + 2);
        var r3 = World.rand(cfg.seed * 31 + i * 7 + 3);

        var h = cfg.minHeight + r1 * (cfg.maxHeight - cfg.minHeight);
        trees.push({
            cx: x,
            half: Math.max(1.2, h * (0.30 + r2 * 0.22)),
            h: h,
            // A minority are broadleaf: rounded rather than pointed. Mixing
            // the two profiles is what stops a treeline reading as a saw.
            round: r3 < (cfg.broadleaf === undefined ? 0.28 : cfg.broadleaf)
        });

        x += cfg.spacing * (0.55 + World.rand(cfg.seed * 31 + i * 7 + 4) * 0.9);
        i++;
    }

    return function (px) {
        var top = ground(px);
        for (var t = 0; t < trees.length; t++) {
            var tr = trees[t];
            var d = Math.abs(px - tr.cx);
            if (d > tr.half) continue;
            var k = 1 - d / tr.half;
            var lift = tr.round ? tr.h * Math.sqrt(Math.max(0, 1 - (d / tr.half) * (d / tr.half)))
                                : tr.h * k;
            var candidate = ground(tr.cx) - lift;
            if (candidate < top) top = candidate;
        }
        return Math.round(top);
    };
}

/*! A flat line, for the sea and the sand. */
function level(y) {
    return function () { return Math.round(y); };
}

// -- rendering ----------------------------------------------------------

/*!
    Fill one band from its skyline down to \a floor.

    \a shade is optional and adds a second tone along the top edge — used only
    on the near bands, where a completely flat shape starts to look like paper.
*/
function _band(g, W, H, sky, floor, colour, shade, shadeDepth) {
    for (var x = 0; x < W; x++) {
        var top = sky(x);
        for (var y = Math.max(0, top); y < Math.min(H, floor); y++) {
            var c = colour;
            if (shade && (y - top) < shadeDepth)
                c = shade;
            _set(g, x, y, c);
        }
    }
}

/*!
    Snow caps, measured down from the ridge at each column.

    Only where the ridge is genuinely high — measuring from a fixed altitude
    draws a white stripe straight across a range regardless of its shape.
*/
function _caps(g, W, sky, reference, colour, above, depth) {
    for (var x = 0; x < W; x++) {
        var top = sky(x);
        var height = (reference - top) / reference;
        if (height < above) continue;
        var cap = (height - above) / (1 - above) * depth;
        for (var y = top; y < top + cap; y++) {
            var edge = (top + cap - y) / 4;
            if (edge > 1 || World.dither(x, y, edge))
                _set(g, x, y, colour);
        }
    }
}

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

// -- the composition ----------------------------------------------------

/*!
    Build the landscape.

    \a opts carries \c season, \c pal, and \c haze — the colour of the sky at
    the horizon, which every band is mixed toward by its distance. Passing the
    live haze in is what lets distant ridges go pink at sunset without any band
    knowing what time it is.

    Returns \c {{runs, sea, focal, sway}}.
*/
function build(W, H, opts) {
    var g = _grid(W, H);
    var pal = opts.pal;
    var haze = opts.haze;
    var season = opts.season;

    /*  One horizon, and everything stacks by depth from it. The sea meets the
        sky here; the far shore sits on it; the beach and the meadow come
        forward from it.  */
    var horizon = Math.round(H * 0.44);
    var seaFloor = Math.round(H * 0.60);
    var sandFloor = Math.round(H * 0.68);

    /*  Atmospheric perspective, as one rule. `depth` runs 0 at the horizon to
        1 in the foreground; everything is mixed toward the haze by how far
        away it is. Because a band's trees are part of its silhouette and share
        its colour, they recede with it — which the previous version got wrong,
        fading the mountains while leaving their forests fully saturated.  */
    function far(colour, depth) {
        return World.mix(haze, colour, 0.18 + depth * 0.82);
    }

    // ---- distant ranges, on the far shore -------------------------------

    var farRidge = ridge({ base: horizon - 2, relief: 30, scale: 44, seed: 3, sharp: 1.6 });
    _band(g, W, H, farRidge, horizon + 1, far(pal.ridgeFar, 0.10));

    var midRidge = ridge({ base: horizon + 1, relief: 40, scale: 28, seed: 11, sharp: 2.2 });
    _band(g, W, H, midRidge, horizon + 1, far(pal.ridgeMid, 0.22));
    _caps(g, W, midRidge, horizon + 1, far(pal.snowCap, 0.30), 0.46, 11);

    // ---- the far shore: a wooded headland sitting on the water ----------

    var shore = treeline({
        base: horizon + 2, relief: 9, scale: 20, seed: 23, sharp: 1.3,
        width: W, spacing: 3.1, minHeight: 3, maxHeight: 8, broadleaf: 0.30
    });
    _band(g, W, H, shore, horizon + 2, far(pal.ridgeNear, 0.34));

    // ---- the sea --------------------------------------------------------
    //
    // Flat colour here; the movement is a separate animated layer, because a
    // sea baked into a cached texture cannot move.
    _band(g, W, H, level(horizon + 2), seaFloor, far(pal.water, 0.46));

    // ---- the beach ------------------------------------------------------
    //
    // Two tones: wet sand along the waterline, dry sand below it. That single
    // division is what makes a strip of tan read as a beach.
    _band(g, W, H, level(seaFloor), seaFloor + 3, far(pal.sandWet, 0.58));
    _band(g, W, H, level(seaFloor + 3), sandFloor, far(pal.sand, 0.66));

    // ---- the meadow -----------------------------------------------------

    var meadow = function (x) {
        return Math.round(sandFloor + World.fbm(x / 40, 91, 2) * 3 - 1);
    };
    _band(g, W, H, meadow, H, pal.grassDark, pal.grassMid, 6);

    /*  A near band across the very bottom, darker than the meadow. It gives
        the frame a floor and stops the composition sliding off the edge —
        the same job a repoussoir does in a painting.  */
    var apron = function (x) {
        return Math.round(H * 0.86 + World.fbm(x / 26, 55, 3) * 6 - 3);
    };
    _band(g, W, H, apron, H, pal.grassDeep);

    // ---- the focal point ------------------------------------------------

    var focal = _focal(g, W, H, season, pal, {
        horizon: horizon, seaFloor: seaFloor, sandFloor: sandFloor,
        meadow: meadow, apron: apron, far: far
    });

    /*  Foreground trees are returned rather than painted: they are the only
        things near enough for wind to show on. Two, not nine — a silhouette
        works by being singular.  */
    var sway = [
        { x: Math.round(W * 0.88), base: Math.round(H * 0.90), height: 46, lean: 1.0 },
        { x: Math.round(W * 0.965), base: Math.round(H * 0.97), height: 34, lean: 1.2 }
    ];

    return {
        runs: runs(g),
        sea: { top: horizon + 2, bottom: seaFloor },
        horizon: horizon,
        sandFloor: sandFloor,
        focal: focal,
        sway: sway
    };
}

/*!
    What the season puts in the picture.

    One subject, placed deliberately, rather than a scattering. The autumn
    entry is the odd one out: it returns a second, quieter thing for the scene
    to reveal only occasionally.
*/
function _focal(g, W, H, season, pal, geom) {
    var key = {
        L: pal.leafLight, D: pal.leafDark, T: pal.trunk, K: pal.trunkDark,
        B: pal.blossom, W: "#ffffff", O: "#e8863a", Y: "#f2c14e",
        R: "#c9483a", G: pal.grassDark, S: pal.snowCap, C: "#2a2a34",
        P: "#d9762e", V: "#5a8f3a", N: "#f4a0b8", E: "#16161e",
        A: "#e04a3a", U: "#3d7fc4", M: "#f6f2e6", X: "#8a1c1c",
        Z: "#c8d8e8", Q: "#ffd45e"
    };

    var beachY = geom.seaFloor + 4;
    var groundY = Math.round(H * 0.80);

    switch (season) {
    case "spring":
        // A single blossoming tree, off-centre, with the bunnies beneath it.
        _stamp(g, Sprites.BLOSSOM_TREE, Math.round(W * 0.18), groundY - 26, key);
        _stamp(g, Sprites.BUNNY, Math.round(W * 0.26), groundY + 2, key);
        _stamp(g, Sprites.BUNNY, Math.round(W * 0.31), groundY + 7, key);
        return { kind: "spring" };

    case "summer":
        // Parasols on the sand — the one thing that says summer beach.
        _stamp(g, Sprites.PARASOL, Math.round(W * 0.22), beachY - 7, key);
        _stamp(g, Sprites.PARASOL, Math.round(W * 0.34), beachY - 5, key);
        _stamp(g, Sprites.PARASOL, Math.round(W * 0.64), beachY - 6, key);
        return { kind: "summer" };

    case "autumn":
        /*  Pumpkins and a scarecrow, and then the quiet part.

            The horror is deliberately withheld. A monster in frame is a
            cartoon; something that is only *sometimes* there, that you are not
            sure you saw, is the effect being aimed at. The scene reveals the
            watcher on a slow cycle and never draws attention to it.  */
        _stamp(g, Sprites.SCARECROW, Math.round(W * 0.70), groundY - 14, key);
        _stamp(g, Sprites.PUMPKIN, Math.round(W * 0.20), groundY + 6, key);
        _stamp(g, Sprites.PUMPKIN, Math.round(W * 0.27), groundY + 11, key);
        _stamp(g, Sprites.PUMPKIN, Math.round(W * 0.80), groundY + 9, key);
        return {
            kind: "autumn",
            watcher: { x: Math.round(W * 0.45), y: geom.sandFloor - 12 },
            eyes: [
                { x: Math.round(W * 0.12), y: geom.horizon - 4 },
                { x: Math.round(W * 0.57), y: geom.horizon - 2 },
                { x: Math.round(W * 0.86), y: geom.horizon - 6 }
            ]
        };

    default: // winter
        // A lit tree and a cabin: warmth, which is the whole point of winter.
        _stamp(g, Sprites.CABIN, Math.round(W * 0.72), groundY - 12, key);
        _stamp(g, Sprites.XMAS_TREE, Math.round(W * 0.20), groundY - 18, key);
        _stamp(g, Sprites.SNOWMAN, Math.round(W * 0.33), groundY + 2, key);
        return {
            kind: "winter",
            lights: [
                { x: Math.round(W * 0.20) + 3, y: groundY - 14 },
                { x: Math.round(W * 0.20) + 8, y: groundY - 10 },
                { x: Math.round(W * 0.20) + 2, y: groundY - 6 },
                { x: Math.round(W * 0.20) + 9, y: groundY - 3 },
                { x: Math.round(W * 0.20) + 5, y: groundY - 17 }
            ],
            windows: [
                { x: Math.round(W * 0.72) + 3, y: groundY - 7 },
                { x: Math.round(W * 0.72) + 8, y: groundY - 7 }
            ]
        };
    }
}

/*!
    Build one foreground conifer as pixels, in tree-local coordinates.

    A near silhouette, so it is a single dark tone rather than a shaded
    sprite — detail this close to the viewer competes with the focal point.
*/
function swayTree(height, colour) {
    var half = Math.max(2, Math.round(height * 0.26));
    var pixels = [];
    for (var row = 0; row < height; row++) {
        var k = row / height;
        // Slight concavity: a straight-sided triangle reads as a traffic cone.
        var spread = Math.round(half * Math.pow(k, 0.78));
        for (var dx = -spread; dx <= spread; dx++)
            pixels.push({ x: dx, y: row - height, c: colour });
    }
    for (var t = 0; t < 3; t++) {
        pixels.push({ x: 0, y: -t, c: colour });
        pixels.push({ x: -1, y: -t, c: colour });
    }
    return pixels;
}
