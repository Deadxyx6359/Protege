"""The document tools (B1): what an agent can read, create and change, and how
the gate and the files behave around it.

The formats are tested in test_office_formats.py; these test the tools — the
permission each needs, the confirmation, and what happens at the edges: an
existing file, a locked file, a file in the old format, text that is not there.
"""

from __future__ import annotations

import json

import pytest

from protege.core.documents import Package, sheets, slides, word
from protege.core.permissions import AuditLog, Policy, SecretStore
from protege.core.tools import ToolContext, default_registry
from protege.core.tools.builtin import office

from test_office_formats import DECK_PARTS, WORD_PARTS, package_bytes, tiny_pdf


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path / "cfg"))


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "report.docx").write_bytes(package_bytes(WORD_PARTS))
    (root / "roadmap.pptx").write_bytes(package_bytes(DECK_PARTS))
    (root / "budget.xlsx").write_bytes(sheets.create(
        [("Budget", [["Item", "Cost"], ["Paper", 12.5], ["Ink", 30]])], title="Budget"))
    (root / "paper.pdf").write_bytes(tiny_pdf())
    return root


def ctx(tmp_path, *grants, confirm=None):
    policy = Policy()
    for capability, scope in grants:
        policy.grant(capability, (str(scope),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), actor="tester",
                       confirm=confirm or (lambda summary: False))


def reading(tmp_path, folder):
    return ctx(tmp_path, ("docs.read", folder))


def writing(tmp_path, folder):
    return ctx(tmp_path, ("docs.read", folder), ("docs.write", folder),
               confirm=lambda summary: True)


def call(name, arguments, context):
    return default_registry().invoke(name, arguments, context)


# -- what is offered -------------------------------------------------------------------


def test_documents_need_their_own_permission_not_file_access(folder):
    """Reading a folder's files and reading its documents are separate grants."""
    only_files = Policy()
    only_files.grant("files.read", (str(folder),))
    names = {t.name for t in default_registry().available(only_files)}
    assert "read_document" not in names

    documents = Policy()
    documents.grant("docs.read", (str(folder),))
    names = {t.name for t in default_registry().available(documents)}
    assert "read_document" in names
    assert not {"create_document", "edit_document", "update_spreadsheet"} & names


def test_the_research_gatherer_can_read_documents():
    from protege.core.agents.roles import ANALYST, GATHERER

    assert "read_document" in GATHERER.tools and "read_document" in ANALYST.tools


# -- read_document -----------------------------------------------------------------------


@pytest.mark.parametrize("name, expected", [
    ("report.docx", "# Quarterly report"),
    ("roadmap.pptx", "## Slide 1 — Roadmap"),
    ("budget.xlsx", "| 2 | Paper | 12.5 |"),
    ("paper.pdf", "# Big Heading"),
])
def test_every_kind_of_document_reads_as_text(tmp_path, folder, name, expected):
    result = call("read_document", {"path": str(folder / name)}, reading(tmp_path, folder))
    assert result.ok and expected in result.content


def test_reading_outside_the_granted_folder_is_refused(tmp_path, folder):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "secret.docx").write_bytes(package_bytes(WORD_PARTS))
    result = call("read_document", {"path": str(other / "secret.docx")},
                  reading(tmp_path, folder))
    assert "Not permitted" in result.content


def test_an_old_format_file_gets_advice_not_an_error(tmp_path, folder):
    (folder / "old.doc").write_bytes(b"\xd0\xcf\x11\xe0 old")
    result = call("read_document", {"path": str(folder / "old.doc")}, reading(tmp_path, folder))
    assert not result.ok and "save it as .docx" in result.content


def test_a_long_document_is_cut_rather_than_flooding_the_context(tmp_path, folder, monkeypatch):
    monkeypatch.setattr(office, "MAX_READ_CHARS", 50)
    result = call("read_document", {"path": str(folder / "report.docx")}, reading(tmp_path, folder))
    assert result.ok and "cut at 50 characters" in result.content


# -- create_document ------------------------------------------------------------------------


def test_a_word_document_is_created_and_reads_back(tmp_path, folder):
    target = folder / "plan.docx"
    result = call("create_document",
                  {"path": str(target), "content": "# Plan\n\n- Build it\n- Ship it\n"},
                  writing(tmp_path, folder))
    assert result.ok
    assert word.render(word.read(Package(target.read_bytes()))) == "# Plan\n\n- Build it\n- Ship it"


def test_a_workbook_is_created_and_reads_back(tmp_path, folder):
    target = folder / "costs.xlsx"
    result = call("create_document",
                  {"path": str(target), "content": "| Item | Cost |\n| Paper | 4 |\n"},
                  writing(tmp_path, folder))
    assert result.ok
    assert sheets.read(Package(target.read_bytes()))[0].rows == [["Item", "Cost"], ["Paper", "4"]]


