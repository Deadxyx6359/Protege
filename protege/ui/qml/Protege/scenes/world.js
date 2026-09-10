.pragma library

/*!
    What the scenes need to know about the world: where the day is, which
    season it is, and what the sky should look like.

    Time and season come from the system clock and need no network — the scene
    is complete without one. Weather is a capability like any other; when it is
    not granted, `clear` is a perfectly good sky.

    Colours are chosen as a 16-ish entry palette rather than sampled from
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

function isDark(date) {
    var p = phase(date);
    return p === "night" || p === "dusk";
}

// -- season -------------------------------------------------------------

/*! Meteorological seasons — whole months, not equinoxes.

    Astronomical seasons start mid-month, which would make the scene change
    its planting on the 20th of March for reasons no one looking at it would
    guess. Whole months are what people actually mean by "it's autumn now".
*/
function season(date, southern) {
    var m = date.getMonth(); // 0 = January
    var order = ["winter", "winter", "spring", "spring", "spring", "summer",
                 "summer", "summer", "autumn", "autumn", "autumn", "winter"];
    var s = order[m];
    if (!southern)
        return s;
    var flip = { winter: "summer", summer: "winter", spring: "autumn", autumn: "spring" };
    return flip[s];
}

/*! 0.0 at the start of the season, 1.0 at its end.

    Lets a scene ease between plantings instead of swapping them at midnight on
    the first — trees that turn over a fortnight look like trees.
*/
function seasonProgress(date) {
    var m = date.getMonth();
    var within = [2, 0, 0, 1, 2, 0, 1, 2, 0, 1, 2, 1];  // month's index in its season
    var day = (date.getDate() - 1) / 30.0;
    return Math.min(1, Math.max(0, (within[m] + day) / 3.0));
}

// -- palettes -----------------------------------------------------------

/*  Sky keyframes through the day. Interpolated, so the sky is never quite the
    same twice and dawn actually arrives rather than being switched on.  */
var SKY = [
    { at: 0.00, top: "#0b1026", bottom: "#131a3a" },  // deep night
    { at: 0.20, top: "#0d1330", bottom: "#1b2148" },  // late night
    { at: 0.22, top: "#2b2a5c", bottom: "#7b4a6b" },  // first light, ~05:15
    { at: 0.25, top: "#4a4a86", bottom: "#e08a6b" },  // dawn, ~06:00
    { at: 0.28, top: "#6f8fc4", bottom: "#f3b183" },  // sunrise, ~06:45
    { at: 0.33, top: "#5b9bd5", bottom: "#a8d3ef" },  // morning, ~07:55
    { at: 0.52, top: "#4a92d9", bottom: "#bfe0f5" },  // midday
    { at: 0.68, top: "#5a95cf", bottom: "#d9e6f0" },  // afternoon
    { at: 0.76, top: "#5f7ec0", bottom: "#f0b070" },  // golden hour
    { at: 0.82, top: "#41427e", bottom: "#d9713f" },  // sunset
    { at: 0.87, top: "#22224f", bottom: "#6a3a5c" },  // dusk
    { at: 0.93, top: "#101636", bottom: "#1c2246" },  // evening
    { at: 1.00, top: "#0b1026", bottom: "#131a3a" }
];

function _hex(c) {
    return [parseInt(c.substr(1, 2), 16),
            parseInt(c.substr(3, 2), 16),
            parseInt(c.substr(5, 2), 16)];
}

function _mix(a, b, t) {
    var x = _hex(a), y = _hex(b);
    var out = "#";
    for (var i = 0; i < 3; i++) {
        var v = Math.round(x[i] + (y[i] - x[i]) * t);
        out += ("0" + v.toString(16)).slice(-2);
    }
    return out;
}

/*! Sky gradient for a moment in the day: \c {{top, bottom}}. */
function sky(fraction) {
    for (var i = 0; i < SKY.length - 1; i++) {
        var a = SKY[i], b = SKY[i + 1];
        if (fraction >= a.at && fraction <= b.at) {
            var t = (fraction - a.at) / (b.at - a.at);
            return { top: _mix(a.top, b.top, t), bottom: _mix(a.bottom, b.bottom, t) };
        }
    }
    return { top: SKY[0].top, bottom: SKY[0].bottom };
}

