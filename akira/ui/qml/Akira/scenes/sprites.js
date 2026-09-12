.pragma library

/*!
    The things in the picture that have a shape.

    Terrain, forest and sea are generated in scene.js, because they have to
    vary and to recede. These do not: they are the subject, and a subject
    should look the same every time you see it.

    There is one per season, placed deliberately. Spreading interest evenly
    across a frame is what makes a picture read as texture rather than as a
    scene, so everything else is deliberately quiet and this is where the
    detail goes.

    Key
      .  transparent   W  white        E  darkest        C  charcoal
      O  orange        P  pumpkin      Y  straw          V  stem green
      R  red cloth     K  wood dark    T  trunk          G  grass dark
      L  leaf light    D  leaf dark    B  blossom        S  snow
      A  accent red    M  cream        Q  lit window     Z  pale blue
      X  deep red      N  pink         U  blue
*/

// -- spring -------------------------------------------------------------

/*! The spring subject: one tree in blossom, off-centre. */
var BLOSSOM_TREE = [
    "...BLLLB....",
    "..BLLLLLLB..",
    ".LLLBLLLLLL.",
    "BLLLLLLLBLLB",
    ".LLBLLLLLLL.",
    "..LLLLLBLL..",
    "...LLLLLL...",
    "....KKK.....",
    "....KKK.....",
    "....KKK.....",
    "...KKKKK...."
];

var BUNNY = [
    "W.W....",
    "W.W....",
    "WWWW...",
    "WEWWWW.",
    "WWWWWWW",
    ".W...W."
];

// -- summer -------------------------------------------------------------

/*! The summer subject: parasols on the sand. */
var PARASOL = [
    "...M...",
    ".MAMAM.",
    "MAMAMAM",
    "...K...",
    "...K...",
    "...K..."
];

// -- autumn -------------------------------------------------------------

var PUMPKIN = [
    "..V..",
    ".OPO.",
    "OPPPO",
    "OPPPO",
    ".OPO."
];

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

/*!
    The one that is not always there.

    A monster in frame is a cartoon. Something you are not certain you saw is
    the effect being aimed at, so this is drawn thin, dark, at the treeline,
    and only during a brief window of a long cycle — never announced, never
    lit, and gone before you can point at it.
*/
var WATCHER = [
    ".E.",
    "EEE",
    ".E.",
    ".E.",
    ".E.",
    "EEE",
    ".E.",
    ".E.",
    ".E.",
    "E.E",
    "E.E"
];

// -- winter -------------------------------------------------------------

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

/*! Winter's subject is warmth: a lit window in the cold. */
var CABIN = [
    "...RRRRRR...",
    "..RRRRRRRR..",
    ".RRRRRRRRRR.",
    "KKKKKKKKKKKK",
    "K.QQ..QQ...K",
    "K.QQ..QQ...K",
    "KKKKKKKKKKKK",
    "K....KK....K",
    "K....KK....K",
    "KKKKKKKKKKKK"
];

var XMAS_TREE = [
    ".....S.....",
    "....DLD....",
    "...DLLLD...",
    "..DLQLLLD..",
    ".DLLLLLQLD.",
    "..DLLLLLD..",
    ".DLQLLLLLD.",
    "DLLLLLQLLLD",
    ".DLLLLLLLD.",
    "DLLQLLLLLLD",
    "....KKK....",
    "....KKK...."
];

// -- incidental ---------------------------------------------------------

/*! Summer, drifting. Two frames is the whole vocabulary of a 3×3 sprite. */
var BUTTERFLY_A = ["N.N", "NEN", ".E."];
var BUTTERFLY_B = ["...", "NEN", ".E."];

/*! A gull, for the sea. Two frames: up-stroke and down-stroke. */
var GULL_A = ["W.W", ".W."];
var GULL_B = ["...", "WWW"];

function width(sprite) { return sprite[0].length; }
function height(sprite) { return sprite.length; }
