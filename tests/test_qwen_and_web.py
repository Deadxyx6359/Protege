"""Think-block filtering, the knowledge graph, the sidebar, and the icon.

The think filter carries the most weight here. Qwen3 emits reasoning between
<think> tags, and a leaked reasoning trace does not merely look untidy: the
auditor's grammar is two lines, so a preamble around `VERDICT: PASS` parses as
"unexpected text alongside the verdict" and blocks every response. An
unfiltered stream would present as a totally broken application.
"""

from __future__ import annotations


import pytest

from akira.knowledge_graph import (
    build_graph,
    hub_of,
    layout,
    summarize,
)
from akira.lock.auditor import parse_verdict
from akira.lock.tripwires import TripwireSet
from akira.models.think_filter import ThinkFilter, strip_think
from akira.schemas import Manifest
from akira.vault import scan_vault


# --- strip_think ------------------------------------------------------------


def test_strips_a_complete_span():
    assert strip_think("<think>reasoning here</think>Answer.") == "Answer."


def test_strips_multiline_reasoning():
    text = "<think>\nstep one\nstep two\n</think>\nThe answer is 4."
    assert "step one" not in strip_think(text)
    assert "The answer is 4." in strip_think(text)


def test_strips_an_unclosed_span():
    # Cut off by max_tokens. Reasoning must not surface just because the model
    # never got to close the tag.
    assert strip_think("Intro. <think>reasoning that never ends") == "Intro. "


def test_passes_plain_text_through_unchanged():
    for text in ["", "hello", "VERDICT: PASS", "a < b and c > d"]:
        assert strip_think(text) == text


def test_strips_multiple_spans():
    assert strip_think("<think>a</think>X<think>b</think>Y") == "XY"


def test_empty_think_pair_from_no_think_switch():
    # /no_think still emits an empty pair; it must not reach the parser.
    assert strip_think("<think>\n\n</think>\n\nVERDICT: PASS").strip() == "VERDICT: PASS"


# --- streaming filter -------------------------------------------------------


def _stream(pieces: list[str]) -> str:
    f = ThinkFilter()
    return "".join(f.feed(p) for p in pieces) + f.flush()


def test_stream_suppresses_reasoning():
    assert _stream(["<think>", "secret ", "reasoning", "</think>", "Answer."]) == "Answer."


def test_stream_handles_tag_split_across_chunks():
    # The realistic case: llama.cpp emits "<thi" then "nk>".
    assert _stream(["<thi", "nk>", "hidden", "</thi", "nk>", "Visible."]) == "Visible."


def test_stream_handles_one_character_at_a_time():
    text = "<think>hidden</think>Shown."
    assert _stream(list(text)) == "Shown."


def test_stream_passes_plain_tokens_through():
    assert _stream(["Hello", " ", "world"]) == "Hello world"


def test_stream_holds_back_a_partial_tag_then_releases_it():
    # "<thi" that turns out to be ordinary text must not be swallowed.
    assert _stream(["a<thi", "ng>b"]) == "a<thing>b"


def test_stream_drops_unclosed_reasoning_at_flush():
    assert _stream(["Intro.", "<think>", "endless"]) == "Intro."


def test_stream_never_emits_tag_fragments():
    out = _stream(["<think>", "x", "</think>", "Y"])
    assert "<" not in out and ">" not in out


# --- the reason it matters --------------------------------------------------


def test_unfiltered_reasoning_would_block_every_response():
    """Documents the failure this filter prevents.

    With reasoning left in, the auditor's own output fails `parse_verdict` and
    the whole app blocks. This asserts both halves: raw blocks, filtered passes.
    """
    raw = "<think>The draft mentions gravity, which is allowed.</think>\nVERDICT: PASS"
    assert parse_verdict(raw).blocked
    assert parse_verdict(strip_think(raw).strip()).passed