def test_creating_never_overwrites(tmp_path, folder):
    before = (folder / "report.docx").read_bytes()
    result = call("create_document", {"path": str(folder / "report.docx"), "content": "# New"},
                  writing(tmp_path, folder))
    assert not result.ok and "edit_document" in result.content
    assert (folder / "report.docx").read_bytes() == before


def test_a_deck_cannot_be_made_from_nothing_yet_and_says_why(tmp_path, folder):
    result = call("create_document", {"path": str(folder / "talk.pptx"), "content": "# Hi"},
                  writing(tmp_path, folder))
    assert not result.ok and "PowerPoint" in result.content
    assert not (folder / "talk.pptx").exists()


def test_creating_asks_first(tmp_path, folder):
    asked = []
    context = ctx(tmp_path, ("docs.write", folder),
                  confirm=lambda summary: asked.append(summary) or False)
    result = call("create_document", {"path": str(folder / "plan.docx"), "content": "# Plan"}, context)
    assert not result.ok and asked and "plan.docx" in asked[0]
    assert not (folder / "plan.docx").exists()


# -- edit_document ----------------------------------------------------------------------------


def test_a_word_edit_changes_the_text_and_keeps_the_rest(tmp_path, folder):
    target = folder / "report.docx"
    result = call("edit_document", {"path": str(target), "find": "12 percent",
                                    "replace": "15 percent"}, writing(tmp_path, folder))
    assert result.ok and "1 occurrence" in result.content
    assert word.read(Package(target.read_bytes()))[1].text == "Revenue grew by 15 percent."


def test_a_deck_edit_reaches_the_speaker_notes(tmp_path, folder):
    target = folder / "roadmap.pptx"
    result = call("edit_document", {"path": str(target), "find": "beta", "replace": "release"},
                  writing(tmp_path, folder))
    assert result.ok and "2 occurrences" in result.content
    assert slides.read(Package(target.read_bytes()))[0].notes == "Speak slowly about the release"


def test_text_that_is_not_there_changes_nothing(tmp_path, folder):
    target = folder / "report.docx"
    before = target.read_bytes()
    result = call("edit_document", {"path": str(target), "find": "Twelve percent", "replace": "x"},
                  writing(tmp_path, folder))
    assert not result.ok and "nothing was changed" in result.content
    assert target.read_bytes() == before


def test_a_spreadsheet_is_pointed_at_the_right_tool(tmp_path, folder):
    result = call("edit_document", {"path": str(folder / "budget.xlsx"), "find": "Ink",
                                    "replace": "Toner"}, writing(tmp_path, folder))
    assert not result.ok and "update_spreadsheet" in result.content


def test_a_file_locked_by_word_is_explained(tmp_path, folder, monkeypatch):
    def locked(path, data):
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(office, "write_atomically", locked)
    result = call("edit_document", {"path": str(folder / "report.docx"), "find": "Risks",
                                    "replace": "Threats"}, writing(tmp_path, folder))
    assert not result.ok and "open in another program" in result.content


# -- update_spreadsheet ---------------------------------------------------------------------------


def test_cells_are_set_from_a_json_object(tmp_path, folder):
    target = folder / "budget.xlsx"
    cells = json.dumps({"B3": 32, "C1": "Paid", "C3": "=B3*2"})
    result = call("update_spreadsheet", {"path": str(target), "sheet": "Budget", "cells": cells},
                  writing(tmp_path, folder))
    assert result.ok and "B3" in result.content
    rows = sheets.read(Package(target.read_bytes()))[0].rows
    assert rows[0] == ["Item", "Cost", "Paid"] and rows[2][1] == "32"


@pytest.mark.parametrize("cells, expected", [
    ("{not json", "JSON object"),
    ("[1, 2]", "JSON object"),
    ('{"B2": [1, 2]}', "one value"),
    ('{"B0": 1}', "not a cell reference"),
])
def test_bad_cells_are_refused_and_the_file_is_untouched(tmp_path, folder, cells, expected):
    target = folder / "budget.xlsx"
    before = target.read_bytes()
    result = call("update_spreadsheet", {"path": str(target), "sheet": "Budget", "cells": cells},
                  writing(tmp_path, folder))
    assert not result.ok and expected in result.content
    assert target.read_bytes() == before


def test_an_unknown_sheet_names_the_real_ones(tmp_path, folder):
    result = call("update_spreadsheet", {"path": str(folder / "budget.xlsx"), "sheet": "Summary",
                                         "cells": '{"A1": 1}'}, writing(tmp_path, folder))
    assert not result.ok and "Budget" in result.content


def test_the_confirmation_names_the_cells(tmp_path, folder):
    asked = []
    context = ctx(tmp_path, ("docs.write", folder),
                  confirm=lambda summary: asked.append(summary) or False)
    call("update_spreadsheet", {"path": str(folder / "budget.xlsx"), "sheet": "Budget",
                                "cells": '{"B3": 99}'}, context)
    assert asked and "B3" in asked[0] and "99" in asked[0]
