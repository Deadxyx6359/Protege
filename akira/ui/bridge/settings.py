"""Settings, as QML sees it.

Reads and writes ``AppConfig``, and reports what the router knows about each
route. Changing a model path here reaches the router immediately — a setting
that only takes effect after a restart is a setting people stop trusting.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.config import (
    MODELS_DIR,
    AppConfig,
    ModelConfig,
    discover_models,
)
from akira.core.models import ModelRouter, Route


def _human_size(path: Path) -> str:
    try:
        return f"{path.stat().st_size / 1024**3:.1f} GB"
    except OSError:
        return "—"


class SettingsBridge(QObject):
    """Appearance and model configuration."""

    routesChanged = Signal()
    availableChanged = Signal()
    savedChanged = Signal()

    def __init__(
        self,
        config: AppConfig,
        router: ModelRouter,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._router = router

    # -- what exists --------------------------------------------------------

    @Property("QVariantList", notify=availableChanged)
    def availableModels(self) -> list:
        """Every GGUF found on disk, smallest first.

        Smallest first because that is the useful ordering here: on 15.7 GB of
        RAM the small ones are the candidates, and the big one is the reason
        the application feels slow.
        """
        return [
            {"path": str(p), "name": p.stem, "size": _human_size(p)}
            for p in discover_models()
        ]

    @Property(str, constant=True)
    def modelsDirectory(self) -> str:
        return str(MODELS_DIR)

    @Property("QVariantList", notify=routesChanged)
    def routes(self) -> list:
        """One entry per route, with what is assigned and whether it is loaded."""
        described = {
            Route.CHAT: ("Chat", "Everyday conversation"),
            Route.CODE: ("Code", "Writing and reviewing code"),
            Route.FAST: ("Fast", "Titles and quick classification"),
            Route.DEEP: ("Deep", "Hard reasoning and long documents"),
        }
        out = []
        for route in Route:
            status = self._router.status(route)
            model = self._config.models.get(route.value, ModelConfig())
            label, blurb = described[route]
            out.append(
                {
                    "id": route.value,
                    "label": label,
                    "blurb": blurb,
                    "path": model.path,
                    "name": status.label,
                    "detail": status.detail,
                    "usable": status.usable,
                    "loaded": status.loaded,
                    "contextTokens": model.n_ctx,
                    "maxTokens": model.max_tokens,
                    "gpuLayers": model.n_gpu_layers,
                }
            )
        return out

    # -- changing things ----------------------------------------------------

    @Slot(str, str)
    def assign(self, route_name: str, path: str) -> None:
        """Point \a route_name at \a path, or clear it when \a path is empty."""
        route = Route.parse(route_name)
        current = self._config.models.get(route.value, ModelConfig())
        self._config.models[route.value] = replace(current, path=path)
        self._apply()

    @Slot(str, str, int)
    def setNumber(self, route_name: str, field: str, value: int) -> None:
        """Update one numeric setting on a route.

        Whitelisted rather than passed through to ``setattr``: this is called
        from QML, and a settings panel that can assign any attribute on a
        config object is a much larger surface than it needs to be.
        """
        allowed = {"n_ctx", "max_tokens", "n_gpu_layers", "n_threads"}
        if field not in allowed:
            return

        route = Route.parse(route_name)
        current = self._config.models.get(route.value, ModelConfig())
        self._config.models[route.value] = replace(current, **{field: int(value)})
        self._apply()

    @Slot()
    def refresh(self) -> None:
        """Re-scan the models directory. For after dropping a file in."""
        self.availableChanged.emit()
        self.routesChanged.emit()

    def _apply(self) -> None:
        # The router drops any backend whose path changed, so the next turn
        # loads the new file rather than continuing on the old one.
        self._router.update(self._config)
        try:
            self._config.save()
        except OSError:
            pass
        self.routesChanged.emit()
        self.savedChanged.emit()
