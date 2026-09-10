.pragma library

/*!
    Continuous-curvature rounded rectangles.

    A \c Rectangle corner is a circular arc: it meets the straight edge at a
    point where curvature jumps from zero to 1/r instantly. The eye reads that
    discontinuity as a seam, which is why circular rounding looks slightly
    cheap at large radii.

    Apple's corners instead ease curvature in and out, so the edge flows into
    the corner. The construction here is the standard one: each corner is an
    entry Bézier, a shortened circular arc, and a mirrored exit Bézier, with
    \c smoothing setting how much of the corner is spent easing rather than
    arcing.

    At small radii the difference is invisible and a Rectangle is cheaper —
    use this for cards, sheets, panels and the window, not for badges.
*/

var DEFAULT_SMOOTHING = 0.6;

function _rad(deg) {
    return deg * Math.PI / 180;
}

function _round(n) {
    // Four decimals is well below a device pixel and keeps the path string
    // short; QPainterPath re-parses it on every geometry change.
    return Math.round(n * 10000) / 10000;
}

/*!
    Solve one corner.

    \a budget is how far along an edge this corner may reach — half the
    shorter side when all four corners are equal. Both radius and smoothing
    are reduced to fit rather than allowed to overlap, because two corners
    that overrun each other produce a self-intersecting path.
*/
function _params(radius, smoothing, budget) {
    var r = Math.min(radius, budget);
    var s = smoothing;

    // The distance from the true corner at which the curve starts. Capping it
    // at the budget is what stops adjacent corners colliding on small items.
    var p = (1 + s) * r;
    if (p > budget) {
        s = Math.max(0, budget / r - 1);
        p = budget;
    }

    // How much of the 90° turn stays a true arc. All of it at s = 0, none at
    // s = 1 — where the corner becomes a pure Bézier.
    var arcMeasure = 90 * (1 - s);
    var arcSection = Math.sin(_rad(arcMeasure / 2)) * r * Math.sqrt(2);

    var alpha = (90 - arcMeasure) / 2;
    var p3ToP4 = r * Math.tan(_rad(alpha / 2));

    var beta = 45 * s;
    var c = p3ToP4 * Math.cos(_rad(beta));
    var d = c * Math.tan(_rad(beta));

    // The straight run left over is split 2:1 between the two control points,
    // which is what makes curvature ramp linearly instead of stepping.
    var b = (p - arcSection - c - d) / 3;
    var a = 2 * b;

    return { r: r, a: a, b: b, c: c, d: d, p: p, arc: arcSection };
}

function _topRight(k) {
    var r = _round;
    return "c " + r(k.a) + " 0 " + r(k.a + k.b) + " 0 " + r(k.a + k.b + k.c) + " " + r(k.d)
         + " a " + r(k.r) + " " + r(k.r) + " 0 0 1 " + r(k.arc) + " " + r(k.arc)
         + " c " + r(k.d) + " " + r(k.c) + " " + r(k.d) + " " + r(k.b + k.c)
                 + " " + r(k.d) + " " + r(k.a + k.b + k.c);
}

function _bottomRight(k) {
    var r = _round;
    return "c 0 " + r(k.a) + " 0 " + r(k.a + k.b) + " " + r(-k.d) + " " + r(k.a + k.b + k.c)
         + " a " + r(k.r) + " " + r(k.r) + " 0 0 1 " + r(-k.arc) + " " + r(k.arc)
         + " c " + r(-k.c) + " " + r(k.d) + " " + r(-(k.b + k.c)) + " " + r(k.d)
                 + " " + r(-(k.a + k.b + k.c)) + " " + r(k.d);
}

function _bottomLeft(k) {
    var r = _round;
    return "c " + r(-k.a) + " 0 " + r(-(k.a + k.b)) + " 0 " + r(-(k.a + k.b + k.c)) + " " + r(-k.d)
         + " a " + r(k.r) + " " + r(k.r) + " 0 0 1 " + r(-k.arc) + " " + r(-k.arc)
         + " c " + r(-k.d) + " " + r(-k.c) + " " + r(-k.d) + " " + r(-(k.b + k.c))
                 + " " + r(-k.d) + " " + r(-(k.a + k.b + k.c));
}

function _topLeft(k) {
    var r = _round;
    return "c 0 " + r(-k.a) + " 0 " + r(-(k.a + k.b)) + " " + r(k.d) + " " + r(-(k.a + k.b + k.c))
         + " a " + r(k.r) + " " + r(k.r) + " 0 0 1 " + r(k.arc) + " " + r(-k.arc)
         + " c " + r(k.c) + " " + r(-k.d) + " " + r(k.b + k.c) + " " + r(-k.d)
                 + " " + r(k.a + k.b + k.c) + " " + r(-k.d);
}

/*!
    Build an SVG path for a \a width by \a height rectangle with continuous
    corners of \a radius, eased by \a smoothing (0 = a plain rounded rect,
    0.6 = Apple's default, 1 = fully Bézier).

    Returns a closed path starting at the top edge, suitable for \c PathSvg.
*/
function path(width, height, radius, smoothing) {
    if (width <= 0 || height <= 0)
        return "";

    if (smoothing === undefined)
        smoothing = DEFAULT_SMOOTHING;

    var budget = Math.min(width, height) / 2;
    var k = _params(Math.max(0, radius), Math.max(0, Math.min(1, smoothing)), budget);
    var r = _round;

    if (k.r <= 0)
        return "M 0 0 L " + r(width) + " 0 L " + r(width) + " " + r(height) + " L 0 " + r(height) + " Z";

    return "M " + r(width - k.p) + " 0"
         + " " + _topRight(k)
         + " L " + r(width) + " " + r(height - k.p)
         + " " + _bottomRight(k)
         + " L " + r(k.p) + " " + r(height)
         + " " + _bottomLeft(k)
         + " L 0 " + r(k.p)
         + " " + _topLeft(k)
         + " Z";
}
