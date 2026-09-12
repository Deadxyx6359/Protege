"""`AgentTrace.recent`: the newest events as plain maps, for views that draw a run."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from akira.core.agents.trace import Kind, Trace  # noqa: E402
from akira.ui.bridge.trace import TraceBridge  # noqa: E402


def test_the_newest_events_come_as_maps_oldest_first():
    trace = Trace()
    trace.emit(Kind.STARTED, "gatherer", text="find sources")
    trace.emit(Kind.TOOL_CALL, "gatherer", tool="read_file")
    trace.emit(Kind.MESSAGE, "gatherer", to="analyst", text="here is what I found")
    bridge = TraceBridge(trace)

    rows = bridge.recent(2)
    assert [row["kind"] for row in rows] == ["tool_call", "message"]
    assert rows[0]["tool"] == "read_file" and rows[0]["agent"] == "gatherer"
    assert rows[1]["recipient"] == "analyst"
    assert len(bridge.recent(100)) == 3

    bridge.clear()
    assert bridge.recent(10) == []
