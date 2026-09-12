"""Projects: what a piece of work owns, including its own permissions.

B6. Supersedes the legacy `akira/projects.py` for the new application; the
legacy module stays while the Tk window still uses it.

A project has a name, the folder its notes live in, an optional personality
override for the assistant, and **its own grants**. That last part is the point:
letting an agent read a folder *for one project* must not let every agent read
it everywhere. A grant made in a project is stored with that project and applies
only to work started while it is open.

**How the layers combine.** While a project is open, work started from the
interface runs under the global grants *and* that project's: anything either
allows is allowed, and a refusal explains itself from whichever layer holds the
capability. The combined view cannot be edited; a grant is always made in one
layer or the other. Scheduled jobs are not affected by which project happens to
be open: they run under the global grants, narrowed as before, so a nightly job
never gains or loses a permission because of what was on screen.

**Nothing here deletes notes.** Removing a project removes Akira's record of it
and its grants. The notes are the person's, in their folder, and stay.

Projects live in the configuration folder, one directory each, named by an id
rather than the project's name, so a name never becomes a path and a rename
moves nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from akira.core.config import config_dir
from akira.core.permissions import Policy
from akira.core.permissions.model import Decision, Grant

MAX_PERSONALITY_CHARS = 4000

_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}\Z")
_ID = re.compile(r"\A[0-9a-f]{16}\Z")


class ProjectError(ValueError):
    """Something a project will not do, with a reason for the person."""


def check_name(name: str) -> str:
    cleaned = " ".join((name or "").split())
    if not _NAME.match(cleaned) or set(cleaned) <= {"."}:
        raise ProjectError("A project name uses letters, digits, spaces, dots, hyphens or "
                           "underscores, starts with a letter or digit, and is at most 64 "
                           "characters.")
    return cleaned


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


@dataclass
class Project:
    id: str
    name: str
    folder: str = ""
    """Where its notes live. Where to work, not what may be read: grants decide that."""

    personality: str = ""
    """Added to the assistant's instructions while the project is open."""

    created: float = 0.0


# -- permissions ----------------------------------------------------------------------------


class ProjectPolicy(Policy):
    """One project's own grants, saved beside it."""

    def __init__(self, file: Path, grants: list[Grant] | None = None) -> None:
        super().__init__(grants)
        self._file = file

    def path(self) -> Path:  # this project's file, not the global one
        return self._file

    @classmethod
    def load(cls) -> "Policy":
        raise TypeError("a project's grants are loaded from its own file: use load_from")

    @classmethod
    def load_from(cls, file: Path) -> "ProjectPolicy":
        """Fails closed, as the global policy does: anything unreadable grants nothing."""
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(file)
        if not isinstance(raw, dict):
            return cls(file)
        grants = [g for g in map(Grant.from_json, raw.get("grants") or [])
                  if g is not None and not g.expired()]
        return cls(file, grants)


class LayeredPolicy(Policy):
    """The global grants and one project's, read together. Read-only."""

    def __init__(self, base: Policy, project: Policy, name: str = "") -> None:
        super().__init__()
        self.base = base
        self.project = project
        self.name = name

    def allows(self, capability_id: str, scope: str | None = None) -> Decision:
        decision = self.base.allows(capability_id, scope)
        if decision:
            return decision
        own = self.project.allows(capability_id, scope)
        if own:
            return own
        # Explain from the layer that holds the capability, when only one does.
        if self.base.granted(capability_id) is None and self.project.granted(capability_id):
            return own
        return decision

    def granted(self, capability_id: str) -> Grant | None:
        held = [g for g in (self.base.granted(capability_id), self.project.granted(capability_id))
                if g is not None]
        if len(held) < 2:
            return held[0] if held else None
        # Both layers hold it. The earlier expiry is kept, so anything reading
        # the combined grant errs towards losing the permission, never keeping it.
        expiries = [g.expires for g in held if g.expires is not None]
        scopes = tuple(dict.fromkeys(s for g in held for s in g.scopes))
        return Grant(capability_id, scopes, min(g.granted for g in held),
                     min(expiries) if expiries else None, "")

    def active(self) -> list[Grant]:
        ids = dict.fromkeys(g.capability for g in (*self.base.active(), *self.project.active()))
        return [g for g in map(self.granted, ids) if g is not None]

    def _read_only(self, *_args, **_kwargs):
        raise RuntimeError("grant or revoke in one layer, the global grants or the project's, "
                           "not in the view of both")

    grant = revoke = revoke_all = save = _read_only


