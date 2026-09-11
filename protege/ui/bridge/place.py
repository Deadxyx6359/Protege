"""Where the person is, as they chose to say — the `Place` bridge.

Setting a place grants nothing. Models are told it, with the time zone, only
while `location.read` is granted; see `protege.core.context.place`. The scenes
use its hemisphere to turn the seasons the right way round, which needs no
permission because nothing leaves the screen.
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.context.place import PlaceError, PlaceStore, check_place, season


class PlaceBridge(QObject):
    """The place the person set, and its hemisphere."""

    placeChanged = Signal()

    def __init__(self, store: PlaceStore | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store if store is not None else PlaceStore()
        self._place = self._store.load()

    @property
    def store(self) -> PlaceStore:
        return self._store

    @Property(str, notify=placeChanged)
    def name(self) -> str:
        return self._place.name

    @Property(str, notify=placeChanged)
    def hemisphere(self) -> str:
        """`north`, `south`, or "" when not given."""
        return self._place.hemisphere

    @Property(bool, notify=placeChanged)
    def southernHemisphere(self) -> bool:
        """For `SceneHost.southernHemisphere`."""
        return self._place.southern

    @Property(str, notify=placeChanged)
    def season(self) -> str:
        """Today's season in that hemisphere, by the scenes' own rule."""
        return season(date.today(), self._place.southern)

    @Slot(str, str, result=str)
    def setPlace(self, name: str, hemisphere: str) -> str:
        """Keep where the person is. Returns "" or why not."""
        try:
            place = check_place(name, hemisphere)
            self._store.save(place)
        except PlaceError as exc:
            return str(exc)
        except OSError as exc:
            return f"The place could not be saved: {exc}"
        self._place = place
        self.placeChanged.emit()
        return ""

    @Slot()
    def clearPlace(self) -> None:
        self._store.clear()
        self._place = self._store.load()
        self.placeChanged.emit()
