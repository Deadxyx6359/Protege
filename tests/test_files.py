"""Putting a finished file in place, on Windows as it behaves.

Defender and the search indexer open a file for a moment just after it is
written, and a move onto it in that moment is refused with "Access is denied".
A store that gave up there would lose what it was saving: a connected account,
a review, a grant. So the move is tried again, briefly, and a real refusal is
still raised.
"""

from __future__ import annotations

import os

import pytest

from akira.core import files


def test_a_file_briefly_held_open_is_moved_once_it_is_let_go(tmp_path, monkeypatch):
    source, target = tmp_path / "new.json", tmp_path / "kept.json"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    real, refusals = os.replace, [PermissionError(5, "Access is denied")] * 2

    def held_open(a, b):
        if refusals:
            raise refusals.pop()
        real(a, b)

    monkeypatch.setattr(files.os, "replace", held_open)
    monkeypatch.setattr(files, "PAUSE_S", 0.001)
    files.replace(source, target)
    assert target.read_text(encoding="utf-8") == "new" and not source.exists()


def test_a_file_held_for_good_is_still_refused(tmp_path, monkeypatch):
    tries = []

    def never(a, b):
        tries.append(1)
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(files.os, "replace", never)
    monkeypatch.setattr(files, "PAUSE_S", 0.001)
    with pytest.raises(PermissionError):
        files.replace(tmp_path / "a", tmp_path / "b")
    assert len(tries) == files.ATTEMPTS


def test_anything_but_a_refusal_is_not_retried(tmp_path, monkeypatch):
    tries = []

    def missing(a, b):
        tries.append(1)
        raise FileNotFoundError(2, "No such file")

    monkeypatch.setattr(files.os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        files.replace(tmp_path / "a", tmp_path / "b")
    assert tries == [1]


def test_every_store_moves_its_files_into_place_this_way():
    root = files.__file__.rsplit("core", 1)[0]
    direct = []
    for folder, _, names in os.walk(root):
        for name in names:
            if name.endswith(".py") and name != "files.py":
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as source:
                    if "os.replace(" in source.read():
                        direct.append(os.path.relpath(path, root))
    assert direct == [], f"moved into place without the retry: {direct}"
