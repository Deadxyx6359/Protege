.pragma library

/*!
    Pixel sprites, written the way sprites have always been written: a grid of
    characters, one per pixel, with a key that maps each to a palette slot.

    Authoring them as data rather than as drawing code means a season's planting
    is legible at a glance and editable without touching the renderer — and the
    palette does the seasonal work, so one tree shape serves spring, summer and
    autumn.

    Key
      .  transparent      L  leaf, light      D  leaf, dark
      T  trunk            B  blossom / fruit  G  grass highlight
      S  snow             K  dark accent
*/

var TREE_FULL = [
    "...DDD..",
    "..DLLLD.",
    ".DLLLLLD",
    "DLLLLLLD",
    "DLLLDLLD",
    ".DLLLLD.",
    "..DLLD..",
    "...TT...",
    "...TT...",
    "..TTTT.."
];

/*! Winter, or any deciduous tree without its leaves. The canopy becomes
    branch-work in trunk colour rather than disappearing. */
var TREE_BARE = [
    "........",
    "..T...T.",
    "...T.T..",
    "..T.T.T.",
    "...TTT..",
    "....T...",
    "...TT...",
    "...TT...",
    "...TT...",
    "..TTTT.."
];

/*! Evergreen. Keeps its colour through winter, which is what stops a winter
    landscape reading as a dead one. */
var PINE = [
    "...D...",
    "..DLD..",
    ".DLLLD.",
    "..DLD..",
    ".DLLLD.",
    "DLLLLLD",
    "..DLD..",
    ".DLLLD.",
    "DLLLLLD",
    "...T...",
    "..TTT.."
];

var BUSH = [
    ".DLD.",
    "DLLLD",
    "DLLLD",
    ".DDD."
];

var FLOWER = [
    ".B.",
    "BLB",
    ".T."
];

var GRASS_TUFT = [
    "G.G",
    "GGG"
];

/*! Sprites keyed by name, so a scene can pick by season without a switch. */
var ALL = {
    treeFull: TREE_FULL,
    treeBare: TREE_BARE,
    pine: PINE,
    bush: BUSH,
    flower: FLOWER,
    grass: GRASS_TUFT
};

function width(sprite) { return sprite[0].length; }
function height(sprite) { return sprite.length; }

/*!
    Paint \a sprite onto a 2D canvas context at \a x, \a y.

    \a colours maps the key letters to CSS colours; a letter with no entry is
    skipped, which is how one sprite drops its blossom outside spring without
    needing a second copy.
*/
function draw(ctx, sprite, x, y, colours) {
    for (var row = 0; row < sprite.length; row++) {
        var line = sprite[row];
        for (var col = 0; col < line.length; col++) {
            var key = line.charAt(col);
            if (key === ".")
                continue;
            var colour = colours[key];
            if (!colour)
                continue;
            ctx.fillStyle = colour;
            ctx.fillRect(x + col, y + row, 1, 1);
        }
    }
}

/*! Scatter a few blossom pixels over a canopy. Spring only.

    Deterministic in \a seed so the same tree blossoms the same way every
    launch — the landscape has to be the same place each time you open it.
*/
function blossom(ctx, sprite, x, y, colour, seed) {
    var n = 0;
    for (var row = 0; row < sprite.length; row++) {
        var line = sprite[row];
        for (var col = 0; col < line.length; col++) {
            var key = line.charAt(col);
            if (key !== "L" && key !== "D")
                continue;
            n++;
            var r = Math.sin((seed + n) * 12.9898) * 43758.5453;
            if ((r - Math.floor(r)) > 0.78) {
                ctx.fillStyle = colour;
                ctx.fillRect(x + col, y + row, 1, 1);
            }
        }
    }
}
