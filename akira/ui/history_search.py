"""Local presentation search: bounded excerpts, latest request wins.

Only saved user/assistant messages are read. This is not retrieval for a model,
and does not search project files, credentials, source caches or system prompts.
"""
from __future__ import annotations

import re
import threading

from PySide6.QtCore import QObject, Property, Signal, Slot

from akira.core.conversations import ConversationError, MAX_BYTES


def terms(query: str) -> list[str]:
    return str(query).strip()[:200].casefold().split()


def matching_excerpt(query: str, fields: list[str]) -> str | None:
    """All words may occur in different fields; show a short matching passage."""
    words = terms(query)
    clean = [" ".join(str(field).split()) for field in fields]
    folded = [field.casefold() for field in clean]
    if not words:
        return ""
    if not all(any(word in field for field in folded) for word in words):
        return None
    # Prefer body fields over the title when both match.
    for index in list(range(1, len(clean))) + [0]:
        offsets = [folded[index].find(word) for word in words if word in folded[index]]
        if offsets:
            offset = min(offsets)
            # Folded Unicode can have a different length (e.g. ß -> ss).
            position = 0
            while position < len(clean[index]) and offset > 0:
                offset -= len(clean[index][position].casefold())
                position += 1
            start = max(0, position - 45)
            return ("…" if start else "") + clean[index][start:start + 170] + ("…" if len(clean[index]) > start + 170 else "")
    return ""


def search_saved(store, candidates: list[dict], query: str, cancelled: threading.Event):
    """Search at most 200 known ids / 32 MiB; never follow a saved-file link."""
    results, skipped, used = [], 0, 0
    for row in candidates[:200]:
        if cancelled.is_set():
            return [], ""
        try:
            ident = row["id"]
            if not re.fullmatch(r"[0-9a-f]{8,64}", ident):
                raise ValueError("Invalid saved id")
            path = store.directory / (ident + ".json")
            if path.is_symlink() or path.is_junction():
                raise ValueError("Linked saved file")
            size = path.stat().st_size
            if size > MAX_BYTES or used + size > 32 * 1024 * 1024:
                skipped += 1
                continue
            used += size
            conversation = store.load(ident)
            fields = [conversation.title] + [m.text for m in conversation.messages if m.role in ("user", "assistant")]
            snippet = matching_excerpt(query, fields)
            if snippet is not None:
                results.append({**row, "snippet": snippet})
        except (ConversationError, OSError, ValueError, TypeError, AttributeError):
            skipped += 1
    note = f"Searched {min(200, len(candidates))} recent saved chats on this device."
    if skipped:
        note += f" {skipped} could not be searched or exceeded the size limit."
    if len(results) > 40:
        note += " Showing the newest 40 matches; add words to narrow the search."
    return results[:40], note


class HistorySearch(QObject):
    changed = Signal()
    _finished = Signal(object)

    def __init__(self, store, candidates, parent=None):
        super().__init__(parent)
        self._store, self._candidates = store, candidates
        self._query, self._note, self._results = "", "", []
        self._busy = False
        self._serial = 0
        self._cancel = threading.Event()
        self._active = False
        self._pending = None
        self._closed = False
        self._finished.connect(self._receive)

    @Property("QVariantList", notify=changed)
    def results(self):
        return self._results

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def note(self):
        return self._note

    @Slot()
    def clear(self):
        self._serial += 1
        self._cancel.set()
        self._pending = None
        self._query, self._note, self._results = "", "", []
        self._busy = False
        self.changed.emit()

    @Slot(str)
    def search(self, query):
        self.clear()
        if self._closed or not terms(query):
            return
        self._query = query[:200]
        self._busy = True
        self._pending = (self._serial, self._query, list(self._candidates()))
        self.changed.emit()
        self._launch()

    def refresh(self):
        if self._query:
            self.search(self._query)

    def close(self):
        self._closed = True
        self.clear()

    def _launch(self):
        if self._active or self._pending is None:
            return
        serial, query, candidates = self._pending
        self._pending = None
        self._active = True
        self._cancel = cancelled = threading.Event()
        def work():
            try:
                rows, note = search_saved(self._store, candidates, query, cancelled)
            except Exception:
                rows, note = [], "Saved chats could not be searched. Try again."
            try:
                self._finished.emit((serial, rows, note))
            except RuntimeError:
                # The window/parent may have been destroyed while a file read
                # was finishing. No result should reach a new window.
                pass
        threading.Thread(target=work, name="history-search", daemon=True).start()

    @Slot(object)
    def _receive(self, payload):
        serial, rows, note = payload
        self._active = False
        if serial == self._serial and not self._closed:
            self._results, self._note, self._busy = rows, note, False
            self.changed.emit()
        self._launch()
