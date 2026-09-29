"""The library: documents added from the window, and folders read where they are.

There was no way to give Akira a document from the window: documents were
whatever was in a folder allowed on the permission screen, found by knowing to
go there. The library is where they go now.

  * **Files** are copied into a folder of Akira's own, one for each project and
    one for the person's own work outside any, so a datasheet added in one
    project is not read in another. Adding them is the person's own act, so
    reading that folder is allowed as they add them.
  * **Folders** stay where they are and are read in place: a library such as
    ST's STM32Cube package holds thousands of files, and a copy of it would be
    out of date the day it was made. Adding one allows reading it, and removing
    it takes away what adding it allowed.

The chat searches the library of the open project and the person's own, and
checks an answer's library names against the headers in it
(`akira.core.brain.grounding`).
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from akira.core import files
from akira.core.config import config_dir
from akira.security.paths import PathViolation, is_within, real, reject_dangerous

from . import KINDS

#: What may be added as a file: documents, text, and source a library ships.
ADDABLE = frozenset(set(KINDS) | {".md", ".txt", ".h", ".hpp", ".c", ".cpp", ".ino"})

#: The largest file added. A chip's reference manual runs to tens of megabytes.
MAX_FILE_BYTES = 150_000_000

#: The folder of the person's own work, outside any project.
PERSONAL = "personal"

_PROJECT_ID = re.compile(r"\A[A-Za-z0-9_-]{1,64}\Z")
_REFERENCES = "references.json"


@dataclass(frozen=True)
class Entry:
    name: str
    path: str
    kind: str
    """`file`, copied into the library, or `folder`, read where it is."""
    size: int = 0
    personal: bool = False
    """In the person's own library rather than the open project's."""


class Library:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else config_dir() / "library"

    # -- where -----------------------------------------------------------------------------

    def folder(self, project: str = "") -> Path:
        """The folder files added for \a project are copied into; "" is the person's own."""
        name = project if project and _PROJECT_ID.match(project) else PERSONAL
        return self.root / name

    def folders(self, project: str = "") -> list[Path]:
        """Every folder the library of \a project reads, and the person's own, that exists."""
        out: list[Path] = []
        for owner in dict.fromkeys((project, "")):
            own = self.folder(owner)
            if own.is_dir():
                out.append(own)
            out += [Path(r["folder"]) for r in self._references().get(self._key(owner), [])
                    if Path(r["folder"]).is_dir()]
        return list(dict.fromkeys(out))

    def entries(self, project: str = "") -> list[Entry]:
        """What is in the library: the open project's, then the person's own."""
        out: list[Entry] = []
        for owner in dict.fromkeys((project, "")):
            personal = not owner or owner != project
            own = self.folder(owner)
            if own.is_dir():
                for path in sorted(own.iterdir(), key=lambda p: p.name.lower()):
                    if path.is_file():
                        out.append(Entry(path.name, str(path), "file", path.stat().st_size,
                                         personal=personal and bool(project)))
            for held in self._references().get(self._key(owner), []):
                folder = Path(held["folder"])
                out.append(Entry(folder.name or str(folder), str(folder), "folder",
                                 personal=personal and bool(project)))
        return out

    # -- adding and removing -----------------------------------------------------------------

    def add_files(self, project: str, paths: list[Path]) -> tuple[list[Path], list[str]]:
        """Copy \a paths into \a project's library: what was added, and why each other was not."""
        target = self.folder(project)
        added: list[Path] = []
        problems: list[str] = []
        for source in paths:
            why = _addable(source)
            if why:
                problems.append(why)
                continue
            target.mkdir(parents=True, exist_ok=True)
            destination = _free_name(target, source.name)
            try:
                shutil.copy2(source, destination)
            except OSError as exc:
                problems.append(f"{source.name} could not be copied: {exc}")
                continue
            added.append(destination)
        return added, problems

    def add_folder(self, project: str, folder: Path, granted: list[str]) -> str:
        """Read \a folder where it is, for \a project; \a granted is what adding it allowed."""
        try:
            reject_dangerous(folder)
            folder = real(folder)
        except (PathViolation, OSError, ValueError):
            return "That is not a folder that can be added."
        if not folder.is_dir():
            return "That is not a folder."
        if folder.parent == folder:
            return "A whole drive cannot be added. Choose the folder inside it that you need."
        if is_within(real(self.root), folder) or is_within(folder, real(self.root)):
            return "That folder is Akira's own library."
        held = self._references()
        key = self._key(project)
        if any(Path(r["folder"]) == folder for r in held.get(key, [])):
            return ""
        held.setdefault(key, []).append({"folder": str(folder), "granted": list(granted)})
        self._save(held)
        return ""

    def remove(self, project: str, path: str) -> tuple[str, list[str]]:
        """Take \a path out of \a project's library, or the person's own: "" or why not, and
        what adding a folder had allowed, to be taken back."""
        target = Path(path)
        held = self._references()
        for owner in dict.fromkeys((project, "")):
            key = self._key(owner)
            for reference in held.get(key, []):
                if Path(reference["folder"]) == target:
                    held[key] = [r for r in held[key] if r is not reference]
                    self._save(held)
                    return "", list(reference.get("granted", []))
            own = self.folder(owner)
            try:
                inside = target.is_file() and is_within(real(own), real(target))
            except (OSError, ValueError):
                inside = False
            if inside:
                try:
                    target.unlink()
                except OSError as exc:
                    return f"{target.name} could not be removed: {exc}", []
                return "", []
        return "That is not in the library.", []

    # -- the list of folders read in place ------------------------------------------------------

    def _key(self, project: str) -> str:
        return project if project and _PROJECT_ID.match(project) else PERSONAL

    def _references(self) -> dict[str, list[dict]]:
        try:
            raw = json.loads((self.root / _REFERENCES).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(k): [r for r in v if isinstance(r, dict) and isinstance(r.get("folder"), str)]
                for k, v in raw.items() if isinstance(v, list)}

    def _save(self, held: dict[str, list[dict]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.root / (_REFERENCES + ".tmp")
        temporary.write_text(json.dumps(held, indent=1), encoding="utf-8")
        files.replace(temporary, self.root / _REFERENCES)


def _addable(source: Path) -> str:
    """Why \a source cannot be added, or ""."""
    try:
        reject_dangerous(source)
        if source.is_symlink():
            return f"{source.name} is a link: add the file it points to."
        if not source.is_file():
            return f"{source.name} is not a file."
        size = source.stat().st_size
    except (PathViolation, OSError, ValueError):
        return f"{source.name} cannot be read."
    if source.suffix.lower() not in ADDABLE:
        return (f"{source.name} is not a kind of file Akira reads: add PDFs, Word, Excel or "
                "PowerPoint files, text or Markdown, or C headers and source.")
    if size > MAX_FILE_BYTES:
        return f"{source.name} is over {MAX_FILE_BYTES // 1_000_000} MB."
    return ""


def _free_name(folder: Path, name: str) -> Path:
    """\a name in \a folder, or "name (2)" if that is taken: nothing added replaces anything."""
    candidate = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    count = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({count}){suffix}"
        count += 1
    return candidate
