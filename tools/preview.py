#!/usr/bin/env python3
"""Render a QML file to PNG.

Building an interface by launching it, looking, closing it and editing is slow
and leaves no record. This renders a QML root to an image instead, so a visual
change can be checked the same way a test is — and in both appearances at once,
which is where most colour mistakes actually surface.

    python tools/preview.py akira/ui/qml/Gallery.qml --mode both
    python tools/preview.py path/to/Thing.qml --out shot.png --size 1200x800

The file must have a Window or ApplicationWindow at its root.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from akira.ui.engine import build_engine, configure_application, load  # noqa: E402
from akira.ui.shell import build_context  # noqa: E402


def _size(text: str) -> tuple[int, int]:
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 1280x800") from None


def _settle(window, ms: int) -> None:
    """Run the event loop so animations reach their resting state.

    Frames have to be forced. Qt Quick advances animations per rendered frame,
    and a window nothing is asking to redraw simply does not render — so a
    plain event loop leaves every Behavior frozen at its starting value and the
    screenshot shows the *old* colours after a theme switch. Requesting an
    update on a timer is what makes the grab reflect the settled state.
    """
    loop = QEventLoop()
    pump = QTimer()
    pump.setInterval(16)
    pump.timeout.connect(window.requestUpdate)
    pump.start()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()
    pump.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="preview", description=__doc__)
    parser.add_argument("qml", help="QML file with a Window at its root")
    parser.add_argument("--out", help="output PNG (default: alongside the QML file)")
    parser.add_argument("--size", type=_size, help="override the window size, e.g. 1280x800")
    parser.add_argument("--view", choices=("chats", "code", "research", "documents", "memory"), help="workspace to render in Main.qml")
    parser.add_argument(
        "--mode",
        choices=("dark", "light", "both"),
        default="dark",
        help="appearance to render (default: dark)",
    )
    parser.add_argument(
        "--settle",
        type=int,
        default=400,
        help="milliseconds to let layout settle before grabbing (default: 400)",
    )
    parser.add_argument(
        "--motion",
        action="store_true",
        help="leave animations running (default: collapsed, for deterministic output)",
    )
    args = parser.parse_args(argv)

    qml_path = Path(args.qml).resolve()
    out = Path(args.out).resolve() if args.out else qml_path.with_suffix(".png")

    app = QGuiApplication(sys.argv[:1])
    configure_application(app)

    modes = ("dark", "light") if args.mode == "both" else (args.mode,)

    # persist=False: rendering a screenshot must not rewrite the user's config.
    ctx = build_context(persist=False)
    theme = ctx.theme
    theme.mode = modes[0]
    # Animations off by default. A screenshot taken while transitions are in
    # flight is a race: whether it captures the old colour, the new one, or a
    # blend depends on how fast the machine drew the preceding frames. Reusing
    # the reduce-motion setting collapses every duration to zero, so a grab is
    # always of the resting state.
    theme.reduceMotion = not args.motion

    engine, theme = build_engine(theme=theme, context=ctx.as_context())
    window = load(engine, qml_path)
    if args.view and not window.setProperty("currentNav", args.view):
        parser.error("--view requires a root with a currentNav property (Main.qml)")

    if args.size:
        window.setWidth(args.size[0])
        window.setHeight(args.size[1])
    window.setVisible(True)

    written: list[Path] = []
    for mode in modes:
        theme.mode = mode
        # Long enough for the palette cross-fade (340ms) plus whatever the
        # scene itself is doing.
        _settle(window, args.settle)

        target = out if len(modes) == 1 else out.with_suffix(f".{mode}.png")
        image = window.grabWindow()
        if image.isNull():
            print("grab returned nothing — is the window visible?", file=sys.stderr)
            return 1
        image.save(str(target))
        written.append(target)
        print(f"{mode:>5}  {target}  {image.width()}x{image.height()}")

    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
