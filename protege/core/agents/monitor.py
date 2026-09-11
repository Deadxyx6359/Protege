"""Watching for change: the monitoring agent's local half (C6).

A watch is a folder the person chose. Every so often each one is looked at, and
what changed since becomes scheduler events that jobs can wait for:
`file.created`, `file.changed` and `file.deleted` for each file, and one
`folder.changed` for the lot. A job on `folder.changed` for a watch can run an
agent over what arrived, or put up a notice with the `notify` action here.

**Held to the permission on every look.** Listing a folder is `files.read`
there, as it is for `list_directory`. It is checked against the global grants at
each look, not once when the watch is made, so revoking it stops the watch at
the next look, and the watch says why instead of failing silently. Watches run
in the background like scheduled jobs, so like them they use the global grants,
never the open project's.

**A file is reported once it has settled.** A change is announced only when the
file looks the same on two looks in a row, so a job never wakes to a download or
a save still in progress. A file that never stops changing, such as a log, is
not announced until it does.

**Polling, not OS notifications.** It needs nothing beyond the standard library,
behaves the same on every filesystem, synced folders included, and costs a
directory walk per look. A watch that grows past `MAX_FILES` pauses and says so,
rather than letting one enormous folder turn the walk into a load.

Pages, inboxes and feeds are watched the same way once the network chokepoint
(C1) and the connectors (C5) exist. Until then only folders are.
"""

from __future__ import annotations

import contextlib
import fnmatch
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from protege.core.config import config_dir
from protege.core.permissions import AuditLog, Policy
from protege.core.schedule import ActionRegistry, ActionResult, JobContext
from protege.security.paths import PathViolation, real

NOTIFY_ACTION = "notify"
POLL_S = 30.0
MAX_FILES = 5_000
MAX_FILE_EVENTS = 50
MAX_WATCHES = 20
MAX_PATTERNS = 10
MAX_TITLE_CHARS = 80
MAX_NOTICE_CHARS = 600

#: Folders never walked: version control, Obsidian's own, caches.
SKIPPED_DIRS = frozenset({".git", ".obsidian", ".trash", "node_modules", "__pycache__"})

#: Files still arriving. A browser renames them when the download finishes.
PARTIAL_SUFFIXES = (".tmp", ".crdownload", ".part", ".partial", ".download")

_ID = re.compile(r"\A[0-9a-f]{16}\Z")

#: Who the activity log records when a watch is paused.
ACTOR = "monitor"


class MonitorError(ValueError):
    """Something a watch will not do, with a reason for the person."""


@dataclass
class Watch:
    id: str
    folder: str
    patterns: tuple[str, ...] = ()
    """File name patterns such as `*.pdf`. Empty watches every file."""

    created: float = 0.0
    paused: str = ""
    """Why it is not being looked at, for the person. Empty while it is."""

    def wants(self, name: str) -> bool:
        lowered = name.lower()
        return not self.patterns or any(fnmatch.fnmatchcase(lowered, p.lower())
                                        for p in self.patterns)

    def to_json(self) -> dict:
        return {"id": self.id, "folder": self.folder, "patterns": list(self.patterns),
                "created": self.created}

    @classmethod
    def from_json(cls, data: dict) -> "Watch":
        if not _ID.match(str(data.get("id", ""))) or not str(data.get("folder", "")).strip():
            raise ValueError("not a watch")
        patterns = data.get("patterns") or []
        if not isinstance(patterns, list):
            raise ValueError("patterns must be a list")
        return cls(str(data["id"]), str(data["folder"]), _clean_patterns(patterns),
                   float(data.get("created") or 0.0))


def _clean_patterns(patterns) -> tuple[str, ...]:
    cleaned: list[str] = []
    for raw in patterns or ():
        pattern = str(raw).strip()
        if not pattern:
            continue
        if len(pattern) > 40 or "/" in pattern or "\\" in pattern:
            raise MonitorError(f"{pattern!r} is not a file name pattern. Use something like *.pdf.")
        if pattern.lower() not in (p.lower() for p in cleaned):
            cleaned.append(pattern)
    if len(cleaned) > MAX_PATTERNS:
        raise MonitorError(f"A watch takes at most {MAX_PATTERNS} patterns.")
    return tuple(cleaned)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


