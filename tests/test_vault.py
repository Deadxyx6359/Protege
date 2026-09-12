"""Vault reading and note visibility.

Visibility is the whole of Layer 3's security value, so these tests are written
adversarially: each one asks "what is the cheapest way to get a locked note in
front of the model", and asserts it does not work.
"""

from __future__ import annotations

import pytest

from akira.schemas import Manifest
from akira.vault import (
    NoteScope,
    classify,
    coerce_topic,
    extract_topics,
    parse_frontmatter,
    read_note,
    render_note,
    scan_vault,
)


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "projects" / "demo" / "notes").mkdir(parents=True)
    (root / "projects" / "demo" / "memory" / "live").mkdir(parents=True)
    (root / "projects" / "demo" / "memory" / "pending").mkdir(parents=True)
    (root / "global" / "notes").mkdir(parents=True)
    (root / ".protege").mkdir()
    (root / ".obsidian").mkdir()
    return root


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def note_with(topics, body="Some content about the subject."):
    joined = ", ".join(topics)
    return f"---\ntopics: [{joined}]\n---\n\n{body}\n"


# --- frontmatter parsing ---------------------------------------------------


def test_parses_topics_list():
    fm, body, err = parse_frontmatter("---\ntopics: [a_b, c_d]\n---\n\nbody\n")
    assert not err
    assert fm["topics"] == ["a_b", "c_d"]
    assert body.strip() == "body"


def test_parses_block_style_topics():
    fm, _, err = parse_frontmatter("---\ntopics:\n  - physics\n  - chemistry\n---\nbody")
    assert not err
    assert extract_topics(fm)[0] == ("chemistry", "physics")


def test_document_without_frontmatter_has_no_topics():
    fm, body, err = parse_frontmatter("just a note\n")
    assert fm == {} and not err
    assert body == "just a note\n"


def test_malformed_yaml_reports_an_error():
    _, _, err = parse_frontmatter("---\ntopics: [unclosed\n---\n\nbody\n")
    assert "malformed YAML" in err


def test_non_mapping_frontmatter_reports_an_error():
    _, _, err = parse_frontmatter("---\n- just\n- a\n- list\n---\n\nbody\n")
    assert "must be a mapping" in err


def test_frontmatter_uses_safe_load_only():
    # A note is user-authored data. Full yaml.load would let a crafted note
    # construct arbitrary Python objects on scan.
    text = "---\ntopics: !!python/object/apply:os.system ['echo pwned']\n---\nbody"
    fm, _, err = parse_frontmatter(text)
    assert err, "unsafe YAML tags must fail to parse rather than execute"
    assert fm == {}


# --- topic coercion --------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("python_basics", "python_basics"),
        ("Python-Basics", "python_basics"),
        ("#python basics", "python_basics"),
        ("python/basics", "python_basics"),
        ("  PHYSICS  ", "physics"),
        ("a__b", "a_b"),
    ],
)
def test_tags_are_coerced_leniently(raw, expected):
    # Leniency here is safety, not convenience: a tag that fails to match makes
    # the note look untagged, and untagged means invisible -- so strictness
    # would silently hide notes the user believed were tagged.
    assert coerce_topic(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "###", "123", "?!?", None, True, [], {}])
def test_uncoercible_tags_return_none(raw):
    assert coerce_topic(raw) is None


def test_one_bad_tag_invalidates_the_whole_note():
    # Dropping the bad tag and keeping the good ones would let
    # `topics: [python_basics, "???"]` resolve to a fully-unlocked note.
    topics, err = extract_topics({"topics": ["python_basics", "???"]})
    assert topics == ()
    assert "unusable topic tag" in err


def test_obsidian_tags_key_is_accepted():
    topics, err = extract_topics({"tags": ["physics"]})
    assert topics == ("physics",) and not err


def test_topics_key_wins_over_tags():
    topics, _ = extract_topics({"topics": ["physics"], "tags": ["chemistry"]})
    assert topics == ("physics",)


