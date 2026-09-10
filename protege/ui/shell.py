"""Entry point for the Qt shell.

Separate from ``app.py``, which is the Tkinter window being replaced. Both are
runnable for now: the rebuild is a long job, and taking away the working
application on day one would leave nothing to use in the meantime.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QGuiApplication, QIcon

from protege.core.config import AppConfig, autoconfigure
from protege.core.models import ModelRouter, Route
from protege.design import ThemeController
from protege.ui.bridge import ChatBridge, SettingsBridge

from .engine import QML_ROOT, QmlError, build_engine, configure_application, load

MAIN_QML = QML_ROOT / "Main.qml"
ICON = Path(__file__).parent / "assets" / "protege.ico"


@dataclass
class AppContext:
    """Everything the QML engine needs, and everything Python must keep alive.

    Context properties do not take ownership. Without a strong reference here,
    the first garbage collection after startup frees an object QML is still
    bound to, and the process dies inside a binding re-evaluation.
    """

    config: AppConfig
    router: ModelRouter
    theme: ThemeController
    chat: ChatBridge
    settings: SettingsBridge

    def as_context(self) -> dict:
        """The name → object map exposed to QML."""
        return {"Chat": self.chat, "Settings": self.settings}

    def close(self) -> None:
        # Order matters: save before unloading. A crash during model teardown
        # would otherwise take the last turn with it.
        self.chat.flush()
        # Several gigabytes of model. Leaving it to interpreter shutdown means
        # llama.cpp's destructor races the Python teardown it depends on.
        self.router.close()


def build_context(*, persist: bool = True) -> AppContext:
    """Load configuration and construct the object graph behind the interface.

    Shared with ``tools/preview.py`` so a screenshot exercises the same wiring
    the application does — a view that renders in the preview but not in the
    app is almost always a divergence here.
    """
    config = AppConfig.load()
    if autoconfigure(config) and persist:
        # Persisting immediately means the discovered paths are visible in
        # Settings rather than being silently re-derived on every launch.
        try:
            config.save()
        except OSError as exc:
            print(f"Could not save configuration: {exc}", file=sys.stderr)

    router = ModelRouter(config)
    theme = ThemeController(
        mode=config.appearance,
        reduce_motion=config.reduce_motion,
        on_change=(
            (lambda mode, reduce: _persist_appearance(config, mode, reduce))
            if persist
            else None
        ),
    )
    return AppContext(
        config=config,
        router=router,
        theme=theme,
        chat=ChatBridge(router, config),
        settings=SettingsBridge(config, router),
    )


def run_shell(argv: list[str] | None = None) -> int:
    """Start the interface and run until the last window closes."""
    app = QGuiApplication(argv if argv is not None else sys.argv)
    configure_application(app)

    if ICON.is_file():
        app.setWindowIcon(QIcon(str(ICON)))

    ctx = build_context()
    engine, theme = build_engine(theme=ctx.theme, context=ctx.as_context())

    try:
        load(engine, MAIN_QML)
    except QmlError as exc:
        print(exc, file=sys.stderr)
        return 1

    # Without this the process lingers after the window closes, because the
    # engine still holds the root object and Qt has nothing left to quit on.
    engine.quit.connect(app.quit)

    if ctx.config.preload:
        # On a worker thread, and started only after the window exists: loading
        # several gigabytes takes seconds, and doing it before the first frame
        # would turn a fast launch into a hang with nothing on screen.
        threading.Thread(
            target=ctx.router.warm,
            args=(Route.parse(ctx.config.default_route),),
            name="preload",
            daemon=True,
        ).start()

    try:
        return app.exec()
    finally:
        ctx.close()


def _persist_appearance(config: AppConfig, mode: str, reduce_motion: bool) -> None:
    config.appearance = mode
    config.reduce_motion = reduce_motion
    try:
        config.save()
    except OSError:
        # A preference that failed to save is not worth interrupting anyone
        # over; it will simply be the default again next launch.
        pass


if __name__ == "__main__":
    raise SystemExit(run_shell())