# --- Qwen3 dialect detection ------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("Qwen3-14B-Q4_K_M.gguf", True),
        ("qwen3-8b-q4_k_m.gguf", True),
        ("Qwen_Qwen3-14B-Q4_K_M.gguf", True),
        ("Ministral-8B-Instruct-2410-Q4_K_M.gguf", False),
        ("Qwen2.5-14B-Instruct-Q4_K_M.gguf", False),
        ("Mistral-Small-24B-Q4_K_M.gguf", False),
    ],
)
def test_qwen3_detection_by_filename(filename, expected):
    """Family detection drives the /no_think switch, so it must not misfire.

    Filename rather than GGUF metadata: `general.name` is set by whoever ran
    the conversion and is frequently blank or wrong in community quants, while
    nobody renames a model file to disguise its family.
    """
    from akira.models.base import ModelSpec, Role

    # _is_qwen3 only reads spec.path, so this needs no loaded model.
    class Probe:
        spec = ModelSpec(path=rf"C:\models\{filename}", role=Role.MAIN)

    from akira.models.llama_backend import LlamaBackend

    assert LlamaBackend._is_qwen3.fget(Probe()) is expected


# --- knowledge graph --------------------------------------------------------


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "global" / "notes").mkdir(parents=True)
    return root


def put(vault, name, topics, body="Body text."):
    joined = ", ".join(topics)
    (vault / "global" / "notes" / name).write_text(
        f"---\ntopics: [{joined}]\n---\n\n{body}\n", encoding="utf-8"
    )


def _manifest(*unlocked):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    return manifest


def test_hub_of_splits_on_the_first_underscore():
    assert hub_of("python_basics") == "python"
    assert hub_of("python_advanced_loops") == "python"
    assert hub_of("chemistry") == "chemistry"


def test_topics_cluster_into_domains(vault):
    put(vault, "a.md", ["python_basics"])
    put(vault, "b.md", ["python_loops"])
    put(vault, "c.md", ["chemistry_organic"])
    graph = build_graph(scan_vault(vault), Manifest.initial())

    assert {h.topic for h in graph.hubs} == {"python", "chemistry"}
    branches = {(e.a, e.b) for e in graph.edges if e.kind == "branch"}
    assert ("python", "python_basics") in branches
    assert ("python", "python_loops") in branches