# --- classification --------------------------------------------------------


@pytest.mark.parametrize(
    "rel,scope,project",
    [
        ("global/notes/a.md", NoteScope.GLOBAL, ""),
        ("projects/demo/notes/a.md", NoteScope.PROJECT, "demo"),
        ("projects/demo/project.md", NoteScope.PROJECT_DOC, "demo"),
        ("projects/demo/memory/live/s1.md", NoteScope.MEMORY_LIVE, "demo"),
        ("projects/demo/memory/pending/s1.md", NoteScope.MEMORY_PENDING, "demo"),
        ("Welcome.md", NoteScope.LOOSE, ""),
        ("Inbox/idea.md", NoteScope.LOOSE, ""),
    ],
)
def test_classification(rel, scope, project):
    assert classify(rel) == (scope, project)


def test_only_some_scopes_are_retrievable():
    assert NoteScope.GLOBAL.retrievable
    assert NoteScope.PROJECT.retrievable
    assert NoteScope.LOOSE.retrievable
    # Injected directly at their own budget priority; retrieving them too would
    # double-count them.
    assert not NoteScope.PROJECT_DOC.retrievable
    assert not NoteScope.MEMORY_LIVE.retrievable
    # Consolidation output the user has not confirmed yet. Retrieving it would
    # let unreviewed model-written notes influence answers before review.
    assert not NoteScope.MEMORY_PENDING.retrievable


# --- scanning --------------------------------------------------------------


def test_scan_skips_control_and_editor_directories(vault):
    write(vault / ".protege" / "manifest.json", "{}")
    write(vault / ".protege" / "notes.md", note_with(["physics"]))
    write(vault / ".obsidian" / "workspace.md", note_with(["physics"]))
    write(vault / "global" / "notes" / "real.md", note_with(["physics"]))
    scan = scan_vault(vault)
    paths = [n.rel_path for n in scan.notes]
    assert paths == ["global/notes/real.md"]


def test_scan_reads_topics_and_body(vault):
    write(vault / "global" / "notes" / "a.md", note_with(["physics", "optics"], "Light bends."))
    note = scan_vault(vault).notes[0]
    assert note.topics == ("optics", "physics")
    assert "Light bends." in note.body
    assert note.ok


def test_unreadable_note_becomes_a_problem_not_a_crash(vault):
    path = vault / "global" / "notes" / "bad.md"
    write(path, "---\ntopics: [oops\n---\nbody")
    scan = scan_vault(vault)
    assert len(scan.problems) == 1
    assert not scan.problems[0].ok


# --- visibility: the three fail-closed rules -------------------------------


def _manifest(*unlocked):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    return manifest


def test_untagged_note_is_invisible(vault):
    # Rule 1. If untagged meant visible, the lock would be opt-in: write about a
    # locked subject, omit the frontmatter, done.
    write(vault / "global" / "notes" / "untagged.md", "Uranium enrichment works like this.\n")
    scan = scan_vault(vault)
    assert scan.visible(_manifest("physics")) == []
    assert len(scan.untagged()) == 1


def test_note_is_visible_only_when_every_topic_is_unlocked(vault):
    # Rule 2. "Any topic unlocked" would deliver cryptography content through
    # the python_basics door.
    write(vault / "global" / "notes" / "mixed.md", note_with(["python_basics", "cryptography"]))
    scan = scan_vault(vault)
    assert scan.visible(_manifest("python_basics")) == []
    assert len(scan.visible(_manifest("python_basics", "cryptography"))) == 1


def test_unparseable_note_is_invisible(vault):
    # Rule 3. Unknown topics are treated as locked.
    write(vault / "global" / "notes" / "broken.md", "---\ntopics: [unclosed\n---\nSecret content")
    scan = scan_vault(vault)
    assert scan.visible(_manifest("physics")) == []


