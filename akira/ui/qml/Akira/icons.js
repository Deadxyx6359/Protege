.pragma library

/*!
    Icon geometry.

    Every icon is drawn on a 24×24 grid and, unless marked \c filled, is a
    *stroke* — an open path with round caps and joins, weighted to sit beside
    Segoe UI Variable rather than to be noticed on its own. That is the whole
    trick to SF Symbols-style icons: consistent optical weight, consistent
    terminal shape, and no filled mass except where the icon is a symbol rather
    than a picture.

    Paths use absolute commands only. Arcs are written as two half-arcs where a
    full circle is needed, because a single 360° arc is degenerate in SVG and
    renders as nothing.
*/

var STROKE = {

    // -- navigation --------------------------------------------------------

    chat: "M 7 4 L 17 4 A 3 3 0 0 1 20 7 L 20 14 A 3 3 0 0 1 17 17 "
        + "L 11 17 L 6 21 L 6.6 17 A 3 3 0 0 1 4 14 L 4 7 A 3 3 0 0 1 7 4 Z",

    code: "M 9 7 L 4 12 L 9 17 M 15 7 L 20 12 L 15 17",

    document: "M 14 3 L 6 3 A 2 2 0 0 0 4 5 L 4 19 A 2 2 0 0 0 6 21 "
            + "L 18 21 A 2 2 0 0 0 20 19 L 20 9 Z M 14 3 L 14 9 L 20 9",

    folder: "M 3 7 A 2 2 0 0 1 5 5 L 9.5 5 L 11.5 8 L 19 8 A 2 2 0 0 1 21 10 "
          + "L 21 18 A 2 2 0 0 1 19 20 L 5 20 A 2 2 0 0 1 3 18 Z",

    terminal: "M 5 7 L 9 11 L 5 15 M 12 16 L 19 16",

    sidebar: "M 4 6 A 2 2 0 0 1 6 4 L 18 4 A 2 2 0 0 1 20 6 L 20 18 "
           + "A 2 2 0 0 1 18 20 L 6 20 A 2 2 0 0 1 4 18 Z M 10 4 L 10 20",

    // -- actions -----------------------------------------------------------

    search: "M 20.5 20.5 L 16.4 16.4 M 18 11 A 7 7 0 1 0 4 11 A 7 7 0 1 0 18 11 Z",

    plus: "M 12 5 L 12 19 M 5 12 L 19 12",
    close: "M 6.5 6.5 L 17.5 17.5 M 17.5 6.5 L 6.5 17.5",
    check: "M 5 12.5 L 9.5 17 L 19 6.5",

    send: "M 12 20 L 12 4.5 M 5.5 11 L 12 4.5 L 18.5 11",
    stop: "M 8 8 L 16 8 L 16 16 L 8 16 Z",

    attach: "M 19.5 11.5 L 11.5 19.5 A 5 5 0 0 1 4.5 12.5 L 12.5 4.5 "
          + "A 3.5 3.5 0 0 1 17.5 9.5 L 9.5 17.5 A 2 2 0 0 1 6.7 14.7 L 14 7.5",

    copy: "M 9 9 A 2 2 0 0 1 11 7 L 19 7 A 2 2 0 0 1 21 9 L 21 17 "
        + "A 2 2 0 0 1 19 19 L 11 19 A 2 2 0 0 1 9 17 Z "
        + "M 5 15 A 2 2 0 0 1 3 13 L 3 5 A 2 2 0 0 1 5 3 L 13 3 A 2 2 0 0 1 15 5",

    trash: "M 4.5 7 L 19.5 7 M 10 11 L 10 17 M 14 11 L 14 17 "
         + "M 6.5 7 L 7.4 20 A 1.6 1.6 0 0 0 9 21.5 L 15 21.5 A 1.6 1.6 0 0 0 16.6 20 L 17.5 7 "
         + "M 9 7 L 9 4.5 A 1.5 1.5 0 0 1 10.5 3 L 13.5 3 A 1.5 1.5 0 0 1 15 4.5 L 15 7",

    refresh: "M 20.5 12 A 8.5 8.5 0 1 1 17.6 5.6 M 20.5 4 L 20.5 9.5 L 15 9.5",

    pin: "M 12 16.5 L 12 22 M 8.5 2.5 L 15.5 2.5 L 14.5 9 L 18 12 L 6 12 L 9.5 9 Z",

    // -- disclosure --------------------------------------------------------

    chevronRight: "M 9.5 5 L 16.5 12 L 9.5 19",
    chevronDown: "M 5 9.5 L 12 16.5 L 19 9.5",
    chevronUpDown: "M 8 10 L 12 6 L 16 10 M 8 14 L 12 18 L 16 14",

    // -- state -------------------------------------------------------------

    clock: "M 21 12 A 9 9 0 1 0 3 12 A 9 9 0 1 0 21 12 Z M 12 6.5 L 12 12 L 15.8 14.2",

    user: "M 20 21 L 20 19 A 4.5 4.5 0 0 0 15.5 14.5 L 8.5 14.5 "
        + "A 4.5 4.5 0 0 0 4 19 L 4 21 M 16 7 A 4 4 0 1 0 8 7 A 4 4 0 1 0 16 7 Z",

    settings: "M 4 8 L 13.2 8 M 18.8 8 L 20 8 M 4 16 L 8.2 16 M 13.8 16 L 20 16 "
            + "M 18.8 8 A 2.8 2.8 0 1 0 13.2 8 A 2.8 2.8 0 1 0 18.8 8 Z "
            + "M 13.8 16 A 2.8 2.8 0 1 0 8.2 16 A 2.8 2.8 0 1 0 13.8 16 Z",

    moon: "M 20.5 14.5 A 9 9 0 1 1 10 3.2 A 7.2 7.2 0 0 0 20.5 14.5 Z",

    sun: "M 16 12 A 4 4 0 1 0 8 12 A 4 4 0 1 0 16 12 Z "
       + "M 12 2.5 L 12 4.5 M 12 19.5 L 12 21.5 M 21.5 12 L 19.5 12 M 4.5 12 L 2.5 12 "
       + "M 18.7 5.3 L 17.3 6.7 M 6.7 17.3 L 5.3 18.7 M 18.7 18.7 L 17.3 17.3 M 6.7 6.7 L 5.3 5.3",

    gitBranch: "M 7 6.5 L 7 17.5 "
             + "M 10 18.5 A 3 3 0 1 0 4 18.5 A 3 3 0 1 0 10 18.5 Z "
             + "M 20 5.5 A 3 3 0 1 0 14 5.5 A 3 3 0 1 0 20 5.5 Z "
             + "M 17 8.5 A 7 7 0 0 1 10 15.5",

    more: "M 6.2 12 A 1.2 1.2 0 1 0 3.8 12 A 1.2 1.2 0 1 0 6.2 12 Z "
        + "M 13.2 12 A 1.2 1.2 0 1 0 10.8 12 A 1.2 1.2 0 1 0 13.2 12 Z "
        + "M 20.2 12 A 1.2 1.2 0 1 0 17.8 12 A 1.2 1.2 0 1 0 20.2 12 Z",

    // -- trust and reach ---------------------------------------------------

    shield: "M 12 3 L 19.5 6 L 19.5 11.5 C 19.5 16 16.3 19.6 12 21 "
          + "C 7.7 19.6 4.5 16 4.5 11.5 L 4.5 6 Z",

    eye: "M 2.5 12 C 5 7.5 8.3 5.5 12 5.5 C 15.7 5.5 19 7.5 21.5 12 "
       + "C 19 16.5 15.7 18.5 12 18.5 C 8.3 18.5 5 16.5 2.5 12 Z "
       + "M 15 12 A 3 3 0 1 0 9 12 A 3 3 0 1 0 15 12 Z",

    globe: "M 21 12 A 9 9 0 1 0 3 12 A 9 9 0 1 0 21 12 Z M 3.5 12 L 20.5 12 "
         + "M 12 3 C 9.5 5.7 8.3 8.7 8.3 12 C 8.3 15.3 9.5 18.3 12 21 "
         + "C 14.5 18.3 15.7 15.3 15.7 12 C 15.7 8.7 14.5 5.7 12 3 Z",

    team: "M 12.5 7.5 A 3.5 3.5 0 1 0 5.5 7.5 A 3.5 3.5 0 1 0 12.5 7.5 Z "
        + "M 2.5 20 A 6.5 6.5 0 0 1 15.5 20 M 16 4.3 A 3.5 3.5 0 0 1 16 10.7 "
        + "M 18 14.2 A 6.5 6.5 0 0 1 21.5 20",

    bell: "M 5.5 17 L 18.5 17 M 7 17 L 7 11 A 5 5 0 0 1 17 11 L 17 17 "
        + "M 10.2 17 A 1.8 1.8 0 0 0 13.8 17 M 12 4 L 12 6",

    feed: "M 7 18.5 A 1.5 1.5 0 1 0 4 18.5 A 1.5 1.5 0 1 0 7 18.5 Z "
        + "M 4 11.5 A 8.5 8.5 0 0 1 12.5 20 M 4 5 A 15 15 0 0 1 19 20",

    calendar: "M 6 5 L 18 5 A 2 2 0 0 1 20 7 L 20 18 A 2 2 0 0 1 18 20 L 6 20 "
            + "A 2 2 0 0 1 4 18 L 4 7 A 2 2 0 0 1 6 5 Z M 4 9.5 L 20 9.5 "
            + "M 8.5 3 L 8.5 6.5 M 15.5 3 L 15.5 6.5",

    mail: "M 5 6 L 19 6 A 2 2 0 0 1 21 8 L 21 17 A 2 2 0 0 1 19 19 L 5 19 "
        + "A 2 2 0 0 1 3 17 L 3 8 A 2 2 0 0 1 5 6 Z M 3.5 7.5 L 12 13.5 L 20.5 7.5"
};