def test_subtopic_labels_drop_the_hub_prefix(vault):
    put(vault, "a.md", ["python_basics"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    assert graph.nodes["python_basics"].label == "basics"


def test_a_bare_topic_fuses_with_its_own_hub(vault):
    put(vault, "a.md", ["chemistry"])
    put(vault, "b.md", ["chemistry_organic"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    hub = graph.nodes["chemistry"]
    assert hub.is_hub and hub.is_real
    # It must not also orbit itself.
    assert ("chemistry", "chemistry") not in {(e.a, e.b) for e in graph.edges}


def test_synthetic_hub_is_marked_unreal(vault):
    put(vault, "a.md", ["python_basics"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    assert graph.nodes["python"].is_hub
    assert not graph.nodes["python"].is_real


def test_unlocked_state_is_carried(vault):
    put(vault, "a.md", ["python_basics"])
    put(vault, "b.md", ["python_loops"])
    graph = build_graph(scan_vault(vault), _manifest("python_basics"))
    assert graph.nodes["python_basics"].unlocked
    assert not graph.nodes["python_loops"].unlocked
    assert graph.unlocked_count == 1


def test_locked_topics_still_appear(vault):
    # The whole point of the map is seeing territory you have not taught yet.
    put(vault, "a.md", ["chemistry_organic"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    assert "chemistry_organic" in graph.nodes


def test_topics_come_from_manifest_even_without_notes(vault):
    graph = build_graph(scan_vault(vault), _manifest("physics"))
    assert "physics" in graph.nodes
    assert graph.nodes["physics"].unlocked


def test_topics_come_from_tripwires(vault, tmp_path):
    from akira.lock.tripwires import TopicTripwires

    tripwires = TripwireSet(by_topic={"chemistry": TopicTripwires(topic="chemistry", keywords=("sodium",))})
    graph = build_graph(scan_vault(vault), Manifest.initial(), tripwires)
    assert graph.nodes["chemistry"].has_tripwires


def test_cotagged_topics_get_a_cross_link(vault):
    put(vault, "a.md", ["physics_optics", "chemistry_light"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    cotags = {frozenset((e.a, e.b)) for e in graph.edges if e.kind == "cotag"}
    assert frozenset(("physics_optics", "chemistry_light")) in cotags


def test_cotag_never_duplicates_a_branch(vault):
    put(vault, "a.md", ["python", "python_basics"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    pairs = [frozenset((e.a, e.b)) for e in graph.edges]
    assert len(pairs) == len(set(pairs))


def test_note_counts_are_tallied(vault):
    put(vault, "a.md", ["physics"])
    put(vault, "b.md", ["physics"])
    graph = build_graph(scan_vault(vault), Manifest.initial())
    assert graph.nodes["physics"].note_count == 2


def test_empty_vault_yields_an_empty_graph(vault):
    graph = build_graph(scan_vault(vault), Manifest.initial())
    assert graph.nodes == {}
    assert "No topics yet" in summarize(graph)


# --- layout -----------------------------------------------------------------


def test_layout_places_every_node_inside_the_canvas(vault):
    for i in range(4):
        put(vault, f"n{i}.md", [f"domain{i}_alpha", f"domain{i}_beta"])
    graph = layout(build_graph(scan_vault(vault), Manifest.initial()), 900, 700)
    for node in graph.nodes.values():
        assert 0 <= node.x <= 900, node.topic
        assert 0 <= node.y <= 700, node.topic
        assert node.radius > 0


def test_layout_is_deterministic(vault):
    # A map that will not hold still is useless for building a mental model.
    put(vault, "a.md", ["python_basics", "python_loops", "chemistry_organic"])
    scan = scan_vault(vault)
    first = layout(build_graph(scan, Manifest.initial()), 800, 600)
    second = layout(build_graph(scan, Manifest.initial()), 800, 600)
    assert {k: (v.x, v.y) for k, v in first.nodes.items()} == {
        k: (v.x, v.y) for k, v in second.nodes.items()
    }


def test_single_hub_sits_at_the_center(vault):
    put(vault, "a.md", ["physics_optics"])
    graph = layout(build_graph(scan_vault(vault), Manifest.initial()), 800, 600)
    hub = graph.nodes["physics"]
    assert abs(hub.x - 400) < 1 and abs(hub.y - 300) < 1


def test_summary_counts_domains_and_unlocks(vault):
    put(vault, "a.md", ["python_basics"])
    put(vault, "b.md", ["chemistry_organic"])
    graph = build_graph(scan_vault(vault), _manifest("python_basics"))
    text = summarize(graph)
    assert "2 domain(s)" in text and "1 unlocked" in text


# --- icon -------------------------------------------------------------------


def test_icon_asset_exists_and_is_a_multi_size_ico():
    import struct
    from pathlib import Path

    icon = Path(__file__).resolve().parent.parent / "akira" / "ui" / "assets" / "akira.ico"
    assert icon.is_file(), "run tools/make_icon.py"
    data = icon.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert reserved == 0 and kind == 1
    # Windows picks per-context sizes; one bitmap scaled badly is the thing to avoid.
    assert count >= 5
    sizes = {struct.unpack("<BBBBHHII", data[6 + 16 * i:22 + 16 * i])[0] or 256 for i in range(count)}
    assert {16, 32, 256} <= sizes


# --- Tk-dependent -----------------------------------------------------------


@pytest.fixture
def root(clean_root):
    """The shared session-wide Tk interpreter (see conftest.py).

    Not a fresh `tk.Tk()` per module: several live interpreters in one process
    made Tk fail intermittently, and the fixture's TclError handler turned that
    into a silent skip of the whole module.
    """
    return clean_root


def test_sidebar_constructs_and_lists_projects(root):
    from akira.ui.sidebar import Sidebar

    calls: list[str] = []
    bar = Sidebar(
        root,
        actions={"new_session": lambda: calls.append("new"), "settings": lambda: calls.append("set")},
        projects=["default", "research"],
        current_project="default",
        on_switch_project=lambda n: calls.append(n),
        on_new_project=lambda: calls.append("newproj"),
    )
    bar.pack()
    root.update_idletasks()
    assert set(bar._project_rows) == {"default", "research"}
    bar.set_status("Tier 0\n2 topics")
    assert "Tier 0" in bar.status.cget("text")
    bar.destroy()


def test_sidebar_marks_the_current_project(root):
    from akira.ui import theme
    from akira.ui.sidebar import Sidebar

    bar = Sidebar(
        root, actions={}, projects=["a", "b"], current_project="b",
        on_switch_project=lambda n: None, on_new_project=lambda: None,
    )
    root.update_idletasks()
    assert str(bar._project_rows["b"].cget("bg")) == theme.PURPLE_DEEP
    assert str(bar._project_rows["a"].cget("bg")) == theme.BG_PANEL
    bar.destroy()


def test_knowledge_web_keeps_every_node_on_screen(root, vault):
    """Regression: the first draw runs before the button row claims its space.

    Laying out against that stale, taller canvas height pushed the bottom hub
    and its subtopics below the visible area. A deferred redraw once geometry
    settles is the fix; this checks the outcome at several window sizes rather
    than trusting the mechanism.
    """
    from akira.lock.tripwires import TripwireSet
    from akira.models import ModelManager
    from akira.schemas import Settings
    from akira.ui.knowledge_web import KnowledgeWebDialog
    from akira.unlock import UnlockFlow

    for i in range(4):
        put(vault, f"d{i}.md", [f"domain{i}_alpha", f"domain{i}_beta", f"domain{i}_gamma"])
    settings = Settings.from_json({"models": {"main_path": "m.gguf", "auditor_path": "m.gguf"}})
    flow = UnlockFlow(
        vault, Manifest.initial(), settings,
        ModelManager(settings, factory=lambda spec: None), tripwires=TripwireSet(),
    )
    # A visible parent: a transient of a withdrawn master never maps on
    # Windows, and an unmapped canvas reports 1x1.
    root.deiconify()
    try:
        for size in ("1000x740", "760x560"):
            dialog = KnowledgeWebDialog(root, flow)
            dialog.geometry(size)
            for _ in range(6):
                dialog.update_idletasks()
                dialog.update()
            width = dialog.canvas.winfo_width()
            height = dialog.canvas.winfo_height()
            for node in dialog.graph.nodes.values():
                assert 0 <= node.x <= width, f"{node.topic} off-canvas at {size}"
                assert node.y - node.radius >= 0, f"{node.topic} above canvas at {size}"
                # +16 leaves room for the label hanging below the node.
                assert node.y + node.radius + 16 <= height, f"{node.topic} below canvas at {size}"
            dialog.destroy()
    finally:
        root.withdraw()


def test_knowledge_web_constructs(root, vault):
    from akira.lock.tripwires import TripwireSet
    from akira.models import ModelManager
    from akira.schemas import Settings
    from akira.ui.knowledge_web import KnowledgeWebDialog
    from akira.unlock import UnlockFlow

    put(vault, "a.md", ["python_basics"])
    put(vault, "b.md", ["chemistry_organic"])
    settings = Settings.from_json({"models": {"main_path": "m.gguf", "auditor_path": "m.gguf"}})
    flow = UnlockFlow(
        vault, _manifest("python_basics"), settings,
        ModelManager(settings, factory=lambda spec: None), tripwires=TripwireSet(),
    )
    dialog = KnowledgeWebDialog(root, flow)
    root.update_idletasks()
    # Nodes are drawn and clickable.
    assert dialog._hit
    assert "python_basics" in dialog._hit.values()
    dialog.destroy()


def test_the_blank_lines_after_an_empty_think_span_do_not_open_the_reply():
    from akira.models.think_filter import ThinkFilter

    stream = ThinkFilter()
    pieces = ["<think>", "\n\n", "</think>", "\n", "\n", "The answer", " is 391.", "\n"]
    out = "".join(stream.feed(piece) for piece in pieces) + stream.flush()
    assert out == "The answer is 391.\n"
    plain = ThinkFilter()
    assert plain.feed("  Indented only at the start") == "Indented only at the start"
    assert plain.feed("\n\nkept once it has begun") == "\n\nkept once it has begun"
