"""Canvas, the school's course site, as a connected account (C5): reading courses and coursework.

The person makes an access token in Canvas (Account, Settings, New access
token), gives it an expiry date, and gives it to Akira with their school's
Canvas address. The token is sealed with DPAPI (`canvas.<hash>.token`) and never
shown to a model. `canvas.json` keeps the site and the person's name there, and
nothing secret.

A Canvas token can do anything the person can: Canvas gives students no token
that only reads. So Akira holds itself to reading, and says so. Every request is
a GET, held to `lms.read` for that Canvas site, sent to that site and nowhere
else, and never followed to another address. Nothing here can submit, post or
change anything; that would be `lms.write`, and it is not in this module.

Connecting asks Canvas who the token belongs to before anything is kept, so a
token Canvas refuses is never sealed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from akira.core.config import config_dir
from akira.core.net import NetError, call, host_of, with_query
from akira.core.net.page import readable
from akira.core.permissions import AuditLog, SecretStore
from akira.core.permissions.secrets import SecretError
from akira.core.review import declare_secret_owner

from .google import ConnectError
from akira.core import files

#: What reading Canvas needs, for the site.
CAPABILITY = "lms.read"

#: Who connects and disconnects: always the person, never an agent.
ACTOR = "person"

#: The most items one request asks Canvas for.
PAGE = 100

#: The most courses whose assignments are looked through.
MAX_COURSES = 20

#: The longest look ahead for assignments.
MAX_DAYS = 60

#: The most of an assignment's description that is kept.
MAX_DESCRIPTION = 20_000

#: Where Canvas says to make a token, for the person.
TOKEN_HELP = ("In Canvas, open Account, then Settings, then New access token. Give it a purpose "
              "and an expiry date, and paste the token here.")

#: Canvas ids are numbers. Checked rather than escaped, so an id can never become
#: part of another address.
_ID = re.compile(r"[0-9]{1,20}")

#: What a token looks like: no spaces, not absurdly long.
_TOKEN = re.compile(r"[A-Za-z0-9~._-]{20,200}")

declare_secret_owner("canvas.", "Canvas")


@dataclass(frozen=True)
class CanvasAccount:
    site: str
    name: str
    """The person's name as Canvas has it, so they can see which account it is."""
    connected: float = 0.0


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    code: str
    score: str
    """The current score Canvas shows the person, such as "91.5", or ""."""
    grade: str
    """The current letter grade, when the course gives one, or ""."""


@dataclass(frozen=True)
class Assignment:
    id: str
    course_id: str
    course: str
    name: str
    due: str
    """As Canvas gives it: a date and time in UTC, or "" for none."""
    points: str
    submitted: bool
    missing: bool
    late: bool
    score: str
    url: str


@dataclass(frozen=True)
class AssignmentText:
    assignment: Assignment
    text: str
    truncated: bool


def site_of(text: str) -> str:
    """A Canvas site, from its address or its name. Raises `ConnectError` if it is not one."""
    value = str(text).strip()
    if value.lower().startswith("http://"):
        raise ConnectError("Canvas is reached over https only.")
    host = host_of(value if "://" in value else f"https://{value}")
    try:
        ipaddress.ip_address(host)
        is_address = True
    except ValueError:
        is_address = False
    if not host or "." not in host or is_address:
        raise ConnectError(f"{text!r} is not a Canvas site. Give its address, such as "
                           "school.instructure.com.")
    return host


def token_name(site: str) -> str:
    """Where a site's token is sealed. The site itself is not in the name."""
    return f"canvas.{hashlib.sha256(site.encode('utf-8')).hexdigest()[:16]}.token"


def ident(text: str, what: str) -> str:
    """\a text as a Canvas id. Raises `ConnectError` if it is not one."""
    value = str(text).strip()
    if not _ID.fullmatch(value):
        raise ConnectError(f"{value!r} is not {what} id. list_assignments gives them.")
    return value


