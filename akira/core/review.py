"""The routine security review.

Reads what the permissions and the activity log say, from the outside — it is
not an agent and does not go through the tools it is reviewing. It runs daily
on the scheduler (`ensure_review_job`) and whenever someone asks.

**It only reads.** The grant file, the activity log, the names in the secret
store. It never revokes or edits anything itself: a review that quietly changed
permissions would be one more actor editing them, which is the very thing it
exists to watch. Every finding carries a suggestion and a person acts on it.

What it looks for, and why:

  * **Grants broader than any task needs** — a whole drive, the entire user
    folder, a Windows system folder. Critical when it is write access.
  * **Grants that outlive their use** — held for the whole window and never
    exercised. Nothing is lost by revoking them.
  * **Grants narrower in practice than on paper** — every recent use sat in one
    subfolder of a broad grant, so the grant could be that subfolder.
  * **Long-lived permissions that let data leave the machine.**
  * **Reaching for secrets** — any tool touching SSH keys, browser profiles,
    credential stores, or Akira's own settings folder. The last is always
    critical: that folder holds the permissions themselves.
  * **Refusal bursts** — one agent refused many times in minutes is confused,
    or following instructions it picked up from something it read.
  * **Signs of tampering** — permissions for capabilities that do not exist in
    the grant file, or damage in the middle of the activity log. Akira writes
    neither, and an interrupted write only ever damages the last line.
  * **Credentials nothing owns**, which nobody will think to rotate.
  * **Permission changes in the window**, so a grant nobody remembers making
    gets noticed.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from akira.core import files
from akira.core.config import config_dir
from akira.core.permissions import CATALOGUE, AuditLog, Policy, SecretStore
from akira.core.permissions.audit import Event as AuditEvent
from akira.core.permissions.capabilities import Direction, Risk, ScopeKind, get
from akira.core.schedule import (
    ActionRegistry,
    ActionResult,
    Daily,
    Job,
    JobContext,
    Missed,
    Scheduler,
)

SEVERITIES = ("critical", "warn", "info")
_RANK = {severity: rank for rank, severity in enumerate(SEVERITIES)}

WINDOW_DAYS = 30

#: Refusals from one agent inside this many seconds that count as a burst.
BURST_COUNT = 5
BURST_WINDOW_S = 600

#: Uses needed before suggesting a grant be narrowed. One or two uses are not
#: a pattern, and "narrow it to the one file you opened" is not useful advice.
NARROW_MIN_USES = 3

MAX_STORED_REVIEWS = 10

REVIEW_ACTION = "security_review"

#: Places that hold credentials or identity, as normalised path fragments
#: (lower case, forward slashes). Touching any of these is worth a person's
#: attention whether or not it was allowed.
SENSITIVE_FRAGMENTS = (
    "/.ssh/", "/.gnupg/", "/.aws/", "/.azure/", "/.kube/",
    "/.docker/config.json", "/.git-credentials", "/.netrc", "/_netrc",
    "/appdata/roaming/microsoft/credentials/",
    "/appdata/local/microsoft/credentials/",
    "/appdata/roaming/microsoft/protect/",
    "/google/chrome/user data/", "/microsoft/edge/user data/",
    "/mozilla/firefox/profiles/", "/bravesoftware/brave-browser/user data/",
    "/id_rsa", "/id_ed25519", "/id_ecdsa",
)

#: Argument names that carry a path, checked alongside the recorded scope.
_PATH_KEYS = ("path", "target", "file", "folder", "directory", "cwd")

_BREADTH = {
    "drive": "the whole of a drive",
    "home": "your entire user folder",
    "above-home": "every user's folders on this computer",
    "system": "a Windows system folder",
}

#: Secret-name prefixes, and the component that uses each. Anything stored
#: under a name no component claims is reported as orphaned.
_SECRET_OWNERS: dict[str, str] = {}


def declare_secret_owner(prefix: str, owner: str) -> None:
    """Say that secrets named with \a prefix belong to \a owner."""
    _SECRET_OWNERS[prefix] = owner


def secret_owner(name: str) -> str | None:
    matches = [p for p in _SECRET_OWNERS if name.startswith(p)]
    return _SECRET_OWNERS[max(matches, key=len)] if matches else None


# -- results -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    """`critical`, `warn`, or `info`."""
    code: str
    title: str
    detail: str = ""
    suggestion: str = ""
    capability: str = ""

    def to_json(self) -> dict:
        return {"severity": self.severity, "code": self.code, "title": self.title,
                "detail": self.detail, "suggestion": self.suggestion,
                "capability": self.capability}

    @classmethod
    def from_json(cls, raw: dict) -> "Finding":
        severity = str(raw["severity"])
        if severity not in _RANK:
            raise ValueError(f"unknown severity {severity!r}")
        return cls(severity, str(raw["code"]), str(raw["title"]),
                   str(raw.get("detail", "")), str(raw.get("suggestion", "")),
                   str(raw.get("capability", "")))


@dataclass(slots=True)
class Review:
    at: float
    window_days: int
    findings: list[Finding] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        counts = {severity: 0 for severity in SEVERITIES}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    @property
    def worst(self) -> str:
        return self.findings[0].severity if self.findings else ""

    def summary(self) -> str:
        counts = self.counts
        parts = []
        if counts["critical"]:
            parts.append(f"{counts['critical']} critical")
        if counts["warn"]:
            parts.append(f"{counts['warn']} warning" + ("" if counts["warn"] == 1 else "s"))
        if counts["info"]:
            parts.append(f"{counts['info']} note" + ("" if counts["info"] == 1 else "s"))
        return ", ".join(parts) if parts else "Nothing to report"

    def to_json(self) -> dict:
        return {"at": self.at, "window_days": self.window_days,
                "findings": [f.to_json() for f in self.findings],
                "stats": self.stats}

    @classmethod
    def from_json(cls, raw: dict) -> "Review":
        return cls(float(raw["at"]), int(raw["window_days"]),
                   [Finding.from_json(f) for f in raw.get("findings") or ()],
                   dict(raw.get("stats") or {}))


# -- the review --------------------------------------------------------------


def review(*, policy: Policy, audit: AuditLog,
           secret_store: SecretStore | None = None,
           permissions_file: Path | None = None,
           protected: Path | None = None,
           now: float | None = None,
           window_days: int = WINDOW_DAYS,
           projects: dict[str, Policy] | None = None) -> Review:
    """Look at the current state and return what is worth a person's attention.

    \a projects are each project's own grants, by name. They are checked like
    the global ones: a whole drive granted inside one project is still a whole
    drive.
    """
    now = time.time() if now is None else now
    since = now - window_days * 86400
    events = [e for e in audit.read(limit=100_000) if e.at >= since]

    findings: list[Finding] = []
    findings += _grant_findings(policy)
    for name, own in sorted((projects or {}).items()):
        findings += [Finding(f.severity, f.code, f"In the project {name}: {f.title}",
                             f.detail, f.suggestion, f.capability)
                     for f in _grant_findings(own)]
    findings += _usage_findings(policy, events, since, window_days)
    findings += _file_findings(permissions_file or Policy.path(), now)
    findings += _attempt_findings(events, protected or config_dir())
    findings += _change_findings(events, window_days)
    findings += _secret_findings(secret_store)
    findings += _log_findings(audit.path)
    findings.sort(key=lambda f: (_RANK[f.severity], f.code, f.capability, f.title))

    stats = {
        "grants": len(policy.active()),
        "events": len(events),
        "refusals": sum(1 for e in events if e.kind == "tool" and not e.allowed),
    }
    return Review(now, window_days, findings, stats)


def _norm(path: object) -> str:
    return str(path).replace("\\", "/").lower().rstrip("/") + "/"


def _path_breadth(scope: str) -> str:
    try:
        path = Path(scope).expanduser().resolve()
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return ""
    if path.parent == path:
        return "drive"
    if path == home:
        return "home"
    if home.is_relative_to(path):
        return "above-home"
    for variable in ("WINDIR", "SYSTEMROOT", "PROGRAMFILES",
                     "PROGRAMFILES(X86)", "PROGRAMDATA"):
        root = os.environ.get(variable)
        if not root:
            continue
        with contextlib.suppress(OSError, RuntimeError):
            resolved = Path(root).resolve()
            if path == resolved or path.is_relative_to(resolved):
                return "system"
    return ""


def _grant_findings(policy: Policy) -> list[Finding]:
    findings: list[Finding] = []
    leaving: list[str] = []
    for grant in policy.active():
        capability = get(grant.capability)
        if capability.leaves_machine:
            leaving.append(capability.title)

        if capability.scope is ScopeKind.PATH:
            for scope in grant.scopes:
                breadth = _path_breadth(scope)
                if not breadth:
                    continue
                writes = capability.direction is Direction.WRITE
                findings.append(Finding(
                    "critical" if writes else "warn", "broad-path",
                    f"{capability.title} covers {_BREADTH[breadth]}",
                    f"It was granted for {scope}. "
                    + ("Anything an agent is steered into doing there cannot be "
                       "undone from inside Akira." if writes else
                       "An agent can read anything there, including files you "
                       "would never think to hand it."),
                    "Limit it to the folders the work actually needs.",
                    capability.id))

        if (capability.risk is Risk.HIGH and capability.leaves_machine
                and grant.expires is None):
            findings.append(Finding(
                "warn", "no-expiry", f"{capability.title} never expires",
                "It can send data off this computer and was granted with no end date.",
                "Grant it for a set period, and renew it while you still need it.",
                capability.id))

    if leaving:
        findings.append(Finding(
            "info", "leaves-machine", "Some permissions let data leave this computer",
            ", ".join(sorted(leaving)) + ".",
            "Worth knowing rather than necessarily wrong. Check each is one you meant."))
    return findings


def _used_where(event: AuditEvent) -> str:
    scope = event.detail.get("scope")
    if scope:
        return str(scope)
    arguments = event.detail.get("arguments")
    if isinstance(arguments, dict):
        return str(arguments.get("path") or "")
    return ""


def _common_folder(paths: list[str], root: str) -> str:
    try:
        root_path = Path(root).resolve()
        folders = []
        for text in paths:
            candidate = Path(text).resolve()
            folders.append(candidate if candidate.is_dir() else candidate.parent)
        common = Path(os.path.commonpath([str(f) for f in folders]))
    except (OSError, ValueError, RuntimeError):   # ValueError: different drives
        return ""
    if common == root_path or not common.is_relative_to(root_path):
        return ""
    return str(common)


def _usage_findings(policy: Policy, events: list[AuditEvent], since: float,
                    window_days: int) -> list[Finding]:
    used: dict[str, list[str]] = {}
    for event in events:
        if event.kind != "tool" or not event.allowed:
            continue
        capability = event.detail.get("capability", "")
        if capability:
            used.setdefault(capability, []).append(_used_where(event))

    findings: list[Finding] = []
    for grant in policy.active():
        capability = get(grant.capability)
        uses = used.get(grant.capability, [])

        if not uses and grant.granted < since:
            findings.append(Finding(
                "info", "unused",
                f"{capability.title} has not been used in {window_days} days",
                "Nothing has exercised it in that time.",
                "Revoke it. It costs nothing to grant again when something needs it.",
                capability.id))
            continue

        places = [u for u in uses if u]
        if (capability.scope is ScopeKind.PATH and len(grant.scopes) == 1
                and len(places) >= NARROW_MIN_USES):
            narrower = _common_folder(places, grant.scopes[0])
            if narrower:
                findings.append(Finding(
                    "info", "narrower", f"{capability.title} could be narrower",
                    f"Every use in the last {window_days} days was inside {narrower}, "
                    f"but the permission covers {grant.scopes[0]}.",
                    f"Limit it to {narrower}.", capability.id))
    return findings


def _file_findings(path: Path, now: float) -> list[Finding]:
    unreadable = Finding(
        "warn", "grants-unreadable", "The permission file could not be read",
        "An unreadable file grants nothing, so nothing is exposed — but it also "
        "means the permissions you set are not being applied.",
        "Grant what you need again in Settings; the file will be rewritten.")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return [unreadable]
    entries = raw.get("grants") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return [unreadable]

    unknown: set[str] = set()
    stale = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        capability = entry.get("capability")
        if capability not in CATALOGUE:
            unknown.add(str(capability))
            continue
        expires = entry.get("expires")
        if isinstance(expires, (int, float)) and expires < now:
            stale += 1

    findings: list[Finding] = []
    if unknown:
        findings.append(Finding(
            "warn", "unknown-capability",
            "The permission file lists permissions that do not exist",
            f"{', '.join(sorted(unknown))[:300]}. They grant nothing — Akira "
            "ignores them — but Akira never writes them either, so something "
            "else edited the file.",
            "If you did not edit it yourself, find out what did."))
    if stale:
        findings.append(Finding(
            "info", "expired-entries",
            f"{stale} expired permission{'' if stale == 1 else 's'} still in the file",
            "They grant nothing and are removed the next time permissions are saved.",
            "No action needed."))
    return findings


def _targets(event: AuditEvent) -> list[str]:
    targets = [str(event.detail.get("scope") or "")]
    arguments = event.detail.get("arguments")
    if isinstance(arguments, dict):
        targets += [str(v) for k, v in arguments.items()
                    if k in _PATH_KEYS and isinstance(v, str)]
    return [t for t in targets if t]


def _attempt_findings(events: list[AuditEvent], protected: Path) -> list[Finding]:
    findings: list[Finding] = []
    guarded = _norm(protected)
    seen: set[tuple[str, str, str, str]] = set()

    for event in events:
        if event.kind != "tool":
            continue
        outcome = "allowed" if event.allowed else "refused"
        for target in _targets(event):
            normalised = _norm(target)
            if normalised.startswith(guarded):
                code, severity = "akira-state", "critical"
            elif any(fragment in normalised for fragment in SENSITIVE_FRAGMENTS):
                code = "sensitive-path"
                severity = "critical" if event.allowed else "warn"
            else:
                continue
            key = (code, event.actor, event.action, normalised)
            if key in seen:
                continue
            seen.add(key)
            if code == "akira-state":
                findings.append(Finding(
                    severity, code, "An agent reached for Akira's own settings",
                    f"{event.actor} used {event.action} on {target} ({outcome}). That "
                    "folder holds your permissions and saved credentials, and no task "
                    "has a reason to touch it.",
                    "Look at what the agent was asked to do. If the request came from "
                    "a web page, document or email it had read, treat it as an attempt "
                    "to hijack it."))
            else:
                findings.append(Finding(
                    severity, code, "An agent reached for stored credentials",
                    f"{event.actor} used {event.action} on {target} ({outcome}). "
                    "Keys, browser profiles and credential stores are where accounts "
                    "are taken over from.",
                    "Check the task it was on. If that access was allowed, revoke the "
                    "permission that covered it and consider rotating those credentials."))

    refusals: dict[str, list[float]] = {}
    for event in events:
        if event.kind == "tool" and not event.allowed:
            refusals.setdefault(event.actor, []).append(event.at)
    for actor, times in refusals.items():
        times.sort()
        worst, start = 0, 0
        for end in range(len(times)):
            while times[end] - times[start] > BURST_WINDOW_S:
                start += 1
            worst = max(worst, end - start + 1)
        if worst >= BURST_COUNT:
            findings.append(Finding(
                "warn", "refusal-burst",
                f"{actor} was refused {worst} times within ten minutes",
                "An agent that keeps asking for things it has not been given is either "
                "confused about its task or following instructions it picked up from "
                "something it read.",
                "Check what it was working on. If it had just read a web page, file "
                "or email, that content may be steering it."))
    return findings


def _change_findings(events: list[AuditEvent], window_days: int) -> list[Finding]:
    changes = [e for e in events if e.kind in ("grant", "revoke")]
    if not changes:
        return []
    granted = sorted({e.action for e in changes if e.kind == "grant"})
    revoked = sorted({e.action for e in changes if e.kind == "revoke"})
    parts = []
    if granted:
        parts.append("granted: " + ", ".join(granted))
    if revoked:
        parts.append("revoked: " + ", ".join(revoked))
    count = len(changes)
    return [Finding(
        "info", "permission-changes",
        f"{count} permission change{'' if count == 1 else 's'} in the last {window_days} days",
        "; ".join(parts).capitalize() + ".",
        "Check each was yours. Akira only changes permissions when you do it in Settings.")]


def _secret_findings(secret_store) -> list[Finding]:
    if secret_store is None:
        return []
    try:
        names = secret_store.names()
    except Exception:  # noqa: BLE001 - an unreadable store is not a review failure
        return []
    orphaned = sorted(n for n in names if secret_owner(n) is None)
    if not orphaned:
        return []
    count = len(orphaned)
    return [Finding(
        "warn", "orphaned-secret",
        f"{count} saved credential{'' if count == 1 else 's'} "
        f"belong{'s' if count == 1 else ''} to nothing",
        "Nothing currently in Akira uses: " + ", ".join(orphaned[:10])
        + ". A credential with no owner is one nobody will think to rotate.",
        "Delete any you no longer need.")]


def _log_findings(path: Path) -> list[Finding]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return []
    except OSError:
        return [Finding("warn", "log-unreadable", "The activity log could not be read",
                        "Without it, nothing agents did can be reviewed.",
                        "Check the file is not locked or removed.")]
    damaged = []
    for number, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            if not isinstance(json.loads(line), dict):
                damaged.append(number)
        except ValueError:
            damaged.append(number)
    if not damaged:
        return []
    if damaged == [len(lines) - 1]:
        return [Finding("info", "log-truncated",
                        "The last line of the activity log is incomplete",
                        "Almost always a write interrupted by a crash or power cut.",
                        "No action needed.")]
    count = len(damaged)
    return [Finding(
        "warn", "log-damaged",
        f"{count} line{'' if count == 1 else 's'} inside the activity log "
        f"{'is' if count == 1 else 'are'} damaged",
        "An interrupted write only ever damages the last line. Damage further up "
        "means something other than Akira changed the file.",
        "Keep a copy of the log, and find out what edited it.")]


# -- storage -----------------------------------------------------------------


class ReviewStore:
    """The last few reviews, so the interface can show the latest one."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else config_dir() / "security_review.json"

    @property
    def path(self) -> Path:
        return self._path

    def history(self) -> list[Review]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return [Review.from_json(r) for r in raw["reviews"]]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def latest(self) -> Review | None:
        reviews = self.history()
        return reviews[-1] if reviews else None

    def save(self, result: Review) -> None:
        reviews = (self.history() + [result])[-MAX_STORED_REVIEWS:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=".review-", suffix=".json", dir=self._path.parent)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump({"reviews": [r.to_json() for r in reviews]}, stream, indent=1)
            files.replace(temporary, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise


# -- on the schedule -----------------------------------------------------------


def register_review_action(actions: ActionRegistry, *,
                           policy: Callable[[], Policy], audit: AuditLog,
                           secret_store: SecretStore | None = None,
                           store: ReviewStore | None = None,
                           on_review: Callable[[Review], None] | None = None,
                           projects: Callable[[], dict[str, Policy]] | None = None) -> None:
    """Make the review something a job can run.

    It reads the *live* policy directly rather than through the job's tools:
    it is system code inspecting Akira's own state, not an agent acting.
    \a projects returns each project's own grants, which are reviewed too.
    """
    reviews = store if store is not None else ReviewStore()

    def run(context: JobContext) -> ActionResult:
        result = review(policy=policy(), audit=audit, secret_store=secret_store,
                        projects=projects() if projects is not None else None)
        reviews.save(result)
        audit.record(AuditEvent(result.at, "audit", "security-review", "review",
                                True, {"counts": result.counts}))
        if on_review is not None:
            on_review(result)
        return ActionResult(True, result.summary())

    actions.register(REVIEW_ACTION, run, "Review permissions and recent activity")


def ensure_review_job(scheduler: Scheduler, *, hour: int = 9, minute: int = 0) -> Job:
    """The daily review job, created once. Runs late if the machine was off."""
    existing = scheduler.find(REVIEW_ACTION)
    if existing:
        return existing[0]
    return scheduler.add("Security review", REVIEW_ACTION, Daily(hour, minute),
                         missed=Missed.RUN_LATE)