# -- storage ----------------------------------------------------------------------------------


class ProjectStore:
    """The projects, in the configuration folder."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else config_dir() / "projects"
        self._lock = threading.RLock()

    def _dir(self, project_id: str) -> Path:
        if not _ID.match(project_id or ""):
            raise ProjectError("There is no such project.")
        return self.root / project_id

    @staticmethod
    def _read(directory: Path) -> Project | None:
        if not _ID.match(directory.name):
            return None
        try:
            raw = json.loads((directory / "project.json").read_text(encoding="utf-8"))
            name = check_name(str(raw.get("name", "")))
            return Project(directory.name, name, str(raw.get("folder") or ""),
                           str(raw.get("personality") or "")[:MAX_PERSONALITY_CHARS],
                           float(raw.get("created") or 0.0))
        except (OSError, ValueError, AttributeError, TypeError):
            # A damaged record is skipped, not guessed at.
            return None

    def _write(self, project: Project) -> None:
        _write_json(self._dir(project.id) / "project.json",
                    {"name": project.name, "folder": project.folder,
                     "personality": project.personality, "created": project.created})

    def all(self) -> list[Project]:
        with self._lock:
            children = sorted(self.root.iterdir()) if self.root.is_dir() else []
            found = [p for p in map(self._read, children) if p is not None]
        return sorted(found, key=lambda p: (p.name.lower(), p.id))

    def get(self, project_id: str) -> Project | None:
        try:
            directory = self._dir(project_id)
        except ProjectError:
            return None
        with self._lock:
            return self._read(directory)

    def find(self, name: str) -> Project | None:
        wanted = " ".join((name or "").split()).lower()
        return next((p for p in self.all() if p.name.lower() == wanted), None)

    def create(self, name: str, *, folder: str = "", personality: str = "") -> Project:
        name = check_name(name)
        if len(personality) > MAX_PERSONALITY_CHARS:
            raise ProjectError(f"A personality is at most {MAX_PERSONALITY_CHARS} characters.")
        with self._lock:
            if self.find(name) is not None:
                raise ProjectError(f"There is already a project called {name}.")
            project = Project(secrets.token_hex(8), name, folder, personality, time.time())
            self._write(project)
        return project

    def update(self, project_id: str, *, name: str | None = None, folder: str | None = None,
               personality: str | None = None) -> Project:
        with self._lock:
            project = self.get(project_id)
            if project is None:
                raise ProjectError("There is no such project.")
            if name is not None:
                name = check_name(name)
                other = self.find(name)
                if other is not None and other.id != project.id:
                    raise ProjectError(f"There is already a project called {name}.")
                project.name = name
            if folder is not None:
                project.folder = folder
            if personality is not None:
                if len(personality) > MAX_PERSONALITY_CHARS:
                    raise ProjectError(
                        f"A personality is at most {MAX_PERSONALITY_CHARS} characters.")
                project.personality = personality
            self._write(project)
        return project

    def remove(self, project_id: str) -> None:
        """Forget a project and its grants. Its notes are not touched."""
        with self._lock:
            directory = self._dir(project_id)
            if not (directory / "project.json").is_file():
                raise ProjectError("There is no such project.")
            was_open = self.current_id() == project_id
            shutil.rmtree(directory)
            if was_open:
                self.set_current("")

    # -- the open project -------------------------------------------------------------------

    def current_id(self) -> str:
        try:
            raw = json.loads((self.root / "current.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        project_id = str(raw.get("id", "")) if isinstance(raw, dict) else ""
        return project_id if self.get(project_id) is not None else ""

    def current(self) -> Project | None:
        return self.get(self.current_id())

    def set_current(self, project_id: str) -> None:
        """Open a project, or leave projects with ""."""
        if project_id and self.get(project_id) is None:
            raise ProjectError("There is no such project.")
        with self._lock:
            _write_json(self.root / "current.json", {"id": project_id})

    # -- grants ------------------------------------------------------------------------------

    def policy(self, project_id: str) -> ProjectPolicy:
        return ProjectPolicy.load_from(self._dir(project_id) / "permissions.json")

    def policies(self) -> dict[str, Policy]:
        """Every project's own grants, by project name. For the security review."""
        return {project.name: self.policy(project.id) for project in self.all()}

    def effective(self, base: Policy) -> Policy:
        """What work started from the interface runs under right now."""
        project = self.current()
        if project is None:
            return base
        return LayeredPolicy(base, self.policy(project.id), project.name)