class CanvasStore:
    """Which Canvas sites are connected. Holds nothing secret."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "canvas.json"
        self._lock = threading.Lock()

    def all(self) -> list[CanvasAccount]:
        with self._lock:
            return self._read()

    def _read(self) -> list[CanvasAccount]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        found = []
        for entry in raw.get("canvas", []) if isinstance(raw, dict) else []:
            if isinstance(entry, dict) and entry.get("site"):
                found.append(CanvasAccount(str(entry["site"]), str(entry.get("name", "")),
                                           float(entry.get("connected", 0.0))))
        return found

    def _write(self, accounts: list[CanvasAccount]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(prefix=".canvas-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"canvas": [asdict(a) for a in accounts]}, stream, indent=1)
            files.replace(temporary, self.path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def get(self, site: str) -> CanvasAccount | None:
        return next((a for a in self.all() if a.site == site), None)

    def save(self, account: CanvasAccount) -> None:
        with self._lock:
            kept = [a for a in self._read() if a.site != account.site]
            self._write(kept + [account])

    def remove(self, site: str) -> bool:
        with self._lock:
            accounts = self._read()
            kept = [a for a in accounts if a.site != site]
            if len(kept) == len(accounts):
                return False
            self._write(kept)
            return True

    def only(self) -> str:
        """The one connected site, or "" when there is none or a choice."""
        having = self.all()
        return having[0].site if len(having) == 1 else ""


class Canvas:
    """Connected Canvas sites: connecting one, reading from it, and forgetting it."""

    def __init__(self, *, vault: SecretStore, store: CanvasStore | None = None) -> None:
        self._vault = vault
        self._store = store if store is not None else CanvasStore()

    def accounts(self) -> list[CanvasAccount]:
        return self._store.all()

    def account(self, site: str) -> CanvasAccount | None:
        return self._store.get(site)

    def only(self) -> str:
        return self._store.only()

    # -- connecting --------------------------------------------------------------------------

    def connect(self, site: str, token: str, *, policy, audit: AuditLog | None,
                actor: str = ACTOR) -> CanvasAccount:
        """Ask Canvas whose \a token it is, and keep it only if Canvas accepts it."""
        where = site_of(site)
        token = str(token).strip()
        if not _TOKEN.fullmatch(token):
            raise ConnectError(f"That does not look like a Canvas access token. {TOKEN_HELP}")
        who = self._answer(where, "users/self", {}, lambda: token, policy=policy, audit=audit,
                           actor=actor, refused=f"Canvas at {where} did not accept that token. "
                                                f"{TOKEN_HELP}")
        if not isinstance(who, dict) or not who.get("id"):
            raise ConnectError(f"{where} did not answer the way Canvas does. Check the address.")
        self._vault.put(token_name(where), token)
        account = CanvasAccount(where, str(who.get("name") or who.get("short_name") or ""),
                                time.time())
        self._store.save(account)
        return account

    def disconnect(self, site: str) -> str:
        """Forget a site's token here. Returns what the person should also do in Canvas."""
        where = site_of(site)
        try:
            self._vault.delete(token_name(where))
        except SecretError:
            pass
        self._store.remove(where)
        return (f"Akira has forgotten the token for {where}. Delete it in Canvas as well, under "
                "Account, Settings, Approved integrations, so it stops working everywhere.")

    # -- reading -----------------------------------------------------------------------------

    def get(self, site: str, path: str, params: dict[str, str], *, policy, audit: AuditLog | None,
            actor: str):
        """Read \a path from \a site's API, as the person. Raises `ConnectError`."""
        where = site_of(site)
        if self._store.get(where) is None:
            raise ConnectError(f"{where} is not connected. Connect it in Settings, Accounts.")

        def token() -> str:
            try:
                return self._vault.get(token_name(where))
            except SecretError as exc:
                raise ConnectError(f"The token for {where} could not be read ({exc}). Connect "
                                   "it again.") from None

        return self._answer(where, path, params, token, policy=policy, audit=audit, actor=actor,
                            refused=f"Canvas at {where} no longer accepts its token: it may have "
                                    "expired or been deleted. Make a new one and connect again.")

    def _answer(self, site: str, path: str, params: dict[str, str], token, *, policy,
                audit: AuditLog | None, actor: str, refused: str):
        url = f"https://{site}/api/v1/{path}"
        if params:
            url = with_query(url, params)
        try:
            response = call("GET", url, policy=policy, capability=CAPABILITY, scope=site,
                            hosts=(site,), audit=audit, actor=actor, bearer=token)
        except NetError as exc:
            raise ConnectError(str(exc)) from None
        if response.status == 401:
            raise ConnectError(refused)
        try:
            data = json.loads(response.text() or "null")
        except ValueError:
            raise ConnectError(f"{site} answered with something that is not Canvas's.") from None
        if not response.ok:
            said = data.get("errors") if isinstance(data, dict) else None
            detail = (said[0].get("message") if isinstance(said, list) and said
                      and isinstance(said[0], dict) else response.reason)
            raise ConnectError(f"Canvas at {site} refused: {detail}.")
        return data


