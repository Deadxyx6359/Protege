"""The `Place` bridge: the person's place, checked and kept, and the hemisphere
the scenes turn their seasons by.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from protege.core.context.place import PlaceStore  # noqa: E402
from protege.ui.bridge.place import PlaceBridge  # noqa: E402


def test_a_place_is_set_checked_and_cleared(tmp_path):
    store = PlaceStore(tmp_path / "place.json")
    bridge = PlaceBridge(store)
    changes = []
    bridge.placeChanged.connect(lambda: changes.append(1))

    assert (bridge.name, bridge.hemisphere, bridge.southernHemisphere) == ("", "", False)
    assert bridge.setPlace("Sydney", "west") != "" and not changes
    assert bridge.setPlace("Sydney, Australia", "south") == ""
    assert bridge.name == "Sydney, Australia" and bridge.southernHemisphere and changes
    assert bridge.season in {"winter", "spring", "summer", "autumn"}
    assert PlaceBridge(store).name == "Sydney, Australia", "the place was not kept"

    bridge.clearPlace()
    assert (bridge.name, bridge.southernHemisphere) == ("", False)