class WatchStore:
    """`watches.json`, written atomically, read defensively."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "watches.json"
        self.warnings: list[str] = []

    def load(self) -> list[Watch]:
        if not self.path.exists():
            return []
        try:
            entries = json.loads(self.path.read_text(encoding="utf-8"))["watches"]
            if not isinstance(entries, list):
                raise ValueError("watches must be a list")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            moved = self.path.with_name(f"{self.path.name}.damaged-{int(time.time())}")
            with contextlib.suppress(OSError):
                os.replace(self.path, moved)
            self.warnings.append(f"The list of watched folders was damaged ({exc}). It was "
                                 f"moved aside to {moved.name}; nothing is being watched.")
            return []
        watches = []
        for entry in entries:
            try:
                watches.append(Watch.from_json(entry))
            except (ValueError, TypeError, AttributeError):
                self.warnings.append("A watched folder could not be read, so it is not "
                                     "being watched.")
        return watches

    def save(self, watches: list[Watch]) -> None:
        _write_json(self.path, {"version": 1, "watches": [w.to_json() for w in watches]})


def snapshot(folder: Path, watch: Watch, limit: int | None = None) -> dict[str, tuple[int, int]] | None:
    """Every file \a watch wants, as path → (modified, size). None if past \a limit."""
    limit = MAX_FILES if limit is None else limit
    found: dict[str, tuple[int, int]] = {}
    for current, folders, files in os.walk(folder):
        folders[:] = sorted(f for f in folders if not f.startswith(".") and f not in SKIPPED_DIRS)
        for name in files:
            lowered = name.lower()
            if name.startswith((".", "~$")) or lowered.endswith(PARTIAL_SUFFIXES):
                continue
            if not watch.wants(name):
                continue
            path = Path(current) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            found[path.relative_to(folder).as_posix()] = (stat.st_mtime_ns, stat.st_size)
            if len(found) > limit:
                return None
    return found


class Monitor:
    """Looks at every watch and publishes what changed."""

    def __init__(self, store: WatchStore, *, policy: Callable[[], Policy],
                 publish: Callable[[str, dict], None], audit: AuditLog | None = None) -> None:
        self._store = store
        self._policy = policy
        self._publish = publish
        self._audit = audit
        self._on_change: Callable[[], None] | None = None
        self._lock = threading.RLock()
        self._watches: dict[str, Watch] = {w.id: w for w in store.load()}
        self._seen: dict[str, dict[str, tuple[int, int]]] = {}
        self._settled: dict[str, dict[str, tuple[int, int]]] = {}
        self.last_change: dict[str, float] = {}

    @property
    def warnings(self) -> list[str]:
        return list(self._store.warnings)

    def set_on_change(self, callback: Callable[[], None] | None) -> None:
        """Called, from any thread, when a watch is added, removed, paused or fires."""
        self._on_change = callback

    def _changed(self) -> None:
        callback = self._on_change
        if callback is not None:
            with contextlib.suppress(Exception):
                callback()

    def _save(self) -> None:
        try:
            self._store.save(list(self._watches.values()))
        except OSError as exc:
            self._store.warnings.append(f"The watched folders could not be saved: {exc}")

    # -- the watches --------------------------------------------------------------------

    def watches(self) -> list[Watch]:
        with self._lock:
            return sorted(self._watches.values(), key=lambda w: (w.folder.lower(), w.patterns))

    def add(self, folder: str, patterns=()) -> Watch:
        """Watch a folder. Raises `MonitorError` with the reason when it cannot be."""
        text = (folder or "").strip()
        if not text:
            raise MonitorError("Choose a folder to watch.")
        try:
            path = real(text)
        except (PathViolation, OSError, ValueError) as exc:
            raise MonitorError(f"{text} cannot be watched: {exc}") from None
        if not path.is_dir():
            raise MonitorError(f"{text} is not a folder.")
        decision = self._policy().allows("files.read", str(path))
        if not decision:
            raise MonitorError(f"Not permitted: {decision.reason}. Watching a folder reads its "
                               f"list of files, so allow reading files in {path} first.")
        cleaned = _clean_patterns(patterns)
        with self._lock:
            for watch in self._watches.values():
                if watch.folder.lower() == str(path).lower() and watch.patterns == cleaned:
                    return watch
            if len(self._watches) >= MAX_WATCHES:
                raise MonitorError(f"There are already {MAX_WATCHES} watched folders. "
                                   "Remove one first.")
            watch = Watch(secrets.token_hex(8), str(path), cleaned, time.time())
            self._watches[watch.id] = watch
            self._save()
        self._changed()
        return watch

    def remove(self, watch_id: str) -> bool:
        with self._lock:
            removed = self._watches.pop(watch_id, None) is not None
            self._seen.pop(watch_id, None)
            self._settled.pop(watch_id, None)
            if removed:
                self._save()
        if removed:
            self._changed()
        return removed

    # -- looking ----------------------------------------------------------------------------

    def poll(self) -> int:
        """Look at every watch once. Returns how many events were published."""
        count = 0
        for watch in self.watches():
            try:
                count += self._look(watch)
            except OSError as exc:
                self._pause(watch, f"{watch.folder} could not be read: {exc}")
        return count

    def _pause(self, watch: Watch, reason: str) -> None:
        with self._lock:
            if watch.paused == reason:
                return
            watch.paused = reason
            # Not looking means not knowing: the next look starts afresh
            # rather than reporting everything that changed meanwhile.
            self._seen.pop(watch.id, None)
            self._settled.pop(watch.id, None)
        if self._audit is not None:
            self._audit.tool_call(ACTOR, "watch_folder", {"folder": watch.folder},
                                  allowed=False, capability="files.read", scope=watch.folder,
                                  error=reason)
        self._changed()

    def _look(self, watch: Watch) -> int:
        decision = self._policy().allows("files.read", watch.folder)
        if not decision:
            self._pause(watch, f"Not permitted: {decision.reason}.")
            return 0
        folder = Path(watch.folder)
        if not folder.is_dir():
            self._pause(watch, f"{watch.folder} is not there any more.")
            return 0
        current = snapshot(folder, watch)
        if current is None:
            self._pause(watch, f"{watch.folder} has more than {MAX_FILES} files to watch. "
                               "Narrow it with a pattern such as *.pdf, or watch a smaller "
                               "folder.")
            return 0

        with self._lock:
            if watch.paused:
                watch.paused = ""
                resumed = True
            else:
                resumed = False
            seen = self._seen.get(watch.id)
            settled = self._settled.get(watch.id)
            self._seen[watch.id] = current
            if seen is None or settled is None:
                # The first look is the baseline: what is already there is not news.
                self._settled[watch.id] = dict(current)
                created = changed = deleted = []
            else:
                created, changed, deleted = [], [], []
                for rel, stamp in current.items():
                    # Reported only once it looks the same on two looks running.
                    if seen.get(rel) == stamp and settled.get(rel) != stamp:
                        (changed if rel in settled else created).append(rel)
                        settled[rel] = stamp
                for rel in [r for r in settled if r not in current and r not in seen]:
                    deleted.append(rel)
                    del settled[rel]
        if resumed:
            self._changed()
        if not (created or changed or deleted):
            return 0
        return self._announce(watch, sorted(created), sorted(changed), sorted(deleted))

    def _announce(self, watch: Watch, created: list[str], changed: list[str],
                  deleted: list[str]) -> int:
        published = 0
        for kind, paths in (("created", created), ("changed", changed), ("deleted", deleted)):
            for rel in paths:
                if published >= MAX_FILE_EVENTS:
                    break
                self._publish(f"file.{kind}", {"watch": watch.id, "folder": watch.folder,
                                               "path": rel, "name": rel.rsplit("/", 1)[-1]})
                published += 1
        self._publish("folder.changed", {
            "watch": watch.id, "folder": watch.folder, "created": len(created),
            "changed": len(changed), "deleted": len(deleted),
            "paths": (created + changed + deleted)[:20]})
        self.last_change[watch.id] = time.time()
        self._changed()
        return published + 1


class MonitorService:
    """The thread that looks at the watches."""

    def __init__(self, monitor: Monitor, *, interval_s: float = POLL_S) -> None:
        self._monitor = monitor
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="monitor", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            # The thread must outlive any one look.
            with contextlib.suppress(Exception):
                self._monitor.poll()
            self._stop.wait(self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)


# -- notices ------------------------------------------------------------------------------


def describe_event(name: str, payload: dict) -> str:
    """What an event was, in a sentence for a notice."""
    folder = str(payload.get("folder", ""))
    if name == "folder.changed":
        bits = [f"{payload.get(key)} {label}" for key, label in
                (("created", "new"), ("changed", "changed"), ("deleted", "deleted"))
                if payload.get(key)]
        paths = ", ".join(str(p) for p in (payload.get("paths") or [])[:5])
        return f"In {folder}: {', '.join(bits) or 'changes'}." + (f" {paths}" if paths else "")
    if name.startswith("file.") and payload.get("path"):
        return f"{payload['path']} was {name.split('.', 1)[1]} in {folder}."
    return f"Because of “{name}”."


def register_notify_action(actions: ActionRegistry, *,
                           notify: Callable[[str, str], None]) -> None:
    """Add `notify`: a job that puts up a notice, held to `notify.send`."""

    def run(context: JobContext) -> ActionResult:
        decision = context.tools.policy.allows("notify.send")
        if not decision:
            return ActionResult(False, f"Not permitted: {decision.reason}.")
        title = " ".join(str(context.arguments.get("title") or context.job.name).split())
        text = str(context.arguments.get("text") or "").strip()
        if not text:
            return ActionResult(False, "A notice needs something to say.")
        if context.event is not None:
            text = f"{text}\n\n{describe_event(context.event_name or '', context.event)}"
        title = title[:MAX_TITLE_CHARS]
        notify(title, text[:MAX_NOTICE_CHARS])
        context.tools.audit.tool_call(context.tools.actor, NOTIFY_ACTION, {"title": title},
                                      allowed=True, capability="notify.send")
        return ActionResult(True, f"Showed “{title}”.")

    actions.register(NOTIFY_ACTION, run, "Show a notice")
