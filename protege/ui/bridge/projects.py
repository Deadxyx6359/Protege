"""Projects, and the grants that belong to the open one — the `Projects` bridge.

A grant made here applies only to work started while that project is open. The
permission screen (`Permissions`) holds the grants that apply everywhere. How
the two combine is in `protege.core.projects`.

Every grant and revoke is written to the activity log, naming the project, so
the security review can report it like any other change.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QObject, Signal, Slot

from protege.core.permissions import AuditLog, Policy
from protege.core.projects import ProjectError, ProjectStore
from protege.security.paths import PathViolation, real


def _folder(text: str) -> str:
    folder = (text or "").strip()
    if not folder:
        return ""
    try:
        path = real(folder)
    except (PathViolation, OSError, ValueError) as exc:
        raise ProjectError(f"{folder} cannot be used: {exc}") from None
    if not path.is_dir():
        raise ProjectError(f"{folder} is not a folder.")
    return str(path)


class ProjectsBridge(QObject):
    """Create, open, rename and remove projects, and hold the open one's grants."""

    projectsChanged = Signal()
    currentChanged = Signal()
    grantsChanged = Signal()

    def __init__(self, store: ProjectStore | None = None, audit: AuditLog | None = None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store if store is not None else ProjectStore()
        self._audit = audit if audit is not None else AuditLog()

    @property
    def store(self) -> ProjectStore:
        return self._store

    def effective(self, base: Policy) -> Policy:
        """The global grants plus the open project's. See `ProjectStore.effective`."""
        return self._store.effective(base)

    def _everything_changed(self) -> None:
        self.projectsChanged.emit()
        self.currentChanged.emit()
        self.grantsChanged.emit()

    # -- the projects ------------------------------------------------------------------------

    @Property("QVariantList", notify=projectsChanged)
    def projects(self) -> list:
        """Each project: `id`, `name`, `folder`, `personality`, and `current`."""
        current = self._store.current_id()
        return [{"id": p.id, "name": p.name, "folder": p.folder, "personality": p.personality,
                 "current": p.id == current} for p in self._store.all()]

    @Property(str, notify=currentChanged)
    def currentId(self) -> str:
        return self._store.current_id()

    @Property(str, notify=currentChanged)
    def currentName(self) -> str:
        project = self._store.current()
        return project.name if project is not None else ""

    @Slot(str, str, result=str)
    def create(self, name: str, folder: str = "") -> str:
        """Make a project and open it. Returns "" or why not."""
        try:
            project = self._store.create(name, folder=_folder(folder))
            self._store.set_current(project.id)
        except ProjectError as exc:
            return str(exc)
        self._everything_changed()
        return ""

    @Slot(str, result=str)
    def openProject(self, project_id: str) -> str:
        """Open a project, or leave projects with "". Returns "" or why not."""
        try:
            self._store.set_current(project_id)
        except ProjectError as exc:
            return str(exc)
        self._everything_changed()
        return ""

    def _update(self, project_id: str, **changes) -> str:
        try:
            self._store.update(project_id, **changes)
        except ProjectError as exc:
            return str(exc)
        self.projectsChanged.emit()
        self.currentChanged.emit()
        return ""

    @Slot(str, str, result=str)
    def rename(self, project_id: str, name: str) -> str:
        return self._update(project_id, name=name)

    @Slot(str, str, result=str)
    def setFolder(self, project_id: str, folder: str) -> str:
        """Where the project's notes live. Where to work, not what may be read."""
        try:
            checked = _folder(folder)
        except ProjectError as exc:
            return str(exc)
        return self._update(project_id, folder=checked)

    @Slot(str, str, result=str)
    def setPersonality(self, project_id: str, text: str) -> str:
        return self._update(project_id, personality=text)

    @Slot(str, result=str)
    def remove(self, project_id: str) -> str:
        """Forget a project and its grants. Its notes are left where they are."""
        project = self._store.get(project_id)
        if project is None:
            return "There is no such project."
        held = [grant.capability for grant in self._store.policy(project_id).active()]
        try:
            self._store.remove(project_id)
        except ProjectError as exc:
            return str(exc)
        for capability_id in held:
            self._audit.permission_change(capability_id, granted=False,
                                          note=f"the project {project.name} was removed")
        self._everything_changed()
        return ""

    # -- the open project's grants ------------------------------------------------------------

    @Property("QVariantList", notify=grantsChanged)
    def grants(self) -> list:
        """The open project's own grants: `id`, `scopes`, `expires` (0 = never)."""
        project = self._store.current()
        if project is None:
            return []
        return [{"id": g.capability, "scopes": list(g.scopes), "expires": g.expires or 0}
                for g in self._store.policy(project.id).active()]

    @Slot(str, "QVariantList", result=str)
    def grant(self, capability_id: str, scopes: list) -> str:
        """Grant a capability in the open project only. Returns "" or why not."""
        project = self._store.current()
        if project is None:
            return "Open a project first. Grants for everywhere are on the permission screen."
        policy = self._store.policy(project.id)
        scoped = tuple(str(s) for s in scopes)
        try:
            policy.grant(capability_id, scoped)
        except (KeyError, ValueError) as exc:
            return str(exc) or "that capability cannot be granted like that"
        policy.save()
        self._audit.permission_change(capability_id, granted=True, scopes=scoped,
                                      note=f"in the project {project.name}")
        self.grantsChanged.emit()
        return ""

    @Slot(str, result=str)
    def revoke(self, capability_id: str) -> str:
        project = self._store.current()
        if project is None:
            return "Open a project first."
        policy = self._store.policy(project.id)
        held = policy.granted(capability_id) is not None
        policy.revoke(capability_id)
        policy.save()
        if held:
            self._audit.permission_change(capability_id, granted=False,
                                          note=f"in the project {project.name}")
        self.grantsChanged.emit()
        return ""
