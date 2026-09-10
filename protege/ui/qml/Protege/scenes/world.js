.pragma library

/*!
    What the scenes need to know about the world: where the day is, which
    season it is, and what the weather is doing.

    Time and season come from the system clock and need no network — the scene
    is complete without one. Weather is a capability like any other; when it is
    not granted, `clear` is a perfectly good sky.

    Colours are a deliberately small palette rather than sampled from
    photographs. Eight-bit art reads as eight-bit because of restraint, not
    because of chunky pixels — a pixel-perfect scene in ten thousand colours
    just looks like a low-resolution photograph.
*/

// -- time ---------------------------------------------------------------

/*! Hour of the day as a fraction, 0.0 at midnight to 1.0 at the next. */
function dayFraction(date) {
    return (date.getHours() * 3600 + date.getMinutes() * 60 + date.getSeconds()) / 86400;
}

/*! A coarse name for the current light. Used for what is *present* — stars,
    lit windows — rather than for colour, which is interpolated. */
function phase(date) {
    var h = date.getHours() + date.getMinutes() / 60;
    if (h < 5.0) return "night";
    if (h < 7.5) return "dawn";
    if (h < 10.0) return "morning";
    if (h < 16.5) return "day";
    if (h < 19.0) return "goldenHour";
    if (h < 21.0) return "dusk";
    return "night";
}

// -- season -------------------------------------------------------------

/*  Season boundaries as day-of-year, following the solstices and equinoxes.

    An earlier version used whole months, on the reasoning that "autumn" means
    September onward. That is wrong, and obviously so the moment you look out
    of a window: the tenth of September is summer nearly everywhere in the
    northern hemisphere, and the scene was showing autumn colours in what was
    still shirtsleeve weather. Astronomical boundaries match what people
    actually see outside, which is the only thing this has to agree with.
*/
var SPRING_START = 79;   // ~20 March
var SUMMER_START = 172;  // ~21 June
var AUTUMN_START = 265;  // ~22 September
var WINTER_START = 355;  // ~21 December

function dayOfYear(date) {
    var start = new Date(date.getFullYear(), 0, 0);
    return Math.floor((date - start) / 86400000);
}

function season(date, southern) {
    var d = dayOfYear(date);
    var s;
    if (d < SPRING_START) s = "winter";
    else if (d < SUMMER_START) s = "spring";
    else if (d < AUTUMN_START) s = "summer";
    else if (d < WINTER_START) s = "autumn";
    else s = "winter";

    if (!southern)
        return s;
    var flip = { winter: "summer", summer: "winter", spring: "autumn", autumn: "spring" };
    return flip[s];
}

/*! 0.0 at the start of the season, 1.0 at its end. */
function seasonProgress(date) {
    var d = dayOfYear(date);
    var bounds = [
        [0, SPRING_START], [SPRING_START, SUMMER_START],
        [SUMMER_START, AUTUMN_START], [AUTUMN_START, WINTER_START],
        [WINTER_START, 366]
    ];
    for (var i = 0; i < bounds.length; i++) {
        if (d >= bounds[i][0] && d < bounds[i][1])
            return (d - bounds[i][0]) / (bounds[i][1] - bounds[i][0]);
    }
    return 0;
}

// -- palettes -----------------------------------------------------------

/*  Sky keyframes through the day, interpolated, so dawn arrives rather than
    being switched on. Three stops rather than two: real skies are not a linear
    ramp, and the band just above the horizon carries most of the colour.  */
var SKY = [
    { at: 0.00, top: "#0b1026", mid: "#111838", bottom: "#1a2145" },
    { at: 0.20, top: "#0d1330", mid: "#161d40", bottom: "#232a52" },
    { at: 0.22, top: "#2b2a5c", mid: "#5b4270", bottom: "#8a5570" },
    { at: 0.25, top: "#5a5590", mid: "#a1749b", bottom: "#e0977e" },
    { at: 0.28, top: "#7d93c6", mid: "#c9a0b4", bottom: "#f3c194" },
    { at: 0.33, top: "#6fa3d8", mid: "#a8c8e8", bottom: "#d8e7f2" },
    { at: 0.50, top: "#4a92d9", mid: "#89bde6", bottom: "#c8e2f4" },
    { at: 0.68, top: "#5a95cf", mid: "#9cc4e2", bottom: "#dde8f0" },
    { at: 0.76, top: "#6a7fc0", mid: "#c295ab", bottom: "#f0b070" },
    { at: 0.81, top: "#4a4a86", mid: "#9a5f7e", bottom: "#e08a5f" },
    { at: 0.86, top: "#25264f", mid: "#4e3560", bottom: "#8a4a63" },
    { at: 0.92, top: "#101636", mid: "#1a1e42", bottom: "#2a2b52" },
    { at: 1.00, top: "#0b1026", mid: "#111838", bottom: "#1a2145" }
];

