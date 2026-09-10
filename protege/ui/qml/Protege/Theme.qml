pragma Singleton

import QtQuick

/*!
    Every visual constant in Protégé.

    The palettes live here rather than in Python because QML is their only
    consumer, and a value with one consumer belongs next to it. Python decides
    only which of them is active — it has to, since reading the OS light/dark
    setting is a platform call — and pushes that decision in through
    \c ThemeLink.

    Colours are declared as top-level properties rather than grouped, so each
    can carry its own \c Behavior and cross-fade when the palette swaps.
    Geometry, type and motion are grouped, because they never change at runtime
    and grouping keeps call sites readable: \c Theme.space.lg beats
    \c Theme.spaceLg.
*/
QtObject {
    id: theme

    // -- input -------------------------------------------------------------

    /*  Pushed in by ThemeLink, the one component that knows Python exists.
        Both carry usable defaults so the singleton is completely valid before
        anything attaches — otherwise every colour resolves to undefined on the
        first frame and Qt logs a warning per binding.  */
    property string mode: "dark"
    property real motionScale: 1.0

    readonly property bool isDark: mode === "dark"

    // -- palettes ----------------------------------------------------------

    /*  Deliberately close to Apple's system colours rather than invented.
        #F5F5F7 and #1D1D1F in particular are Apple's own primary text values,
        and matching them is most of why an interface reads as "Apple-like"
        before a single animation runs.

        Alpha is leading — #AARRGGBB, Qt's convention, not CSS's. Writing it
        the other way round yields a colour rather than an error.  */
    readonly property var _dark: ({
        // Near-black with a cool cast, never pure #000: on pure black every
        // shadow is invisible and every edge is a hard cut.
        canvas: "#0B0B0D",
        surface: "#141416",
        surfaceHover: "#1B1B1E",
        surfaceActive: "#232326",
        overlay: "#1E1E21",
        inset: "#08080A",

        separator: "#14FFFFFF",
        separatorStrong: "#26FFFFFF",

        textPrimary: "#F5F5F7",
        textSecondary: "#98989F",
        textTertiary: "#68686F",
        textOnAccent: "#FFFFFF",

        accent: "#7C5CFF",
        accentHover: "#8E72FF",
        accentPressed: "#6A48F0",
        accentSubtle: "#247C5CFF",

        success: "#30D158",
        warning: "#FF9F0A",
        danger: "#FF453A",
        info: "#0A84FF",

        shadow: "#000000",
        scrim: "#99000000"
    })

    readonly property var _light: ({
        canvas: "#FFFFFF",
        surface: "#F7F7F8",
        surfaceHover: "#F0F0F2",
        surfaceActive: "#E7E7EA",
        overlay: "#FFFFFF",
        inset: "#F2F2F4",

        separator: "#12000000",
        separatorStrong: "#24000000",

        textPrimary: "#1D1D1F",
        textSecondary: "#6E6E73",
        textTertiary: "#98989F",
        textOnAccent: "#FFFFFF",

        // Darker than the dark-mode accent: the same violet on white is too
        // light to carry text at 4.5:1.
        accent: "#6644EE",
        accentHover: "#7659F2",
        accentPressed: "#5636DC",
        accentSubtle: "#1A6644EE",

        success: "#248A3D",
        warning: "#B25000",
        danger: "#D70015",
        info: "#0071E3",

        shadow: "#000000",
        scrim: "#4D000000"
    })

    readonly property var _p: isDark ? _dark : _light

    // -- surfaces ----------------------------------------------------------

    property color canvas: _p.canvas
    /*! Raised panels: sidebar, cards, list rows. */
    property color surface: _p.surface
    property color surfaceHover: _p.surfaceHover
    property color surfaceActive: _p.surfaceActive
    /*! Popovers, menus, sheets — things floating above the window. */
    property color overlay: _p.overlay
    /*! Recessed areas: text fields, code blocks. Reads as *below* the surface. */
    property color inset: _p.inset

    // -- lines -------------------------------------------------------------

    /*! Hairlines between rows. Deliberately near-invisible. */
    property color separator: _p.separator
    /*! Borders meant to be seen: focused fields, card outlines. */
    property color separatorStrong: _p.separatorStrong

    // -- text --------------------------------------------------------------

    property color textPrimary: _p.textPrimary
    /*! Supporting text: timestamps, captions, inactive tabs. */
    property color textSecondary: _p.textSecondary
    /*! Placeholders and disabled text. Still clears 3:1 against `surface`. */
    property color textTertiary: _p.textTertiary
    property color textOnAccent: _p.textOnAccent

    // -- accent ------------------------------------------------------------

    property color accent: _p.accent
    property color accentHover: _p.accentHover
    property color accentPressed: _p.accentPressed
    /*! Accent at low alpha — selected rows, badge fills, focus rings. */
    property color accentSubtle: _p.accentSubtle

    // -- semantic ----------------------------------------------------------

    property color success: _p.success
    property color warning: _p.warning
    property color danger: _p.danger
    property color info: _p.info

    // -- effects -----------------------------------------------------------

    property color shadow: _p.shadow
    /*! Dims the window behind a modal sheet. */
    property color scrim: _p.scrim

    // -- helpers -----------------------------------------------------------

    /*!
        Pick legible text for an arbitrary background.

        Needed wherever the background is data rather than a design decision —
        accent buttons, status badges, project colours — because no fixed token
        is readable on every one of them.

        Uses WCAG relative luminance with the sRGB transfer function, not a
        naive average: at equal numeric value green reads far brighter than
        blue, and averaging puts white text on backgrounds it disappears into.
    */
    function contrastText(bg) {
        var c = Qt.color(bg);
        var lin = function (v) {
            return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
        };
        var l = 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
        // 0.36 rather than the midpoint: white-on-colour stays readable further
        // down the scale than black-on-colour does.
        return l > 0.36 ? "#1D1D1F" : "#FFFFFF";
    }

    // -- type --------------------------------------------------------------

    /*  Segoe UI Variable is Windows' optically-sized family and the closest
        thing on this platform to SF Pro. The three cuts are not stylistic
        alternatives — Display has tighter spacing and finer detail for large
        sizes, Text has wider apertures for reading, Small is hinted for
        captions. Using one cut at every size is the single most common reason
        a Windows interface fails to read as Apple-like.

        Crossover points follow the family's own design: Small below 12px,
        Display at 20px and above.  */
    readonly property QtObject font: QtObject {
        readonly property string display: "Segoe UI Variable Display"
        readonly property string text: "Segoe UI Variable Text"
        readonly property string small: "Segoe UI Variable Small"
        readonly property string mono: "Cascadia Mono"
    }

    readonly property QtObject type: QtObject {
        readonly property font hero: Qt.font({
            family: theme.font.display, pixelSize: 40,
            weight: Font.DemiBold, letterSpacing: -1.0
        })
        readonly property font title1: Qt.font({
            family: theme.font.display, pixelSize: 28,
            weight: Font.DemiBold, letterSpacing: -0.6
        })
        readonly property font title2: Qt.font({
            family: theme.font.display, pixelSize: 21,
            weight: Font.DemiBold, letterSpacing: -0.4
        })
        readonly property font title3: Qt.font({
            family: theme.font.display, pixelSize: 17,
            weight: Font.DemiBold, letterSpacing: -0.2
        })
        readonly property font headline: Qt.font({
            family: theme.font.text, pixelSize: 15, weight: Font.DemiBold
        })
        readonly property font body: Qt.font({
            family: theme.font.text, pixelSize: 14.5, weight: Font.Normal
        })
        readonly property font bodyStrong: Qt.font({
            family: theme.font.text, pixelSize: 14.5, weight: Font.DemiBold
        })
        readonly property font callout: Qt.font({
            family: theme.font.text, pixelSize: 13, weight: Font.Normal
        })
        readonly property font caption: Qt.font({
            family: theme.font.small, pixelSize: 11.5, weight: Font.Normal
        })
        readonly property font captionStrong: Qt.font({
            family: theme.font.small, pixelSize: 11.5, weight: Font.DemiBold
        })
        readonly property font mono: Qt.font({
            family: theme.font.mono, pixelSize: 13, weight: Font.Normal
        })
        readonly property font monoSmall: Qt.font({
            family: theme.font.mono, pixelSize: 11.5, weight: Font.Normal
        })
    }

    /*  Line heights as multipliers. QML has no line-height property, so these
        go through Text.lineHeight with lineHeightMode: ProportionalHeight.  */
    readonly property QtObject leading: QtObject {
        readonly property real tight: 1.15    // headings
        readonly property real normal: 1.35   // UI text
        readonly property real relaxed: 1.55  // prose and chat
    }

    // -- space -------------------------------------------------------------

    /*  A 4pt grid. Named rather than numbered so a layout change reads as a
        change of intent instead of arithmetic.  */
    readonly property QtObject space: QtObject {
        readonly property int xxs: 2
        readonly property int xs: 4
        readonly property int sm: 8
        readonly property int md: 12
        readonly property int lg: 16
        readonly property int xl: 24
        readonly property int xxl: 32
        readonly property int xxxl: 48
    }

    // -- shape -------------------------------------------------------------

    readonly property QtObject radius: QtObject {
        readonly property int xs: 6     // badges, tags
        readonly property int sm: 10    // buttons, fields
        readonly property int md: 14    // cards, message bubbles
        readonly property int lg: 20    // panels, sheets
        readonly property int xl: 28    // the window itself
        readonly property int full: 999
    }

    // -- motion ------------------------------------------------------------

    /*  Durations are scaled by motionScale, so the reduce-motion setting
        collapses every transition to zero without any component having to
        know the setting exists.  */
    readonly property real _s: theme.motionScale

    readonly property QtObject duration: QtObject {
        readonly property int instant: Math.round(90 * theme._s)
        readonly property int fast: Math.round(160 * theme._s)
        readonly property int normal: Math.round(240 * theme._s)
        readonly property int slow: Math.round(380 * theme._s)
        readonly property int slower: Math.round(560 * theme._s)
    }

    /*  Apple's interfaces almost never use symmetric easing. Motion leaves
        fast and arrives slow, which is what makes it feel like something with
        mass settling rather than a value being interpolated.

        bezierCurve takes [c1x, c1y, c2x, c2y, endX, endY] and must end at 1,1. */
    readonly property QtObject easing: QtObject {
        /*! The default. cubic-bezier(0.32, 0.72, 0, 1) — decisive exit, long settle. */
        readonly property var standard: [0.32, 0.72, 0.0, 1.0, 1.0, 1.0]
        /*! Entering the screen: no initial hesitation. */
        readonly property var enter: [0.16, 1.0, 0.3, 1.0, 1.0, 1.0]
        /*! Leaving: accelerate away, no lingering. */
        readonly property var exit: [0.7, 0.0, 0.84, 0.0, 1.0, 1.0]
        /*! Overshoots slightly, then settles. For things appearing under a cursor. */
        readonly property var spring: [0.34, 1.56, 0.64, 1.0, 1.0, 1.0]
    }

    // -- elevation ---------------------------------------------------------

    /*  Shadow opacity has to differ by mode. On a dark canvas a black shadow
        is nearly invisible, so dark mode leans on a brighter surface and a
        tighter, more opaque shadow to read as lifted.  */
    readonly property QtObject elevation: QtObject {
        readonly property real low: theme.isDark ? 0.44 : 0.10
        readonly property real mid: theme.isDark ? 0.55 : 0.14
        readonly property real high: theme.isDark ? 0.68 : 0.20
    }

}
