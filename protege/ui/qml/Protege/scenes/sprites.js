.pragma library

/*!
    Pixel sprites, written the way sprites have always been written: a grid of
    characters, one per pixel, with a key mapping each to a palette slot.

    Only things with a *shape* live here. Trees, hills and grass are generated
    in terrain.js, because they need to vary — a forest built from one stamped
    sprite reads as wallpaper. These are the objects that should look the same
    every time you see them.

    Their job is to say what time of year it is from across the room, before
    you have read the sky. Colour alone does not do that; a scarecrow does.

    Key
      .  transparent   W  white         E  darkest (eyes, detail)
      O  orange        P  pumpkin       Y  yellow / straw
      R  red cloth     K  trunk dark    C  charcoal
      V  stem green    G  grass dark    S  snow
      N  pink          T  trunk         L/D  leaf light / dark   B  blossom
*/

/*! Autumn. Five pixels across, so it still reads at a distance. */
var PUMPKIN = [
    "..V..",
    ".OPO.",
    "OPPPO",
    "OPPPO",
    ".OPO."
];

/*! Autumn. The single clearest "it is October" signal available. */
var SCARECROW = [
    "....OOO....",
    "...OOOOO...",
    "....YYY....",
    "...YEYEY...",
    "....YYY....",
    "..YYYYYYY..",
    "RRRRRRRRRRR",
    "..RRRRRRR..",
    "...RRRRR...",
    "...RRRRR...",
    "...RYYYR...",
    "....KKK....",
    "....KKK....",
    "....KKK....",
    "....KKK....",
    "....KKK...."
];

/*! Spring. */
var BUNNY = [
    "W.W....",
    "W.W....",
    "WWWW...",
    "WEWWWW.",
    "WWWWWWW",
    ".W...W."
];

/*! Winter. */
var SNOWMAN = [
    "..CCC..",
    "..CCC..",
    ".WWWWW.",
    ".WEWEW.",
    ".WWWWW.",
    "WWWWWWW",
    "WWWWWWW",
    "WWWWWWW",
    ".WWWWW."
];

/*! Summer. Cut hay, which is what a summer field actually has in it. */
var HAYSTACK = [
    "...YYY...",
    "..YYYYO..",
    ".YYYYYOO.",
    "YYYYYYYOO",
    "YYYYYYYOO",
    "YOYYYYYOO"
];

/*! Summer, animated by the scene rather than stamped into the ground. */
var BUTTERFLY_A = [
    "N.N",
    "NEN",
    ".E."
];

var BUTTERFLY_B = [
    "...",
    "NEN",
    ".E."
];

var ALL = {
    pumpkin: PUMPKIN,
    scarecrow: SCARECROW,
    bunny: BUNNY,
    snowman: SNOWMAN,
    haystack: HAYSTACK,
    butterflyA: BUTTERFLY_A,
    butterflyB: BUTTERFLY_B
};

function width(sprite) { return sprite[0].length; }
function height(sprite) { return sprite.length; }
