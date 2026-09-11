"""The tag map and the link graph (B6): nested tags as hubs, tags used together
linked, links resolved as Obsidian resolves them, a layout that holds still, and
nothing counted that may not be read.
"""

from __future__ import annotations

import pytest

from protege.core.brain import Vault
from protege.core.brain import graph as graph_module
from protege.core.brain.graph import layout, link_graph, tag_map


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    vault = tmp_path / "Vault"
    (vault / ".obsidian").mkdir(parents=True)
    write(vault, "Tomatoes.md", "Stake them. #garden/tomatoes #cooking\n")
    write(vault, "Basil.md", "Beside the tomatoes. #garden/basil #garden\n")
    write(vault, "Sauce.md", "#cooking/sauce from [[Tomatoes]], see [[Pesto]].\n")
    write(vault, "Trips/Kyoto.md", "#travel/japan, and [[Sauce]] on the way.\n")
    write(vault, "Private/Diary.md", "#secret notes, and [[Tomatoes]].\n")
    return vault


def readable(root):
    return Vault(root, history_dir=root.parent / "history",
                 may_read=lambda path: "Private" not in path.parts)


def edges(graph, kind):
    return {(e.a, e.b) for e in graph.edges if e.kind == kind}


# -- the tag map ------------------------------------------------------------------------------


def test_nested_tags_become_hubs_and_branches(root):
    graph = tag_map(readable(root))
    assert {n.id for n in graph.hubs} == {"garden", "cooking", "travel"}
    assert edges(graph, "branch") == {("garden", "garden/tomatoes"), ("garden", "garden/basil"),
                                      ("cooking", "cooking/sauce"), ("travel", "travel/japan")}
    assert graph.nodes["garden/tomatoes"].label == "tomatoes"


def test_tags_used_together_are_linked_once_and_never_over_a_branch(root):
    graph = tag_map(readable(root))
    # Tomatoes.md carries both; Basil.md's pair is already a branch.
    assert edges(graph, "cotag") == {("cooking", "garden/tomatoes")}


def test_a_hub_nobody_tagged_is_drawn_but_not_a_tag(root):
    graph = tag_map(readable(root))
    assert graph.nodes["garden"].real and graph.nodes["cooking"].real
    assert not graph.nodes["travel"].real
    # garden, cooking and the four nested tags; travel is only a hub.
    assert graph.summary() == "6 tags in 3 groups."


def test_only_notes_that_may_be_read_count(root):
    graph = tag_map(readable(root))
    assert "secret" not in graph.nodes
    assert "Private/Diary.md" not in link_graph(readable(root)).nodes


def test_a_folder_limits_the_map(root):
    graph = tag_map(readable(root), folder=Vault(root).root / "Trips")
    assert set(graph.nodes) == {"travel", "travel/japan"}


def test_the_busiest_tags_are_kept_when_there_are_too_many(root, monkeypatch):
    write(root, "More tomatoes.md", "Again. #garden/tomatoes\n")
    monkeypatch.setattr(graph_module, "MAX_NODES", 2)
    graph = tag_map(readable(root))
    # Six tags, two kept: the one on two notes, then the first of the rest by name.
    assert {"garden/tomatoes", "cooking"} <= set(graph.nodes)
    assert graph.hidden == 4 and "left out" in graph.summary()


def test_the_layout_holds_still_and_stays_on_the_canvas(root):
    first = layout(tag_map(readable(root)), 800, 600)
    second = layout(tag_map(readable(root)), 800, 600)
    assert first.to_json() == second.to_json()
    for node in first.nodes.values():
        assert 0 < node.x < 800 and 0 < node.y < 600 and node.radius > 0
    assert len({(round(n.x), round(n.y)) for n in first.nodes.values()}) == len(first.nodes), \
        "two nodes were placed on the same spot"


def test_an_empty_vault_says_how_to_start(tmp_path):
    empty = tmp_path / "Empty"
    (empty / ".obsidian").mkdir(parents=True)
    graph = layout(tag_map(Vault(empty)), 800, 600)
    assert not graph.nodes and "#subject" in graph.summary()


# -- the link graph ---------------------------------------------------------------------------


def test_links_resolve_as_obsidian_does_and_unwritten_notes_are_counted(root):
    graph = link_graph(readable(root))
    assert edges(graph, "link") == {("Sauce.md", "Tomatoes.md"), ("Trips/Kyoto.md", "Sauce.md")}
    assert graph.unresolved == 1, "the link to Pesto, which does not exist, was not counted"
    assert graph.nodes["Sauce.md"].weight == 2
    assert graph.summary() == "4 notes, 2 links, 1 to notes not written yet."
