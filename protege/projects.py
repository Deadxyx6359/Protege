"""Projects -- the top-level organizing unit.

Each project owns its notes, memory, skills, and an optional personality
profile override. `project.md` is the durable "what are we doing and why"
layer and is always loaded into context.

Isolation is one-directional and deliberate: global notes are visible from
every project, project notes are visible only from their own. That asymmetry is
enforced in `vault.VaultScan.visible`, not here -- this module only creates and
enumerates directories. Keeping the containment rule in one place means there
is a single function to audit when asking "can project A see project B's
notes".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .schemas import PROJECT_NAME_RE, SchemaError
from .store import write_text

DEFAULT_PROJECT = "default"

PROJECT_TEMPLATE = """---
topics: []
---

# {name}

## Goal

_What are we doing, and why?_

## Decisions

_Choices already made, so they are not relitigated every session._

## Conventions

_How this project does things._
"""


class ProjectError(RuntimeError):
    """A project could not be created or resolved."""


@dataclass(frozen=True)
class Project:
    name: str
    root: Path

    @property
    def doc_path(self) -> Path:
        return self.root / "project.md"

    @property
    def notes_dir(self) -> Path:
        return self.root / "notes"

    @property
    def memory_live_dir(self) -> Path:
        return self.root / "memory" / "live"

    @property
    def memory_pending_dir(self) -> Path:
        return self.root / "memory" / "pending"

    @property
    def memory_holding_dir(self) -> Path:
        """Where transcripts wait before deletion.

        Consolidation is done by an 8B model and will sometimes produce lossy
        or wrong notes. If the transcript is already gone when the user notices,
        the source is unrecoverable -- so it lands here instead of being
        deleted at session end.
        """
        return self.root / "memory" / "holding"

    @property
    def memory_archive_dir(self) -> Path:
        """Transcripts kept on purpose, rather than pending deletion.

        Separate from the holding area because the two mean opposite things.
        Holding is a stay of execution with a timer on it; this is a decision to
        keep, and nothing sweeps it.
        """
        return self.root / "memory" / "archive"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    def read_doc(self) -> str:
        try:
            return self.doc_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # A missing or unreadable project.md is not fatal. It contributes
            # nothing to context and the session continues.
            return ""


def validate_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not PROJECT_NAME_RE.match(cleaned):
        raise SchemaError(
            f"invalid project name {name!r}: use letters, digits, spaces, dots, hyphens or "
            "underscores, starting with a letter or digit, up to 64 characters"
        )
    # Path traversal cannot reach here given the character class, but a name
    # that is only dots would still resolve oddly on Windows.
    if set(cleaned) <= {".", " "}:
        raise SchemaError(f"invalid project name {name!r}")
    return cleaned


def projects_root(vault: Path) -> Path:
    return Path(vault) / "projects"


def list_projects(vault: Path) -> list[Project]:
    root = projects_root(vault)
    if not root.is_dir():
        return []
    found: list[Project] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and PROJECT_NAME_RE.match(child.name):
            found.append(Project(name=child.name, root=child))
    return found


def get_project(vault: Path, name: str) -> Project:
    name = validate_name(name)
    return Project(name=name, root=projects_root(vault) / name)


def ensure_project(vault: Path, name: str = DEFAULT_PROJECT) -> Project:
    """Create a project's directory tree if it does not exist.

    Idempotent, and never overwrites an existing `project.md` -- that file is
    the user's, and a silent reset of it would destroy exactly the durable
    context the project structure exists to preserve.
    """
    project = get_project(vault, name)
    for directory in (
        project.root,
        project.notes_dir,
        project.memory_live_dir,
        project.memory_pending_dir,
        project.memory_holding_dir,
        project.skills_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    if not project.doc_path.exists():
        write_text(project.doc_path, PROJECT_TEMPLATE.format(name=project.name))
    return project


@dataclass(frozen=True)
class ProjectContents:
    """What a project holds, for the delete confirmation.

    Deleting a project removes notes the user wrote and memory the model
    recorded. Naming the counts before the fact is the difference between a
    considered decision and a nasty surprise.
    """

    notes: int = 0
    memory_files: int = 0
    skills: int = 0
    held_transcripts: int = 0

    @property
    def total(self) -> int:
        return self.notes + self.memory_files + self.skills + self.held_transcripts

    def describe(self) -> str:
        if not self.total:
            return "This project is empty."
        bits = []
        if self.notes:
            bits.append(f"{self.notes} note(s)")
        if self.memory_files:
            bits.append(f"{self.memory_files} memory file(s)")
        if self.skills:
            bits.append(f"{self.skills} skill(s)")
        if self.held_transcripts:
            bits.append(f"{self.held_transcripts} held transcript(s)")
        return "Contains " + ", ".join(bits) + "."


def project_contents(project: Project) -> ProjectContents:
    def count(directory: Path, pattern: str = "*") -> int:
        if not directory.is_dir():
            return 0
        return sum(1 for p in directory.rglob(pattern) if p.is_file())

    return ProjectContents(
        notes=count(project.notes_dir, "*.md"),
        memory_files=count(project.root / "memory" / "live", "*.md")
        + count(project.memory_pending_dir, "*.md"),
        skills=count(project.skills_dir, "*.py"),
        held_transcripts=count(project.memory_holding_dir, "*.md"),
    )


def rename_project(vault: Path, old: str, new: str) -> Project:
    """Rename a project directory.

    A plain directory move: nothing outside the tree stores the project name
    except `settings.current_project`, which the caller updates. Refuses to
    overwrite an existing project rather than merging two trees.
    """
    source = get_project(vault, old)
    target = get_project(vault, validate_name(new))
    if not source.root.is_dir():
        raise ProjectError(f"project {old!r} does not exist")
    if target.root.exists():
        raise ProjectError(f"a project named {target.name!r} already exists")
    try:
        source.root.rename(target.root)
    except OSError as exc:
        raise ProjectError(f"could not rename: {exc}") from exc
    return target


def delete_project(vault: Path, name: str) -> None:
    """Delete a project and everything in it. Irreversible.

    Refuses to delete the last remaining project: the application always needs
    somewhere to put the current session, and a vault with zero projects is a
    state the rest of the code does not expect.
    """
    import shutil

    project = get_project(vault, name)
    if not project.root.is_dir():
        raise ProjectError(f"project {name!r} does not exist")
    if len(list_projects(vault)) <= 1:
        raise ProjectError(
            "this is the only project; create another before deleting it"
        )
    try:
        shutil.rmtree(project.root)
    except OSError as exc:
        raise ProjectError(f"could not delete: {exc}") from exc


def slugify(text: str, *, fallback: str = "note") -> str:
    """Filename-safe slug for notes Protege writes."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:60] or fallback