/*!
    Filled marks. These are symbols rather than depictions, so a stroke would
    read as an outline of the idea instead of the idea itself.
*/
var FILLED = {
    /*  The application mark, and the "thinking" indicator. A four-pointed star
        whose arms are drawn with cubic curves so the concave sides pinch
        rather than taper linearly — the difference between a sparkle and a
        compass rose.  */
    sparkle: "M 12 2.2 C 12 8.4 13.1 9.8 19.4 12 C 13.1 14.2 12 15.6 12 21.8 "
           + "C 12 15.6 10.9 14.2 4.6 12 C 10.9 9.8 12 8.4 12 2.2 Z",

    sparkleSmall: "M 18.5 14.4 C 18.5 17.2 19 17.8 21.8 18.6 "
                + "C 19 19.4 18.5 20 18.5 22.8 C 18.5 20 18 19.4 15.2 18.6 "
                + "C 18 17.8 18.5 17.2 18.5 14.4 Z",

    dot: "M 15 12 A 3 3 0 1 0 9 12 A 3 3 0 1 0 15 12 Z"
};

/*! Every icon name, for tests and the gallery. */
function names() {
    var out = [];
    for (var k in STROKE) out.push(k);
    for (var f in FILLED) out.push(f);
    return out.sort();
}

/*! Look up \a name. Returns \c null when unknown, so callers can render nothing
    rather than a broken path. */
function lookup(name) {
    if (STROKE.hasOwnProperty(name))
        return { path: STROKE[name], filled: false };
    if (FILLED.hasOwnProperty(name))
        return { path: FILLED[name], filled: true };
    return null;
}
