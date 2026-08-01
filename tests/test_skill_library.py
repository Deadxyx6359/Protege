"""Every shipped skill must parse, run, and produce the right answer.

These are handed to the user as trustworthy tools, so "it looked fine" is not
enough -- each one is executed against real input in a subprocess and its
output checked. A broken shipped skill is worse than no skill: it burns the
credibility of the whole library.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from protege.skills.author import check_syntax, scan_imports
from protege.skills.library import LIBRARY, by_name


def run(skill_name: str, tmp_path: Path, *args: str) -> tuple[int, str, str]:
    skill = by_name(skill_name)
    assert skill is not None
    path = tmp_path / skill.filename
    path.write_text(skill.source, encoding="utf-8")
    done = subprocess.run(
        [sys.executable, "-I", str(path), *args],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )
    return done.returncode, done.stdout, done.stderr


# --- the whole library obeys the authoring rules -----------------------------


@pytest.mark.parametrize("skill", LIBRARY, ids=lambda s: s.name)
def test_parses(skill):
    assert check_syntax(skill.source) == ""


@pytest.mark.parametrize("skill", LIBRARY, ids=lambda s: s.name)
def test_uses_no_forbidden_imports(skill):
    """Same rule the authoring path enforces on model-written skills: no
    network, no subprocess, no ctypes. Shipped code does not get an exemption."""
    assert scan_imports(skill.source) == ()


@pytest.mark.parametrize("skill", LIBRARY, ids=lambda s: s.name)
def test_has_a_docstring_and_usage(skill):
    assert skill.source.lstrip().startswith('"""')
    assert "usage:" in skill.source
    assert skill.summary and skill.usage and skill.topic


def test_names_are_unique():
    names = [s.name for s in LIBRARY]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("skill", LIBRARY, ids=lambda s: s.name)
def test_exits_cleanly_with_no_arguments(skill, tmp_path):
    """Run with no args it should print usage and exit non-zero, not traceback."""
    code, out, err = run(skill.name, tmp_path)
    assert code != 0
    assert "Traceback" not in err
    assert "usage:" in out.lower()


# --- each skill produces the right answer ------------------------------------


def test_code_review_finds_real_defects(tmp_path):
    (tmp_path / "sample.py").write_text(
        "def f(items=[]):\n"
        "    try:\n"
        "        pass\n"
        "    except:\n"
        "        pass\n"
        "    if items == None:\n"
        "        pass\n"
        "    return items\n",
        encoding="utf-8",
    )
    code, out, _ = run("code_review", tmp_path, "sample.py")
    assert code == 0
    assert "mutable default" in out
    assert "bare except" in out
    assert "compare to None" in out


def test_code_review_is_quiet_on_clean_code(tmp_path):
    (tmp_path / "clean.py").write_text(
        '"""Module."""\n\n\ndef add(a, b):\n    """Add two numbers."""\n    return a + b\n',
        encoding="utf-8",
    )
    code, out, _ = run("code_review", tmp_path, "clean.py")
    assert code == 0
    assert "No findings." in out


def test_code_review_reports_a_syntax_error_without_crashing(tmp_path):
    (tmp_path / "broken.py").write_text("def oops(:\n    pass\n", encoding="utf-8")
    code, out, err = run("code_review", tmp_path, "broken.py")
    assert "does not parse" in out
    assert "Traceback" not in err


def test_doc_outline_builds_the_heading_tree(tmp_path):
    (tmp_path / "doc.md").write_text(
        "# Title\n\nsome words here\n\n## Section A\n\nmore words in section a\n\n"
        "```\n# not a heading, this is code\n```\n\n## Section B\n\nfinal words\n",
        encoding="utf-8",
    )
    code, out, _ = run("doc_outline", tmp_path, "doc.md")
    assert code == 0
    assert "# Title" in out
    assert "## Section A" in out
    assert "## Section B" in out
    # A heading inside a fenced code block is not a heading.
    assert "not a heading" not in out
    assert "minute(s) to read" in out


