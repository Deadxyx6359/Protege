.pragma library

// Integer-only primitives keep every silhouette on the same pixel grid.
function hash(n) {
    var v = Math.sin(n * 127.1 + 311.7) * 43758.5453123;
    return v - Math.floor(v);
}
function mix(a, b, t) {
    t = Math.max(0, Math.min(1, t));
    var out = "#";
    for (var i = 1; i < 7; i += 2) {
        var x = parseInt(a.substr(i, 2), 16), y = parseInt(b.substr(i, 2), 16);
        out += ("0" + Math.round(x + (y - x) * t).toString(16)).slice(-2);
    }
    return out;
}
function Painter(ctx) { this.ctx = ctx; this.color = ""; }
Painter.prototype.rect = function(x, y, w, h, c) {
    if (!c || w <= 0 || h <= 0) return;
    if (c !== this.color) { this.ctx.fillStyle = c; this.color = c; }
    this.ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
};
Painter.prototype.dot = function(x, y, c) { this.rect(x, y, 1, 1, c); };
Painter.prototype.ellipse = function(cx, cy, rx, ry, c) {
    for (var y = Math.ceil(cy - ry); y <= Math.floor(cy + ry); y++) {
        var half = rx * Math.sqrt(Math.max(0, 1 - Math.pow((y - cy) / ry, 2)));
        var l = Math.ceil(cx - half), r = Math.floor(cx + half);
        this.rect(l, y, r - l + 1, 1, c);
    }
};
Painter.prototype.poly = function(points, c) {
    var top = 270, bottom = 0;
    for (var i = 0; i < points.length; i++) {
        top = Math.min(top, points[i][1]); bottom = Math.max(bottom, points[i][1]);
    }
    for (var y = Math.max(0, Math.ceil(top)); y < Math.min(270, bottom); y++) {
        var cuts = [];
        for (var j = 0; j < points.length; j++) {
            var a = points[j], b = points[(j + 1) % points.length];
            if ((a[1] <= y && b[1] > y) || (b[1] <= y && a[1] > y))
                cuts.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
        }
        cuts.sort(function(a, b) { return a - b; });
        for (var k = 0; k < cuts.length - 1; k += 2)
            this.rect(Math.ceil(cuts[k]), y, Math.floor(cuts[k + 1]) - Math.ceil(cuts[k]) + 1, 1, c);
    }
};
Painter.prototype.line = function(x0, y0, x1, y1, c, thickness) {
    x0 = Math.round(x0); y0 = Math.round(y0); x1 = Math.round(x1); y1 = Math.round(y1);
    var dx = Math.abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    var dy = -Math.abs(y1 - y0), sy = y0 < y1 ? 1 : -1, err = dx + dy;
    for (;;) {
        this.rect(x0, y0, thickness || 1, thickness || 1, c);
        if (x0 === x1 && y0 === y1) break;
        var e = 2 * err;
        if (e >= dy) { err += dy; x0 += sx; }
        if (e <= dx) { err += dx; y0 += sy; }
    }
};
function contour(points, x) {
    for (var i = 0; i < points.length - 1; i++) {
        if (x <= points[i + 1][0]) {
            var a = points[i], b = points[i + 1];
            return a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]);
        }
    }
    return points[points.length - 1][1];
}