function _hex(c) {
    return [parseInt(c.substr(1, 2), 16),
            parseInt(c.substr(3, 2), 16),
            parseInt(c.substr(5, 2), 16)];
}

function mix(a, b, t) {
    var x = _hex(a), y = _hex(b);
    var k = Math.max(0, Math.min(1, t));
    var out = "#";
    for (var i = 0; i < 3; i++) {
        var v = Math.round(x[i] + (y[i] - x[i]) * k);
        out += ("0" + v.toString(16)).slice(-2);
    }
    return out;
}

/*! Sky gradient for a moment in the day: \c {{top, mid, bottom}}. */
function sky(fraction) {
    for (var i = 0; i < SKY.length - 1; i++) {
        var a = SKY[i], b = SKY[i + 1];
        if (fraction >= a.at && fraction <= b.at) {
            var t = (fraction - a.at) / (b.at - a.at);
            return {
                top: mix(a.top, b.top, t),
                mid: mix(a.mid, b.mid, t),
                bottom: mix(a.bottom, b.bottom, t)
            };
        }
    }
    return { top: SKY[0].top, mid: SKY[0].mid, bottom: SKY[0].bottom };
}

/*!
    The season's colours.

    Every surface gets three or four tones rather than one. A single flat
    colour per material is what made the first version of this scene look like
    a diagram; shading and dithering are what turn a green band into a
    hillside.
*/
function palette(seasonName) {
    switch (seasonName) {
    case "spring":
        return {
            pineLight: "#5d9e63", pineMid: "#3d7a4c", pineDark: "#26543a",
            pineDeep: "#1a3b2c",
            leafLight: "#8ecb74", leafMid: "#63a95c", leafDark: "#3f7a45",
            blossom: "#f4b8cf", blossomAlt: "#ffd9e6",
            grassLight: "#9ccf72", grassMid: "#74b45c", grassDark: "#4f8c48",
            grassDeep: "#3a6e3c",
            ridgeFar: "#9aa6c8", ridgeMid: "#7b87ae", ridgeNear: "#5c6b91",
            rock: "#8f8aa6", rockLight: "#b3aec4", snowCap: "#f2f4fb",
            trunk: "#6b4a34", trunkDark: "#4a3325",
            water: "#4a7fbf", waterLight: "#7aa9d9", waterDark: "#32588c",
            flowers: ["#f4b8cf", "#fff3b0", "#c8a2e0", "#ffffff", "#ffd9e6", "#a8d8ff"],
            snow: null
        };
    case "summer":
        return {
            pineLight: "#4f9152", pineMid: "#2f7040", pineDark: "#1e4c30",
            pineDeep: "#143524",
            leafLight: "#6db85a", leafMid: "#489646", leafDark: "#2f6d38",
            blossom: "#f6d76b", blossomAlt: "#ffe9a8",
            grassLight: "#84c261", grassMid: "#5da84e", grassDark: "#3f8440",
            grassDeep: "#2e6634",
            ridgeFar: "#93a2c6", ridgeMid: "#7382ab", ridgeNear: "#55658c",
            rock: "#8a85a1", rockLight: "#aea9c0", snowCap: "#f2f4fb",
            trunk: "#5f4230", trunkDark: "#402c20",
            water: "#3f79bd", waterLight: "#6fa3d6", waterDark: "#2b5288",
            flowers: ["#ffe9a8", "#ffffff", "#f7c4d8", "#c9b3e8", "#ffd166", "#e8f0a0"],
            snow: null
        };
    case "autumn":
        return {
            pineLight: "#54834f", pineMid: "#3a6440", pineDark: "#25452e",
            pineDeep: "#183024",
            leafLight: "#e8a34a", leafMid: "#c9722f", leafDark: "#9b4a26",
            blossom: "#d9603f", blossomAlt: "#f0a05a",
            grassLight: "#c4b463", grassMid: "#a09250", grassDark: "#7a6e3e",
            grassDeep: "#5c5330",
            ridgeFar: "#9d9ab5", ridgeMid: "#807d9c", ridgeNear: "#615f7d",
            rock: "#8d8595", rockLight: "#b0a8b8", snowCap: "#eef1f8",
            trunk: "#553a29", trunkDark: "#38251a",
            water: "#41739f", waterLight: "#6f9cc2", waterDark: "#2c4f73",
            flowers: ["#e8a34a", "#d9603f", "#f0c674", "#b5893f", "#e0dcc0", "#c98b5a"],
            snow: null
        };
    default: // winter
        return {
            pineLight: "#4a6b62", pineMid: "#33514c", pineDark: "#21383a",
            pineDeep: "#16272c",
            leafLight: "#9aa8b8", leafMid: "#78889b", leafDark: "#5a6a7d",
            blossom: "#e8f0f8", blossomAlt: "#ffffff",
            grassLight: "#e8eff6", grassMid: "#cfdae6", grassDark: "#adbccd",
            grassDeep: "#8fa0b4",
            ridgeFar: "#a8b4c8", ridgeMid: "#8896ae", ridgeNear: "#697894",
            rock: "#7f8496", rockLight: "#a3a8b8", snowCap: "#ffffff",
            trunk: "#4a382c", trunkDark: "#2f231b",
            water: "#5a86ac", waterLight: "#93b4d2", waterDark: "#3d6285",
            flowers: ["#ffffff", "#e8f0f8", "#d4e2ee"],
            snow: "#f4f8fc"
        };
    }
}

