"""Search app-owned history without querying models or restoring stale results."""
import threading
import time

from PySide6.QtCore import QCoreApplication

from akira.core.conversation import Conversation
from akira.core.conversations import ConversationStore
from akira.ui.history_search import HistorySearch, matching_excerpt, search_saved


def save(store, title, answer, system="private instructions"):
    chat = Conversation(title=title, system_prompt=system)
    chat.add("user", "A general question")
    chat.add("assistant", answer)
    chat.add("system", "internal message")
    store.save(chat)
    return {"id": chat.id, "title": title, "when": "now", "turns": 3}


def wait_until(app, condition):
    deadline = time.monotonic() + 5
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert condition()


def test_matches_all_words_across_title_and_body_with_literal_unicode_excerpt(tmp_path):
    assert matching_excerpt("OCEAN strasse", ["Ocean", "Die Straße glows."]) == "Die Straße glows."
    assert matching_excerpt("ocean missing", ["Ocean", "Currents."]) is None
    store = ConversationStore(tmp_path)
    rows = [save(store, "Untitled expedition", '<img src="file://outside"> Bioluminescent currents')]
    found, note = search_saved(store, rows, "expedition bioluminescent", threading.Event())
    assert found[0]["id"] == rows[0]["id"]
    assert '<img src="file://outside">' in found[0]["snippet"]  # Rendering must stay plaintext.
    assert "1 recent" in note
    assert search_saved(store, rows, "private instructions", threading.Event())[0] == []
    assert search_saved(store, rows, "internal message", threading.Event())[0] == []


def test_missing_corrupt_and_invalid_ids_do_not_break_other_matches(tmp_path):
    store = ConversationStore(tmp_path)
    valid = save(store, "Notes", "needle")
    corrupt = save(store, "Broken", "needle")
    (tmp_path / (corrupt["id"] + ".json")).write_text("broken", encoding="utf-8")
    rows = [{"id": "../outside"}, {"id": "a" * 32}, corrupt, valid]
    found, note = search_saved(store, rows, "needle", threading.Event())
    assert [r["id"] for r in found] == [valid["id"]]
    assert "3 could not be searched" in note


def test_result_limit_is_visible_and_cancellation_stops_reading(tmp_path):
    store = ConversationStore(tmp_path)
    rows = [save(store, f"Note {i}", "needle") for i in range(42)]
    found, note = search_saved(store, rows, "needle", threading.Event())
    assert len(found) == 40 and found[0]["id"] == rows[0]["id"]
    assert "newest 40" in note
    cancelled = threading.Event(); cancelled.set()
    assert search_saved(store, rows, "needle", cancelled) == ([], "")


def test_search_runs_one_worker_and_never_publishes_a_stale_query(tmp_path, monkeypatch):
    import akira.ui.history_search as module
    app = QCoreApplication.instance() or QCoreApplication([])
    gate, entered = threading.Event(), threading.Event()
    active, max_active, seen = 0, 0, []
    def scan(store, candidates, query, cancelled):
        nonlocal active, max_active
        active += 1; max_active = max(max_active, active); seen.append(query)
        if query == "first":
            entered.set(); gate.wait(4)
        active -= 1
        return [{"id": query}], query
    monkeypatch.setattr(module, "search_saved", scan)
    bridge = HistorySearch(ConversationStore(tmp_path), lambda: [])
    bridge.search("first"); assert entered.wait(2)
    bridge.search("second"); bridge.clear(); bridge.search("third")
    assert bridge.results == [] and bridge.busy
    gate.set(); wait_until(app, lambda: not bridge.busy)
    assert bridge.results == [{"id": "third"}]
    assert seen == ["first", "third"] and max_active == 1
    bridge.close(); bridge.search("closed")
    assert bridge.results == [] and not bridge.busy


def test_refresh_rechecks_saved_content_and_clearing_removes_previews(tmp_path):
    app = QCoreApplication.instance() or QCoreApplication([])
    store = ConversationStore(tmp_path)
    row = save(store, "My question", "needle")
    bridge = HistorySearch(store, lambda: [row])
    bridge.search("needle"); wait_until(app, lambda: not bridge.busy)
    assert len(bridge.results) == 1
    store.delete(row["id"])
    bridge.refresh(); wait_until(app, lambda: not bridge.busy)
    assert not bridge.results and "could not be searched" in bridge.note
    bridge.clear()
    assert not bridge.note and not bridge.busy and not bridge.results