def test_note_with_bad_tag_is_invisible_even_if_other_tags_unlock(vault):
    write(vault / "global" / "notes" / "sneaky.md", "---\ntopics: [physics, \"!!!\"]\n---\nSecret")
    scan = scan_vault(vault)
    assert scan.visible(_manifest("physics")) == []


def test_visible_note_appears_when_unlocked(vault):
    write(vault / "global" / "notes" / "ok.md", note_with(["physics"]))
    scan = scan_vault(vault)
    assert len(scan.visible(_manifest("physics"))) == 1


def test_relocking_hides_the_note_again(vault):
    write(vault / "global" / "notes" / "ok.md", note_with(["physics"]))
    scan = scan_vault(vault)
    manifest = _manifest("physics")
    assert len(scan.visible(manifest)) == 1
    assert scan.visible(manifest.with_relocked("physics")) == []


def test_memory_notes_are_scoped_like_any_other_note(vault):
    # The brief calls this out specifically: if MAIN wrote locked content into
    # the vault, retrieval would hand it back and the gate would be bypassed by
    # the model's own notes.
    write(
        vault / "projects" / "demo" / "notes" / "remembered.md",
        note_with(["chemistry"], "The synthesis route is..."),
    )
    scan = scan_vault(vault)
    assert scan.visible(_manifest("physics"), project="demo") == []
    assert len(scan.visible(_manifest("chemistry"), project="demo")) == 1


# --- project isolation -----------------------------------------------------


def test_project_notes_are_invisible_from_another_project(vault):
    write(vault / "projects" / "demo" / "notes" / "a.md", note_with(["physics"]))
    scan = scan_vault(vault)
    assert len(scan.visible(_manifest("physics"), project="demo")) == 1
    assert scan.visible(_manifest("physics"), project="other") == []


def test_global_notes_are_visible_from_every_project(vault):
    write(vault / "global" / "notes" / "g.md", note_with(["physics"]))
    scan = scan_vault(vault)
    assert len(scan.visible(_manifest("physics"), project="demo")) == 1
    assert len(scan.visible(_manifest("physics"), project="other")) == 1


# --- reporting -------------------------------------------------------------


def test_hidden_count_covers_locked_untagged_and_broken(vault):
    write(vault / "global" / "notes" / "locked.md", note_with(["chemistry"]))
    write(vault / "global" / "notes" / "untagged.md", "no frontmatter")
    write(vault / "global" / "notes" / "broken.md", "---\ntopics: [x\n---\nbody")
    write(vault / "global" / "notes" / "ok.md", note_with(["physics"]))
    scan = scan_vault(vault)
    assert scan.hidden_count(_manifest("physics")) == 3


def test_all_topics_lists_what_the_vault_mentions(vault):
    write(vault / "global" / "notes" / "a.md", note_with(["physics"]))
    write(vault / "global" / "notes" / "b.md", note_with(["chemistry", "physics"]))
    assert scan_vault(vault).all_topics() == ("chemistry", "physics")


# --- writing ---------------------------------------------------------------


def test_render_note_roundtrips(tmp_path):
    text = render_note(["physics", "optics"], "Body text here.")
    path = tmp_path / "n.md"
    path.write_text(text, encoding="utf-8")
    note = read_note(path, tmp_path)
    assert note.topics == ("optics", "physics")
    assert note.body.strip() == "Body text here."


def test_render_note_always_emits_a_topics_key():
    # An explicit empty list stays invisible to retrieval. Omitting the key
    # looks like an oversight and invites someone to "fix" it by making
    # untagged notes visible.
    assert "topics:" in render_note([], "body")


def test_render_note_carries_extra_frontmatter(tmp_path):
    text = render_note(["physics"], "b", extra={"source": "pinned", "session": "abc"})
    path = tmp_path / "n.md"
    path.write_text(text, encoding="utf-8")
    note = read_note(path, tmp_path)
    assert note.frontmatter["source"] == "pinned"
    assert note.frontmatter["session"] == "abc"