/*! How much of night this is, 0 at full day and 1 at deep night. */
function nightness(fraction) {
    var f = fraction;
    if (f > 0.21 && f < 0.30) return 1 - (f - 0.21) / 0.09;   // dawn
    if (f >= 0.30 && f < 0.78) return 0;                       // day
    if (f >= 0.78 && f < 0.90) return (f - 0.78) / 0.12;       // dusk
    return 1;                                                   // night
}

// -- weather ------------------------------------------------------------

/*  Weather is more than a label. Each state carries how hard it is raining,
    how hard the wind is blowing, how much light the cloud deck takes out and
    whether there is lightning — so "drizzle" and "thunderstorm" are genuinely
    different scenes rather than the same particles at two densities.

    wind        0..1  how far the trees lean, and how fast the clouds run
    gust        0..1  how much the wind varies around that lean
    precip      0..1  particle density
    precipKind  "rain" | "snow" | null
    gloom       0..1  how much light the cloud deck takes out
    cover       cloud count
    lightning   mean seconds between strikes, 0 for none
*/
var CONDITIONS = {
    clear:    { wind: 0.10, gust: 0.15, precip: 0.00, precipKind: null,   gloom: 0.00, cover: 2,  lightning: 0 },
    fair:     { wind: 0.18, gust: 0.25, precip: 0.00, precipKind: null,   gloom: 0.04, cover: 4,  lightning: 0 },
    cloudy:   { wind: 0.25, gust: 0.30, precip: 0.00, precipKind: null,   gloom: 0.12, cover: 7,  lightning: 0 },
    overcast: { wind: 0.30, gust: 0.30, precip: 0.00, precipKind: null,   gloom: 0.28, cover: 11, lightning: 0 },
    fog:      { wind: 0.06, gust: 0.10, precip: 0.00, precipKind: null,   gloom: 0.22, cover: 5,  lightning: 0 },
    drizzle:  { wind: 0.22, gust: 0.25, precip: 0.22, precipKind: "rain", gloom: 0.26, cover: 9,  lightning: 0 },
    rain:     { wind: 0.40, gust: 0.35, precip: 0.60, precipKind: "rain", gloom: 0.40, cover: 11, lightning: 0 },
    downpour: { wind: 0.62, gust: 0.45, precip: 1.00, precipKind: "rain", gloom: 0.55, cover: 12, lightning: 0 },
    thunder:  { wind: 0.78, gust: 0.60, precip: 0.92, precipKind: "rain", gloom: 0.66, cover: 12, lightning: 11 },
    windy:    { wind: 0.80, gust: 0.70, precip: 0.00, precipKind: null,   gloom: 0.08, cover: 6,  lightning: 0 },
    gale:     { wind: 1.00, gust: 0.85, precip: 0.30, precipKind: "rain", gloom: 0.45, cover: 12, lightning: 0 },
    snow:     { wind: 0.25, gust: 0.35, precip: 0.55, precipKind: "snow", gloom: 0.30, cover: 10, lightning: 0 },
    blizzard: { wind: 0.95, gust: 0.80, precip: 1.00, precipKind: "snow", gloom: 0.55, cover: 12, lightning: 0 }
};

