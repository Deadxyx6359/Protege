"""Arguments reaching a skill, and the library running for real.

The gap this covers made the entire skill feature ornamental. Every shipped
skill is documented as `something.py <file>`, but the subprocess runner took
exactly one argument -- the skill path -- and forwarded nothing. A skill could
therefore only ever be run against *itself*: a code reviewer whose only subject
was the code reviewer.

Nothing errored. The output was plausible and described the wrong file, which
is why it survived a suite that only ever imported each skill's source. These
tests execute them.
"""

from __future__ import annotations

import json

from akira import store
from akira.projects import ensure_project, get_project
from akira.security.paths import PathPolicy
from akira.skills.library import LIBRARY
from akira.skills.sandbox import approve, run_skill


def prepared(tmp_path):
    """A tier-2 vault with a project, ready to hold skills."""
    vault = tmp_path / "vault"
    vault.mkdir()
    store.bootstrap_vault(vault)
    ensure_project(vault, "default")
    manifest = store.load_manifest(vault).with_trust_tier(2)
    skills_dir = get_project(vault, "default").skills_dir
    skills_dir.mkdir(parents=True, exist_ok=True)
    return vault, manifest, PathPolicy(vault, 2), skills_dir


def approved_run(tmp_path, source: str, args):
    vault, manifest, policy, skills_dir = prepared(tmp_path)
    target = skills_dir / "probe.py"
    target.write_text(source, encoding="utf-8")
    manifest = approve(manifest, policy, target)
    return run_skill(manifest, policy, target, args=[str(a) for a in args])


ECHO = "import sys\nprint('|'.join(sys.argv[1:]))\n"


def test_arguments_are_handed_to_the_skill(tmp_path):
    run = approved_run(tmp_path, ECHO, ["alpha", "beta"])
    assert run.ok, run.error or run.stderr
    assert run.stdout.strip() == "alpha|beta"


def test_a_skill_still_sees_itself_as_argv_zero(tmp_path):
    run = approved_run(tmp_path, "import sys\nprint(sys.argv[0])\n", [])
    assert run.ok, run.error or run.stderr
    assert run.stdout.strip().endswith("probe.py")


def test_no_arguments_still_works(tmp_path):
    run = approved_run(tmp_path, "import sys\nprint(len(sys.argv))\n", [])
    assert run.ok and run.stdout.strip() == "1"


def test_a_path_with_spaces_survives_as_one_argument(tmp_path):
    target = tmp_path / "a file with spaces.txt"
    target.write_text("hi", encoding="utf-8")
    run = approved_run(
        tmp_path, "import sys\nprint(open(sys.argv[1]).read())\n", [target]
    )
    assert run.ok, run.error or run.stderr
    assert run.stdout.strip() == "hi"


def test_arguments_are_not_a_way_around_approval(tmp_path):
    """Approval covers the code. Arguments must not become a side door."""
    _vault, manifest, policy, skills_dir = prepared(tmp_path)
    target = skills_dir / "probe.py"
    target.write_text("print('ran')\n", encoding="utf-8")

    run = run_skill(manifest, policy, target, args=["x"])
    assert not run.ok
    assert "approved" in (run.error or "")
    assert "ran" not in run.stdout


def test_every_library_skill_runs_against_real_input(tmp_path):
    """The library end to end: installed, approved, and given a real file."""
    _vault, manifest, policy, skills_dir = prepared(tmp_path)

    data = tmp_path / "data"
    data.mkdir()
    (data / "sample.py").write_text("def f(a):\n    return a\n", encoding="utf-8")
    (data / "doc.md").write_text(
        "# T\n\nWords here now.\n\n## S\n\nMore words.\n", encoding="utf-8"
    )
    (data / "t.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (data / "t.json").write_text(json.dumps({"k": [1, 2]}), encoding="utf-8")
    (data / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    (data / "new.txt").write_text("one\n2\n", encoding="utf-8")

    inputs = {
        "code_review": [data / "sample.py"],
        "doc_outline": [data / "doc.md"],
        "text_stats": [data / "doc.md"],
        "data_table": [data / "t.csv"],
        "json_tool": [data / "t.json"],
        "diff_files": [data / "old.txt", data / "new.txt"],
        "project_summary": [data],
    }
    assert set(inputs) == {s.name for s in LIBRARY}, (
        "a library skill has no test input -- add one rather than letting it go "
        "unexercised"
    )

    for skill in LIBRARY:
        target = skills_dir / skill.filename
        target.write_text(skill.source, encoding="utf-8")
        manifest = approve(manifest, policy, target)
        run = run_skill(manifest, policy, target,
                        args=[str(p) for p in inputs[skill.name]])
        assert run.ok, f"{skill.name}: {run.error or run.stderr}"
        assert run.stdout.strip(), f"{skill.name} produced no output"


def test_each_library_skill_documents_a_usage_line():
    """The Skills window reads this to tell the user what to type."""
    import re

    for skill in LIBRARY:
        assert re.match(r"\S+\.py\b", skill.usage), skill.name