/*! Foliage, ground and accent colours for a season.

    Two foliage tones per season: canopies are drawn in both so a tree has some
    internal shape instead of reading as a single flat blob.
*/
function palette(seasonName) {
    switch (seasonName) {
    case "spring":
        return {
            leafLight: "#7cc46b", leafDark: "#4e9a52", blossom: "#f2a8c4",
            grassLight: "#6fb85e", grassDark: "#4a8f47",
            hillFar: "#7f9ec0", hillMid: "#5d8a66", trunk: "#6b4a34",
            accent: "#f7e08a", snow: null
        };
    case "summer":
        return {
            leafLight: "#57ab4e", leafDark: "#2f7a3c", blossom: "#f6d76b",
            grassLight: "#5aa84b", grassDark: "#3c7c3a", hillFar: "#7d9ec4",
            hillMid: "#467a4a", trunk: "#5f4230", accent: "#f2c14e", snow: null
        };
    case "autumn":
        return {
            leafLight: "#e0913f", leafDark: "#b2542c", blossom: "#d9603f",
            grassLight: "#a89550", grassDark: "#7d6c39", hillFar: "#8d92ad",
            hillMid: "#7a6a42", trunk: "#553a29", accent: "#e6b055", snow: null
        };
    default: // winter
        return {
            leafLight: "#8fa5b8", leafDark: "#6b8299", blossom: "#dfe9f2",
            grassLight: "#cdd9e4", grassDark: "#a8b9c9", hillFar: "#93a3ba",
            hillMid: "#b3c3d2", trunk: "#4a382c", accent: "#dfe9f2", snow: "#eef4fa"
        };
    }
}

/*! How much of night this is, 0 at full day and 1 at deep night.

    Everything on the ground is multiplied toward this — a summer canopy at
    midnight is a dark shape, not a bright green one lit from nowhere.
*/
function nightness(fraction) {
    var f = fraction;
    // 0.23 is about 05:30 and 0.31 about 07:30 — light by breakfast, which is
    // what the eye expects. An earlier version still had stars out at half
    // past seven in April.
    if (f > 0.23 && f < 0.31) return 1 - (f - 0.23) / 0.08;   // dawn
    if (f >= 0.31 && f < 0.78) return 0;                       // day
    if (f >= 0.78 && f < 0.90) return (f - 0.78) / 0.12;       // dusk
    return 1;                                                   // night
}

/*! Darken \a color toward the night tint by \a amount (0..1). */
function dim(color, amount) {
    return _mix(color, "#141a2e", Math.min(1, Math.max(0, amount)) * 0.72);
}

// -- weather ------------------------------------------------------------

var WEATHER = ["clear", "cloudy", "overcast", "rain", "snow", "fog"];

/*! Normalise anything a connector reports into one of \c WEATHER. */
function normaliseWeather(raw) {
    if (!raw)
        return "clear";
    var w = String(raw).toLowerCase();
    if (w.indexOf("snow") >= 0 || w.indexOf("sleet") >= 0) return "snow";
    if (w.indexOf("rain") >= 0 || w.indexOf("drizzle") >= 0 || w.indexOf("shower") >= 0) return "rain";
    if (w.indexOf("fog") >= 0 || w.indexOf("mist") >= 0 || w.indexOf("haze") >= 0) return "fog";
    if (w.indexOf("overcast") >= 0) return "overcast";
    if (w.indexOf("cloud") >= 0) return "cloudy";
    return "clear";
}

/*! How many clouds a weather state should show. */
function cloudCount(weather) {
    switch (weather) {
    case "clear": return 2;
    case "cloudy": return 5;
    case "overcast": return 8;
    case "rain": return 7;
    case "snow": return 6;
    case "fog": return 4;
    default: return 3;
    }
}

/*! Deterministic pseudo-random in [0,1) from an integer seed.

    The scene must lay out identically on every launch — a landscape whose
    trees move when you reopen the window is a different landscape, and stops
    being a place.
*/
function rand(seed) {
    var x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return x - Math.floor(x);
}