def test_text_stats_finds_repetition_and_long_sentences(tmp_path):
    long_sentence = " ".join(["voltage"] * 40) + "."
    (tmp_path / "t.txt").write_text(f"Short one. {long_sentence}", encoding="utf-8")
    code, out, _ = run("text_stats", tmp_path, "t.txt")
    assert code == 0
    assert "voltage" in out
    assert "over 30 words" in out


def test_data_table_renders_csv(tmp_path):
    (tmp_path / "d.csv").write_text("name,qty\nwidget,3\ngadget,12\n", encoding="utf-8")
    code, out, _ = run("data_table", tmp_path, "d.csv")
    assert code == 0
    assert "| name" in out and "| qty" in out
    assert "widget" in out and "12" in out
    assert out.count("|--") or "|---" in out


def test_data_table_renders_json(tmp_path):
    (tmp_path / "d.json").write_text(
        json.dumps([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]), encoding="utf-8"
    )
    code, out, _ = run("data_table", tmp_path, "d.json")
    assert code == 0
    assert "| a" in out and "| b" in out


def test_data_table_truncates(tmp_path):
    rows = "\n".join(f"r{i},{i}" for i in range(100))
    (tmp_path / "d.csv").write_text(f"name,n\n{rows}\n", encoding="utf-8")
    code, out, _ = run("data_table", tmp_path, "d.csv", "5")
    assert code == 0
    assert "more row(s) not shown" in out


def test_json_tool_accepts_valid_json(tmp_path):
    (tmp_path / "v.json").write_text('{"b": 2, "a": [1, 2, 3]}', encoding="utf-8")
    code, out, _ = run("json_tool", tmp_path, "v.json")
    assert code == 0
    assert "valid JSON" in out
    assert "object (2 keys)" in out


def test_json_tool_pinpoints_a_parse_error(tmp_path):
    (tmp_path / "bad.json").write_text('{\n  "a": 1,\n  "b" 2\n}', encoding="utf-8")
    code, out, err = run("json_tool", tmp_path, "bad.json")
    assert code == 1
    assert "INVALID at line 3" in out
    assert "Traceback" not in err


def test_diff_files_reports_changes(tmp_path):
    (tmp_path / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("one\nTWO\nthree\n", encoding="utf-8")
    code, out, _ = run("diff_files", tmp_path, "a.txt", "b.txt")
    assert code == 0
    assert "-two" in out and "+TWO" in out
    assert "1 line(s) added, 1 removed" in out


def test_diff_files_detects_identical(tmp_path):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("same\n", encoding="utf-8")
    code, out, _ = run("diff_files", tmp_path, "a.txt", "b.txt")
    assert code == 0
    assert "identical" in out


def test_project_summary_counts_and_finds_markers(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("x = 1\n# TODO: finish this\n", encoding="utf-8")
    (src / "b.md").write_text("# doc\n\ntext\n", encoding="utf-8")
    skip = src / "__pycache__"
    skip.mkdir()
    (skip / "junk.py").write_text("noise\n", encoding="utf-8")

    code, out, _ = run("project_summary", tmp_path, str(src))
    assert code == 0
    assert "unfinished marker" in out
    assert "TODO: finish this" in out
    # __pycache__ must not be counted.
    assert "junk" not in out


# --- installation -------------------------------------------------------------


def test_install_writes_an_unapproved_header(tmp_path, tk_available):
    """Shipping a tool and blessing a tool are separate acts."""
    import tkinter as tk

    try:
        root = tk.Tk()
    except tk.TclError:
        if tk_available:
            # Tk works in this process, so this is a real defect.
            raise
        pytest.skip("Tk is unavailable in this environment")
    from protege.ui import theme
    from protege.ui.skill_library_dialog import SkillLibraryDialog

    theme.install(root)
    root.withdraw()
    try:
        skills_dir = tmp_path / "skills"
        dialog = SkillLibraryDialog(root, skills_dir)
        dialog.update_idletasks()
        dialog._install_all()

        written = sorted(p.name for p in skills_dir.glob("*.py"))
        assert written == sorted(s.filename for s in LIBRARY)
        for path in skills_dir.glob("*.py"):
            assert "NOT approved for execution" in path.read_text(encoding="utf-8")
        dialog.destroy()
    finally:
        root.destroy()