def _text(value) -> str:
    return "" if value is None else str(value)


def courses(canvas: Canvas, site: str, *, policy, audit, actor: str) -> list[Course]:
    """The person's active courses, with the score Canvas shows them in each."""
    data = canvas.get(site, "courses", {"enrollment_state": "active", "include[]": "total_scores",
                                        "per_page": str(PAGE)},
                      policy=policy, audit=audit, actor=actor)
    found = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict) or not item.get("id") or item.get("access_restricted_by_date"):
            continue
        mine = next((e for e in item.get("enrollments") or []
                     if isinstance(e, dict) and e.get("type") == "student"), {})
        found.append(Course(_text(item["id"]), _text(item.get("name")) or "(untitled course)",
                            _text(item.get("course_code")),
                            _text(mine.get("computed_current_score")),
                            _text(mine.get("computed_current_grade"))))
    return found


def _assignment(item: dict, course: Course) -> Assignment:
    handed = item.get("submission") if isinstance(item.get("submission"), dict) else {}
    state = _text(handed.get("workflow_state"))
    return Assignment(_text(item.get("id")), course.id, course.name,
                      _text(item.get("name")) or "(untitled)", _text(item.get("due_at")),
                      _text(item.get("points_possible")),
                      state in ("submitted", "graded", "pending_review") or bool(
                          handed.get("submitted_at")),
                      bool(handed.get("missing")), bool(handed.get("late")),
                      _text(handed.get("score")), _text(item.get("html_url")))


def assignments(canvas: Canvas, site: str, *, days: int, now: float, policy, audit,
                actor: str) -> tuple[list[Assignment], list[Course]]:
    """What is due in the next \a days, and what is overdue, across active courses, soonest first.

    Returns the assignments and the courses looked through.
    """
    days = max(1, min(int(days), MAX_DAYS))
    horizon = now + days * 86_400
    taking = courses(canvas, site, policy=policy, audit=audit, actor=actor)[:MAX_COURSES]
    found: dict[str, Assignment] = {}
    for course in taking:
        for bucket in ("overdue", "future"):
            data = canvas.get(site, f"courses/{ident(course.id, 'a course')}/assignments",
                              {"bucket": bucket, "include[]": "submission",
                               "order_by": "due_at", "per_page": str(PAGE)},
                              policy=policy, audit=audit, actor=actor)
            for item in data if isinstance(data, list) else []:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                made = _assignment(item, course)
                if bucket == "future" and made.due and _epoch(made.due) > horizon:
                    continue
                found[f"{course.id}/{made.id}"] = made
    ordered = sorted(found.values(), key=lambda a: (_epoch(a.due) if a.due else float("inf")))
    return ordered, taking


def _epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


def assignment(canvas: Canvas, site: str, course_id: str, assignment_id: str, *, policy, audit,
               actor: str) -> AssignmentText:
    """One assignment, and what it asks, as text."""
    course = ident(course_id, "a course")
    item = canvas.get(site, f"courses/{course}/assignments/{ident(assignment_id, 'an assignment')}",
                      {"include[]": "submission"}, policy=policy, audit=audit, actor=actor)
    if not isinstance(item, dict):
        raise ConnectError("Canvas did not give that assignment.")
    made = _assignment(item, Course(course, _text(item.get("course_name")), "", "", ""))
    description = _text(item.get("description"))
    text = readable(description)[1] if "<" in description else description.strip()
    return AssignmentText(made, text[:MAX_DESCRIPTION], len(text) > MAX_DESCRIPTION)
