"""Watching for change: the monitoring agent (C6).

A watch is a folder, a web page, a feed or an inbox the person chose. Every so
often each one is looked at, and what changed since becomes scheduler events
that jobs can wait for:

- a folder: `file.created`, `file.changed` and `file.deleted` for each file,
  and one `folder.changed` for the lot;
- a page: one `page.changed`, with the lines that appeared and how many went;
- a feed: `feed.item` for each new entry, and one `feed.changed` for the lot;
- an inbox: `mail.item` for each new message, and one `mail.changed` for the lot.

A job waiting for one of these can run an agent over what arrived, or put up a
notice with the `notify` action here.

**Held to the permission on every look.** Listing a folder is `files.read`
there, as it is for `list_directory`. Fetching a page or a feed is `net.http`
for its site, through the network chokepoint, as it is for `fetch_page`.
Reading an inbox is `mail.read` for its address, through that account's
sign-in, as it is for `search_mail`. Each is
checked against the global grants at each look, not once when the watch is
made, so revoking one stops the watch at the next look, and the watch says why
instead of failing silently. Watches run in the background like scheduled
jobs, so like them they use the global grants, never the open project's.

**A file is reported once it has settled.** A change is announced only when the
file looks the same on two looks in a row, so a job never wakes to a download or
a save still in progress. A file that never stops changing, such as a log, is
not announced until it does.

**A page is compared as text, line by line.** Scripts, styles and markup go
first, so a new advert or session token is not news. The lines that appeared
are reported, with how many went; the same lines in another order are not a
change. Words to look for narrow it: only lines that mention one count. A page
that shows the time changes on every look and cannot be told from news, and
words are the remedy for that too.

**A feed is known by its entries.** Each entry's id is remembered, and only
entries not seen before are reported, narrowed by words the same way.

**Pages and feeds remember what they saw across a restart; folders do not.** A
page looked at hourly would otherwise miss a change made while Akira was
closed. What was seen is kept in `watch-state/` beside the list of watches, and
forgotten when the watch is removed or its permission is revoked. A folder is
looked at every half-minute, so its first look after a start is a new baseline.

**Addresses in events lose their query strings**, as in the activity log:
that is where a private feed's address carries its key. What a page or a feed
says is material, not instructions, and a job's agent is told so.

**Polling, not OS notifications.** Folders need nothing beyond the standard
library, behave the same on every filesystem, synced folders included, and
cost a directory walk per look. A folder that grows past `MAX_FILES` pauses and
says so, rather than letting one enormous folder turn the walk into a load.
Pages and feeds are looked at hourly unless the person chooses otherwise, and
never more often than every `MIN_WEB_EVERY_S`: a site is someone else's.

**An inbox is known by its messages**, as a feed is by its entries: the last
week of the inbox is read, as often as a page or a feed may be, up to ten
messages a look, and only messages not seen before are reported, narrowed by
words the same way. Looking is reading: nothing is sent, deleted or marked
read. What a message says is material, not instructions, like a page's.
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
from typing import Callable, Protocol

from akira.core.config import config_dir
from akira.core.net import NetError, fetchable, host_of, redact
from akira.core.net import fetch as net_fetch
from akira.core.net.feed import Entry, FeedError, parse_feed
from akira.core.net.page import PageError, page_text
from akira.core.permissions import AuditLog, Policy
from akira.core.schedule import ActionRegistry, ActionResult, JobContext
from akira.security.paths import PathViolation, real

NOTIFY_ACTION = "notify"
POLL_S = 30.0
MAX_FILES = 5_000
MAX_FILE_EVENTS = 50
MAX_WATCHES = 20
MAX_PATTERNS = 10
MAX_WORD_CHARS = 40
MAX_TITLE_CHARS = 80
MAX_NOTICE_CHARS = 600

FOLDER, PAGE, FEED, INBOX = "folder", "page", "feed", "inbox"
KINDS = (FOLDER, PAGE, FEED, INBOX)

_ADDRESS = re.compile(r"\A[^@\s]+@[^@\s]+\.[^@\s]+\Z")
MAX_ADDRESS_CHARS = 254

#: How often a page or a feed is looked at, unless the person says otherwise.
WEB_EVERY_S = 3600
#: Never more often than this.
MIN_WEB_EVERY_S = 900
MAX_WEB_EVERY_S = 7 * 86400
MAX_URL_CHARS = 2000
MAX_WEB_TITLE_CHARS = 200

#: What a page is remembered as, and how much of a change an event carries.
MAX_PAGE_LINES = 2000
MAX_LINE_CHARS = 500
MAX_EVENT_LINES = 10
MAX_EVENT_LINE_CHARS = 300

#: Entries announced from one look at a feed, and feed entries remembered.
MAX_ITEM_EVENTS = 20
MAX_SEEN = 1000

#: Folders never walked: version control, Obsidian's own, caches.
SKIPPED_DIRS = frozenset({".git", ".obsidian", ".trash", "node_modules", "__pycache__"})

#: Files still arriving. A browser renames them when the download finishes.
PARTIAL_SUFFIXES = (".tmp", ".crdownload", ".part", ".partial", ".download")

_ID = re.compile(r"\A[0-9a-f]{16}\Z")

#: Who the activity log records when a watch is paused, or fetches.
ACTOR = "monitor"


class MonitorError(ValueError):
    """Something a watch will not do, with a reason for the person."""


@dataclass
class Watch:
    id: str
    folder: str = ""
    """The folder, for a folder watch."""

    patterns: tuple[str, ...] = ()
    """For a folder, file name patterns such as `*.pdf`; for a page or a feed,
    words to look for. Empty means every change."""

    created: float = 0.0
    paused: str = ""
    """Why it is not being looked at, for the person. Empty while it is."""

    kind: str = FOLDER
    url: str = ""
    """The address, for a page or a feed."""

    every_s: int = 0
    """How often a page, a feed or an inbox is looked at."""

    address: str = ""
    """The mail address, for an inbox."""

    @property
    def target(self) -> str:
        """What is watched, as it is shown and logged: a web address loses its query."""
        if self.kind == FOLDER:
            return self.folder
        return self.address if self.kind == INBOX else redact(self.url)

    @property
    def site(self) -> str:
        """The site a page or a feed is on, which `net.http` is checked against."""
        return host_of(self.url) if self.kind in (PAGE, FEED) else ""

    def wants(self, name: str) -> bool:
        lowered = name.lower()
        return not self.patterns or any(fnmatch.fnmatchcase(lowered, p.lower())
                                        for p in self.patterns)

    def mentions(self, text: str) -> bool:
        """Whether \a text has one of the words to look for, or there are none."""
        lowered = text.lower()
        return not self.patterns or any(word.lower() in lowered for word in self.patterns)

    def to_json(self) -> dict:
        data = {"id": self.id, "kind": self.kind, "patterns": list(self.patterns),
                "created": self.created}
        if self.kind == FOLDER:
            data["folder"] = self.folder
        elif self.kind == INBOX:
            data.update(address=self.address, every=self.every_s)
        else:
            data.update(url=self.url, every=self.every_s)
        return data

    @classmethod
    def from_json(cls, data: dict) -> "Watch":
        kind = str(data.get("kind") or FOLDER)
        if kind not in KINDS or not _ID.match(str(data.get("id", ""))):
            raise ValueError("not a watch")
        patterns = data.get("patterns") or []
        if not isinstance(patterns, list):
            raise ValueError("patterns must be a list")
        created = float(data.get("created") or 0.0)
        if kind == FOLDER:
            if not str(data.get("folder", "")).strip():
                raise ValueError("not a watch")
            return cls(str(data["id"]), str(data["folder"]), _clean_patterns(patterns), created)
        if kind == INBOX:
            return cls(str(data["id"]), "", _clean_patterns(patterns, words=True), created,
                       kind=kind, every_s=_check_every(data.get("every") or WEB_EVERY_S),
                       address=_check_address(str(data.get("address", ""))))
        return cls(str(data["id"]), "", _clean_patterns(patterns, words=True), created,
                   kind=kind, url=_check_url(str(data.get("url", "")), kind),
                   every_s=_check_every(data.get("every") or WEB_EVERY_S))


def _clean_patterns(patterns, *, words: bool = False) -> tuple[str, ...]:
    """File name patterns for a folder, or words to look for on a page or in a feed."""
    cleaned: list[str] = []
    for raw in patterns or ():
        pattern = " ".join(str(raw).split()) if words else str(raw).strip()
        if not pattern:
            continue
        if words and len(pattern) > MAX_WORD_CHARS:
            raise MonitorError(f"“{pattern[:MAX_WORD_CHARS]}…” is too long to look for. Keep "
                               f"each to {MAX_WORD_CHARS} characters.")
        if not words and (len(pattern) > 40 or "/" in pattern or "\\" in pattern):
            raise MonitorError(f"{pattern!r} is not a file name pattern. Use something like *.pdf.")
        if pattern.lower() not in (p.lower() for p in cleaned):
            cleaned.append(pattern)
    if len(cleaned) > MAX_PATTERNS:
        what = "words to look for" if words else "patterns"
        raise MonitorError(f"A watch takes at most {MAX_PATTERNS} {what}.")
    return tuple(cleaned)


def _check_url(url: str, kind: str) -> str:
    text = (url or "").strip()
    if not text:
        raise MonitorError(f"Give the address of the {kind} to watch.")
    if len(text) > MAX_URL_CHARS:
        raise MonitorError("That address is too long to watch.")
    try:
        return fetchable(text)
    except NetError as exc:
        raise MonitorError(str(exc)) from None


def _check_every(seconds) -> int:
    try:
        every = int(seconds)
    except (TypeError, ValueError):
        raise MonitorError("How often to look must be a number of seconds.") from None
    if not MIN_WEB_EVERY_S <= every <= MAX_WEB_EVERY_S:
        raise MonitorError(f"A page, a feed or an inbox is looked at no more often than every "
                           f"{MIN_WEB_EVERY_S // 60} minutes, and at least once a week.")
    return every


def _same_words(these: tuple[str, ...], those: tuple[str, ...]) -> bool:
    """Whether two lists of words look for the same thing. Words match whatever their
    case, so "Invoice" and "invoice" are one watch, not two reporting everything twice."""
    return tuple(w.lower() for w in these) == tuple(w.lower() for w in those)


def _check_address(text: str) -> str:
    address = (text or "").strip().lower()
    if len(address) > MAX_ADDRESS_CHARS or not _ADDRESS.match(address):
        raise MonitorError(f"{text!r} is not a mail address.")
    return address


class Inbox(Protocol):
    """A connected mailbox, as the monitor sees one (`akira.core.connect.inbox`)."""

    def connected(self, address: str) -> bool:
        """Whether \a address is connected for mail."""
        ...

    def recent(self, address: str) -> list:
        """The latest messages in its inbox, newest first, each with `id`, `sender`,
        `subject`, `date` and `snippet`. Raises, with a reason for the person."""
        ...


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
    """`watches.json`, written atomically, read defensively, and beside it
    `watch-state/`, what each page or feed looked like at its last look."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "watches.json"
        self.warnings: list[str] = []

    @property
    def state_dir(self) -> Path:
        return self.path.with_name("watch-state")

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
            self.warnings.append(f"The list of watches was damaged ({exc}). It was moved "
                                 f"aside to {moved.name}; nothing is being watched.")
            return []
        watches = []
        for entry in entries:
            try:
                watches.append(Watch.from_json(entry))
            except (ValueError, TypeError, AttributeError):
                self.warnings.append("A watch could not be read, so it is not being looked at.")
        return watches

    def save(self, watches: list[Watch]) -> None:
        _write_json(self.path, {"version": 2, "watches": [w.to_json() for w in watches]})

    def load_state(self, watch_id: str) -> dict:
        try:
            data = json.loads((self.state_dir / f"{watch_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_state(self, watch_id: str, data: dict) -> None:
        _write_json(self.state_dir / f"{watch_id}.json", data)

    def drop_state(self, watch_id: str) -> None:
        with contextlib.suppress(OSError):
            (self.state_dir / f"{watch_id}.json").unlink()


@dataclass
class _Seen:
    """What a page or a feed looked like at its last look."""

    looked: float = 0.0
    title: str = ""
    lines: list[str] | None = None
    """A page's text, line by line. None until the first look."""

    ids: list[str] | None = None
    """The ids of a feed's entries, newest first. None until the first look."""

    def to_json(self) -> dict:
        return {"looked": self.looked, "title": self.title, "lines": self.lines, "ids": self.ids}

    @classmethod
    def from_json(cls, data: dict) -> "_Seen":
        def strings(value) -> list[str] | None:
            return [str(item) for item in value] if isinstance(value, list) else None

        try:
            looked = float(data.get("looked") or 0.0)
        except (TypeError, ValueError):
            looked = 0.0
        return cls(looked, str(data.get("title") or "")[:MAX_WEB_TITLE_CHARS],
                   strings(data.get("lines")), strings(data.get("ids")))


def _lines(text: str) -> list[str]:
    """A page's text as the lines it is compared by."""
    found: list[str] = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if line:
            found.append(line[:MAX_LINE_CHARS])
            if len(found) >= MAX_PAGE_LINES:
                break
    return found


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


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
                 publish: Callable[[str, dict], None], audit: AuditLog | None = None,
                 fetch: Callable | None = None, inbox: Inbox | None = None,
                 clock: Callable[[], float] | None = None) -> None:
        self._store = store
        self._policy = policy
        self._publish = publish
        self._audit = audit
        # Connected mailboxes, when there is a way to read them.
        self._inbox = inbox
        # The chokepoint, unless a test stands in for it.
        self._fetch = fetch if fetch is not None else net_fetch
        self._clock = clock if clock is not None else time.time
        self._on_change: Callable[[], None] | None = None
        self._lock = threading.RLock()
        self._watches: dict[str, Watch] = {w.id: w for w in store.load()}
        self._seen: dict[str, dict[str, tuple[int, int]]] = {}
        self._settled: dict[str, dict[str, tuple[int, int]]] = {}
        # Pages and feeds pick up where they left off.
        self._web: dict[str, _Seen] = {w.id: _Seen.from_json(store.load_state(w.id))
                                       for w in self._watches.values() if w.kind != FOLDER}
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
            self._store.warnings.append(f"The watches could not be saved: {exc}")

    # -- the watches --------------------------------------------------------------------

    def watches(self) -> list[Watch]:
        with self._lock:
            return sorted(self._watches.values(),
                          key=lambda w: (KINDS.index(w.kind), w.target.lower(), w.patterns))

    def title(self, watch_id: str) -> str:
        """A page's or a feed's own title, as of its last look. "" before one."""
        with self._lock:
            seen = self._web.get(watch_id)
            return seen.title if seen is not None else ""

    def looked(self, watch_id: str) -> float:
        """When a page or a feed was last looked at, in epoch seconds. 0 if never."""
        with self._lock:
            seen = self._web.get(watch_id)
            return seen.looked if seen is not None else 0.0

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
                if (watch.kind == FOLDER and watch.folder.lower() == str(path).lower()
                        and watch.patterns == cleaned):
                    return watch
            if len(self._watches) >= MAX_WATCHES:
                raise MonitorError(f"There are already {MAX_WATCHES} watches. Remove one first.")
            watch = Watch(secrets.token_hex(8), str(path), cleaned, time.time())
            self._watches[watch.id] = watch
            self._save()
        self._changed()
        return watch

    def add_page(self, url: str, words=(), every_s: int = WEB_EVERY_S) -> Watch:
        """Watch a web page for new lines, only lines with one of \a words if
        any are given. Raises `MonitorError` with the reason when it cannot be."""
        return self._add_web(PAGE, url, words, every_s)

    def add_feed(self, url: str, words=(), every_s: int = WEB_EVERY_S) -> Watch:
        """Watch an RSS or Atom feed for new entries, as `add_page` does a page."""
        return self._add_web(FEED, url, words, every_s)

    def _add_web(self, kind: str, url: str, words, every_s: int) -> Watch:
        address = _check_url(url, kind)
        site = host_of(address)
        decision = self._policy().allows("net.http", site)
        if not decision:
            raise MonitorError(f"Not permitted: {decision.reason}. Watching a {kind} fetches it "
                               f"from {site}, so allow fetching pages from {site} first.")
        cleaned = _clean_patterns(words, words=True)
        every = _check_every(every_s)
        with self._lock:
            for watch in self._watches.values():
                if (watch.kind, watch.url) == (kind, address) and _same_words(watch.patterns, cleaned):
                    return watch
            if len(self._watches) >= MAX_WATCHES:
                raise MonitorError(f"There are already {MAX_WATCHES} watches. Remove one first.")
            watch = Watch(secrets.token_hex(8), "", cleaned, time.time(), kind=kind,
                          url=address, every_s=every)
            self._watches[watch.id] = watch
            self._web[watch.id] = _Seen()
            self._save()
        self._changed()
        return watch

    def add_inbox(self, address: str, words=(), every_s: int = WEB_EVERY_S) -> Watch:
        """Watch a connected inbox for new mail, only mail mentioning one of \a words
        if any are given. Raises `MonitorError` with the reason when it cannot be."""
        mailbox = _check_address(address)
        if self._inbox is None:
            raise MonitorError("Inboxes cannot be watched here.")
        if not self._inbox.connected(mailbox):
            raise MonitorError(f"{mailbox} is not connected for mail. Connect it in Settings, "
                               "Accounts, first.")
        decision = self._policy().allows("mail.read", mailbox)
        if not decision:
            raise MonitorError(f"Not permitted: {decision.reason}. Watching an inbox reads its "
                               f"mail, so allow reading {mailbox}'s mail first.")
        cleaned = _clean_patterns(words, words=True)
        every = _check_every(every_s)
        with self._lock:
            for watch in self._watches.values():
                if (watch.kind, watch.address) == (INBOX, mailbox) and _same_words(watch.patterns, cleaned):
                    return watch
            if len(self._watches) >= MAX_WATCHES:
                raise MonitorError(f"There are already {MAX_WATCHES} watches. Remove one first.")
            watch = Watch(secrets.token_hex(8), "", cleaned, time.time(), kind=INBOX,
                          every_s=every, address=mailbox)
            self._watches[watch.id] = watch
            self._web[watch.id] = _Seen()
            self._save()
        self._changed()
        return watch

    def remove(self, watch_id: str) -> bool:
        with self._lock:
            removed = self._watches.pop(watch_id, None) is not None
            self._seen.pop(watch_id, None)
            self._settled.pop(watch_id, None)
            self._web.pop(watch_id, None)
            if removed:
                self._save()
                self._store.drop_state(watch_id)
        if removed:
            self._changed()
        return removed

    # -- looking ----------------------------------------------------------------------------

    def poll(self) -> int:
        """Look at every watch that is due. Returns how many events were published."""
        count = 0
        for watch in self.watches():
            try:
                count += (self._look(watch) if watch.kind == FOLDER
                          else self._look_inbox(watch) if watch.kind == INBOX
                          else self._look_web(watch))
            except OSError as exc:
                self._pause(watch, f"{watch.target} could not be read: {exc}",
                            keep=watch.kind != FOLDER)
        return count

    def _pause(self, watch: Watch, reason: str, *, keep: bool = False) -> None:
        """Say why \a watch is not reporting, until the cause goes away.

        A refusal forgets what was seen, so what changed while the watch could
        not look is not reported afterwards, and it is recorded. A failure, such
        as a site that could not be reached, keeps what was seen (\a keep), and
        the failed fetch is in the activity log already.
        """
        with self._lock:
            if watch.paused == reason:
                return
            watch.paused = reason
            if not keep:
                # Not looking means not knowing: the next look starts afresh
                # rather than reporting everything that changed meanwhile.
                self._seen.pop(watch.id, None)
                self._settled.pop(watch.id, None)
                if watch.kind != FOLDER:
                    self._web[watch.id] = _Seen()
                    self._store.drop_state(watch.id)
        if not keep and self._audit is not None:
            if watch.kind == FOLDER:
                self._audit.tool_call(ACTOR, "watch_folder", {"folder": watch.folder},
                                      allowed=False, capability="files.read", scope=watch.folder,
                                      error=reason)
            elif watch.kind == INBOX:
                self._audit.tool_call(ACTOR, "watch_inbox", {"address": watch.address},
                                      allowed=False, capability="mail.read", scope=watch.address,
                                      error=reason)
            else:
                self._audit.tool_call(ACTOR, f"watch_{watch.kind}", {"url": watch.target},
                                      allowed=False, capability="net.http", scope=watch.site,
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
        self._fired(watch)
        return published + 1

    def _fired(self, watch: Watch) -> None:
        self.last_change[watch.id] = self._clock()
        self._changed()

    # -- pages and feeds ----------------------------------------------------------------------

    def _look_web(self, watch: Watch) -> int:
        with self._lock:
            seen = self._web.setdefault(watch.id, _Seen())
        now = self._clock()
        if seen.looked and 0 <= now - seen.looked < watch.every_s:
            return 0
        decision = self._policy().allows("net.http", watch.site)
        if not decision:
            self._pause(watch, f"Not permitted: {decision.reason}.")
            return 0
        # A failed look waits its turn like any other, so a site that is down is
        # not asked again every half-minute.
        seen.looked = now
        try:
            response = self._fetch(watch.url, policy=self._policy(), audit=self._audit,
                                   actor=ACTOR)
            if not response.ok:
                raise NetError(f"{redact(response.url)} answered {response.status} "
                               f"{response.reason}.")
            if watch.kind == PAGE:
                title, text = page_text(response)
                found: list = _lines(text)
            else:
                feed = parse_feed(response.body)
                title, found = feed.title, list(feed.entries)
        except (NetError, PageError, FeedError) as exc:
            self._keep(watch, seen)
            self._pause(watch, str(exc), keep=True)
            return 0

        with self._lock:
            if self._watches.get(watch.id) is not watch:
                return 0  # removed while the page was on its way
            resumed, watch.paused = bool(watch.paused), ""
        title = " ".join(title.split())[:MAX_WEB_TITLE_CHARS] or seen.title
        if watch.kind == PAGE:
            published = self._compare_page(watch, seen, title, found)
        else:
            published = self._compare_feed(watch, seen, title, found)
        self._keep(watch, seen)
        if resumed and not published:
            self._changed()
        return published

    def _keep(self, watch: Watch, seen: _Seen) -> None:
        try:
            self._store.save_state(watch.id, seen.to_json())
        except OSError as exc:
            note = f"What a watched {watch.kind} looked like could not be saved: {exc}"
            if note not in self._store.warnings:
                self._store.warnings.append(note)

    def _compare_page(self, watch: Watch, seen: _Seen, title: str, lines: list[str]) -> int:
        before = seen.lines
        seen.lines, seen.title = lines, title
        if before is None:
            # The first look is the baseline: what is already there is not news.
            return 0
        old, new = set(before), set(lines)
        added = list(dict.fromkeys(line for line in lines
                                   if line not in old and watch.mentions(line)))
        gone = list(dict.fromkeys(line for line in before
                                  if line not in new and watch.mentions(line)))
        if not (added or gone):
            return 0
        self._publish("page.changed", {
            "watch": watch.id, "url": watch.target, "title": title, "added": len(added),
            "removed": len(gone),
            "lines": [_cut(line, MAX_EVENT_LINE_CHARS) for line in added[:MAX_EVENT_LINES]]})
        self._fired(watch)
        return 1

    def _compare_feed(self, watch: Watch, seen: _Seen, title: str, entries: list[Entry]) -> int:
        before = seen.ids
        seen.ids = list(dict.fromkeys([entry.id for entry in entries] + (before or [])))[:MAX_SEEN]
        seen.title = title
        if before is None:
            return 0
        known = set(before)
        new = list({entry.id: entry for entry in entries
                    if entry.id not in known
                    and watch.mentions(f"{entry.title}\n{entry.summary}")}.values())
        if not new:
            return 0
        for entry in new[:MAX_ITEM_EVENTS]:
            self._publish("feed.item", {
                "watch": watch.id, "url": watch.target, "feed": title, "title": entry.title,
                "link": redact(entry.link) if entry.link else "",
                "published": entry.published, "summary": entry.summary})
        self._publish("feed.changed", {
            "watch": watch.id, "url": watch.target, "feed": title, "new": len(new),
            "titles": [entry.title for entry in new[:MAX_EVENT_LINES]]})
        self._fired(watch)
        return min(len(new), MAX_ITEM_EVENTS) + 1

    # -- inboxes ------------------------------------------------------------------------------

    def _look_inbox(self, watch: Watch) -> int:
        with self._lock:
            seen = self._web.setdefault(watch.id, _Seen())
        now = self._clock()
        if seen.looked and 0 <= now - seen.looked < watch.every_s:
            return 0
        decision = self._policy().allows("mail.read", watch.address)
        if not decision:
            self._pause(watch, f"Not permitted: {decision.reason}.")
            return 0
        if self._inbox is None:
            self._pause(watch, "Inboxes cannot be looked at here.", keep=True)
            return 0
        # A failed look waits its turn like any other.
        seen.looked = now
        try:
            mail = list(self._inbox.recent(watch.address))
        except Exception as exc:  # noqa: BLE001 - a look must not end the watching; its reason is shown
            self._keep(watch, seen)
            self._pause(watch, str(exc) or type(exc).__name__, keep=True)
            return 0
        with self._lock:
            if self._watches.get(watch.id) is not watch:
                return 0  # removed while the mail was on its way
            resumed, watch.paused = bool(watch.paused), ""
        published = self._compare_inbox(watch, seen, mail)
        self._keep(watch, seen)
        if resumed and not published:
            self._changed()
        return published

    def _compare_inbox(self, watch: Watch, seen: _Seen, mail: list) -> int:
        before = seen.ids
        seen.ids = list(dict.fromkeys([str(m.id) for m in mail] + (before or [])))[:MAX_SEEN]
        if before is None:
            # The first look is the baseline: what is already there is not news.
            return 0
        known = set(before)
        new = list({str(m.id): m for m in mail
                    if str(m.id) not in known
                    and watch.mentions(f"{m.sender}\n{m.subject}\n{m.snippet}")}.values())
        if not new:
            return 0
        for message in new[:MAX_ITEM_EVENTS]:
            self._publish("mail.item", {
                "watch": watch.id, "address": watch.address, "from": message.sender,
                "subject": message.subject, "date": message.date, "snippet": message.snippet,
                "id": str(message.id)})
        self._publish("mail.changed", {
            "watch": watch.id, "address": watch.address, "new": len(new),
            "subjects": [message.subject for message in new[:MAX_EVENT_LINES]]})
        self._fired(watch)
        return min(len(new), MAX_ITEM_EVENTS) + 1


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
    if name == "page.changed":
        what = str(payload.get("title") or payload.get("url") or "A watched page")
        bits = [f"{payload.get(key)} {label}" for key, label in
                (("added", "new"), ("removed", "gone")) if payload.get(key)]
        lines = " / ".join(str(line) for line in (payload.get("lines") or [])[:3])
        return f"{what} changed: {', '.join(bits) or 'changes'}." + (f" {lines}" if lines else "")
    if name == "feed.changed":
        what = str(payload.get("feed") or payload.get("url") or "A watched feed")
        titles = "; ".join(str(t) for t in (payload.get("titles") or [])[:5] if t)
        return f"{what}: {payload.get('new') or 'some'} new." + (f" {titles}" if titles else "")
    if name == "feed.item":
        what = str(payload.get("feed") or payload.get("url") or "a watched feed")
        return f"New in {what}: {payload.get('title') or 'an entry with no title'}."
    if name == "mail.changed":
        where = str(payload.get("address") or "a watched inbox")
        subjects = "; ".join(str(s) for s in (payload.get("subjects") or [])[:5] if s)
        return f"{payload.get('new') or 'Some'} new in {where}." + (f" {subjects}" if subjects else "")
    if name == "mail.item":
        return (f"From {payload.get('from') or 'someone'}: "
                f"{payload.get('subject') or '(no subject)'}.")
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
