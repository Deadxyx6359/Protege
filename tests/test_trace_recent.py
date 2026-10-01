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


def test_activity_tracks_background_work_without_retaining_private_text():
    trace = Trace()
    bridge = TraceBridge(trace)
    trace.emit(Kind.STARTED, "secretary", text="private scheduled task")
    trace.emit(Kind.TOOL_CALL, "secretary", tool="read_file", arguments={"path": "private"})
    assert bridge.activity["secretary"]["label"] == "Using read_file"
    assert bridge.activity["secretary"]["working"]
    assert "private" not in str(bridge.activity)
    # Capped scrollback and clearing it must not lose the live agent state.
    for _ in range(510):
        trace.emit(Kind.NOTE, "scheduler", text="heartbeat")
    for i in range(510):
        trace.emit(Kind.ANSWER, "finished-job-" + str(i))
    assert len(bridge.activity) == 500
    bridge.clear()
    assert bridge.events.count == 0
    assert bridge.activity["secretary"]["working"]
    trace.emit(Kind.TOOL_RESULT, "secretary", ok=False, tool="read_file")
    assert bridge.activity["secretary"]["label"] == "Tool declined"
    trace.emit(Kind.FAILED, "secretary", text="cancelled")
    assert bridge.activity["secretary"]["label"] == "Stopped"
    assert not bridge.activity["secretary"]["working"]
    copy = bridge.activity
    copy["secretary"]["label"] = "Changed"
    assert bridge.activity["secretary"]["label"] == "Stopped"
    bridge.attach(Trace())
    assert bridge.activity == {}