var WEATHER = ["clear", "fair", "cloudy", "overcast", "fog", "drizzle", "rain",
               "downpour", "thunder", "windy", "gale", "snow", "blizzard"];

/*! Look up a condition, falling back to a sky that needs no network. */
function conditions(name) {
    return CONDITIONS[name] || CONDITIONS.clear;
}

/*!
    Normalise anything a connector reports into one of \c WEATHER.

    Ordered most specific first: "heavy rain" must not match the plain "rain"
    rule before "heavy" has been considered, or every storm becomes a shower.
*/
function normaliseWeather(raw) {
    if (!raw)
        return "clear";
    var w = String(raw).toLowerCase();

    if (w.indexOf("thunder") >= 0 || w.indexOf("lightning") >= 0) return "thunder";
    if (w.indexOf("blizzard") >= 0) return "blizzard";
    if (w.indexOf("gale") >= 0 || w.indexOf("hurricane") >= 0 || w.indexOf("storm") >= 0) return "gale";
    if (w.indexOf("snow") >= 0 || w.indexOf("sleet") >= 0 || w.indexOf("flurr") >= 0) return "snow";
    if (w.indexOf("drizzle") >= 0 || w.indexOf("light rain") >= 0 || w.indexOf("mist") >= 0) return "drizzle";
    if (w.indexOf("heavy") >= 0 && w.indexOf("rain") >= 0) return "downpour";
    if (w.indexOf("rain") >= 0 || w.indexOf("shower") >= 0) return "rain";
    if (w.indexOf("fog") >= 0 || w.indexOf("haze") >= 0) return "fog";
    if (w.indexOf("overcast") >= 0) return "overcast";
    if (w.indexOf("wind") >= 0 || w.indexOf("breez") >= 0) return "windy";
    if (w.indexOf("cloud") >= 0) return "cloudy";
    if (w.indexOf("fair") >= 0 || w.indexOf("sun") >= 0) return "clear";
    return "clear";
}

// -- helpers ------------------------------------------------------------

/*! Deterministic pseudo-random in [0,1) from an integer seed.

    The scene must lay out identically on every launch — a landscape whose
    trees move when you reopen the window is a different landscape, and stops
    being a place.
*/
function rand(seed) {
    var x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return x - Math.floor(x);
}

/*! Value noise in one dimension, smooth between integer steps.

    A ridge built from two or three sines reads as a sine wave. Noise reads as
    terrain.
*/
function noise(x, seed) {
    var i = Math.floor(x);
    var f = x - i;
    var s = f * f * (3 - 2 * f);           // smoothstep
    var a = rand(i + seed * 1013);
    var b = rand(i + 1 + seed * 1013);
    return a + (b - a) * s;
}

/*! Several octaves of \c noise, halving in amplitude each time. */
function fbm(x, seed, octaves) {
    var total = 0, amp = 1, freq = 1, norm = 0;
    var n = octaves || 4;
    for (var i = 0; i < n; i++) {
        total += noise(x * freq, seed + i * 7) * amp;
        norm += amp;
        amp *= 0.5;
        freq *= 2;
    }
    return total / norm;
}

/*! A 4×4 ordered dither. True when this cell takes the lighter tone.

    Two colours alternating on a grid read as a third colour between them,
    which is how a small palette covers a whole hillside. It is the single
    biggest difference between pixel art and a low-resolution image.
*/
var _BAYER = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5]
];

function dither(x, y, level) {
    return _BAYER[y & 3][x & 3] < level * 16;
}
