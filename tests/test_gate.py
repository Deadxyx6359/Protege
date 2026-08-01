"""The gate -- Layers 4 and 5 together, and the fail-closed guarantee.

The last test class is the one that matters most: it injects a failure into
every component in turn and asserts that each one produces a block. A lock
system is only as good as its behavior when something breaks, and "something
breaks" is the normal case for a 3B model parsing structured output.
"""

from __future__ import annotations

import json

import pytest

from protege.lock.pipeline import GateReport, OutputGate, is_pure_decline
from protege.lock.tripwires import TripwireSet
from protege.models import ModelManager, ModelSpec, Role
from protege.models.base import ModelUnavailable
from protege.models.scripted import ScriptedBackend
from protege.schemas import Manifest, Settings
from protege.store import bootstrap_vault, tripwire_dir


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    bootstrap_vault(root)
    return root


def put_tripwires(vault, topic, keywords=(), patterns=()):
    (tripwire_dir(vault) / f"{topic}.json").write_text(
        json.dumps({"topic": topic, "keywords": list(keywords), "patterns": list(patterns)}),
        encoding="utf-8",
    )


def make_gate(vault, *, unlocked=(), auditor_reply="VERDICT: PASS", layers=None, auditor_backend=None,
              strictness="normal"):
    manifest = Manifest.initial()
    for topic in unlocked:
        manifest = manifest.with_unlocked(topic)
    settings = Settings.from_json({
        "models": {"main_path": "m.gguf", "auditor_path": "a.gguf"},
        "lock_layers": layers or {},
        "auditor": {"strictness": strictness},
    })
    backend = auditor_backend or ScriptedBackend(
        ModelSpec(path="a.gguf", role=Role.AUDITOR), patterns=[(r".*", auditor_reply)]
    )
    manager = ModelManager(settings, factory=lambda spec: backend)
    return OutputGate(manifest, settings, TripwireSet.load(vault), manager), backend


# --- pure declines ---------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("[LOCKED: chemistry]", True),
        ("  [LOCKED: chemistry]  ", True),
        ("[LOCKED: chemistry]\n[LOCKED: physics]", True),
        ("[LOCKED: chemistry] but here is a hint: sodium", False),
        ("Sure! [LOCKED: chemistry]", False),
        ("I can't discuss that", False),
        ("", False),
    ],
)
def test_pure_decline_detection(text, expected):
    assert is_pure_decline(text) is expected


def test_compliant_decline_skips_the_auditor(vault):
    # Saves several seconds per refusal on a box where the auditor may be
    # sharing MAIN's 8B weights.
    gate, backend = make_gate(vault, unlocked=["physics"])
    result = gate.check("tell me about chemistry", "[LOCKED: chemistry]")
    assert result.allowed
    assert backend.calls == []
    assert "auditor" in result.layers_skipped


def test_decline_with_a_smuggled_hint_is_still_audited(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=["physics"])
    result = gate.check("q", "[LOCKED: chemistry] but it involves sodium")
    assert not result.allowed
    assert result.layer == "tripwires"


# --- layer ordering --------------------------------------------------------


def test_tripwires_run_before_the_auditor(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, backend = make_gate(vault, unlocked=["physics"])
    result = gate.check("q", "You need sodium for this.")
    assert not result.allowed
    assert result.layer == "tripwires"
    # No point spending seconds of inference on text already known to be bad.
    assert backend.calls == []


def test_auditor_runs_when_tripwires_are_clean(vault):
    gate, backend = make_gate(vault, unlocked=["physics"], auditor_reply="VERDICT: BLOCK\nTOPIC: chemistry")
    result = gate.check("q", "Salt is sodium chloride.")
    assert not result.allowed
    assert result.layer == "auditor"
    assert result.topic == "chemistry"
    assert len(backend.calls) == 1


def test_clean_text_passes_both_layers(vault):
    gate, _ = make_gate(vault, unlocked=["physics"])
    result = gate.check("q", "Objects fall at nine point eight metres per second squared.")
    assert result.allowed
    assert result.layers_run == ("tripwires", "auditor")


# --- layer toggles ---------------------------------------------------------


def test_disabled_tripwires_are_skipped(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=["physics"], layers={"tripwires": False})
    result = gate.check("q", "You need sodium.")
    assert result.allowed
    assert "tripwires" in result.layers_skipped


def test_disabled_auditor_is_skipped(vault):
    gate, backend = make_gate(vault, unlocked=["physics"], layers={"auditor": False})
    result = gate.check("q", "anything at all")
    assert result.allowed
    assert backend.calls == []


def test_both_disabled_passes_everything(vault):
    # This is what the UI warning strip exists to make impossible to forget.
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=[], layers={"tripwires": False, "auditor": False})
    assert gate.check("q", "sodium sodium sodium").allowed


# --- scoping ---------------------------------------------------------------


def test_only_locked_topics_are_scanned(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=["chemistry"])
    assert gate.check("q", "Sodium reacts with water.").allowed


def test_locked_topics_to_scan_excludes_unlocked(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    put_tripwires(vault, "physics", keywords=["gravity"])
    gate, _ = make_gate(vault, unlocked=["physics"])
    assert gate.locked_topics_to_scan() == ("chemistry",)


# --- fail closed: the property the whole system rests on -------------------


def test_auditor_timeout_blocks(vault):
    slow = ScriptedBackend(
        ModelSpec(path="a.gguf", role=Role.AUDITOR),
        patterns=[(r".*", "VERDICT: PASS")],
        latency_s=5.0,
    )
    manifest = Manifest.initial()
    settings = Settings.from_json({
        "models": {"main_path": "m.gguf", "auditor_path": "a.gguf"},
        "auditor": {"timeout_s": 1.0},
    })
    manager = ModelManager(settings, factory=lambda spec: slow)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    result = gate.check("q", "some draft")
    assert not result.allowed
    assert result.layer == "auditor"


def test_auditor_backend_unavailable_blocks(vault):
    class Broken(ScriptedBackend):
        def generate(self, *a, **k):
            raise ModelUnavailable("could not load auditor")

    gate, _ = make_gate(vault, auditor_backend=Broken(ModelSpec(path="a.gguf", role=Role.AUDITOR)))
    result = gate.check("q", "some draft")
    assert not result.allowed
    assert result.layer == "auditor"


def test_auditor_returning_garbage_blocks(vault):
    gate, _ = make_gate(vault, auditor_reply="I'm not sure, it might be okay?")
    assert not gate.check("q", "some draft").allowed


def test_auditor_returning_nothing_blocks(vault):
    gate, _ = make_gate(vault, auditor_reply="")
    assert not gate.check("q", "some draft").allowed


def test_model_manager_failure_blocks(vault):
    manifest = Manifest.initial()
    settings = Settings.from_json({"models": {"main_path": "m.gguf", "auditor_path": "a.gguf"}})

    def exploding_factory(spec):
        raise RuntimeError("CUDA out of memory")

    manager = ModelManager(settings, factory=exploding_factory)
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    result = gate.check("q", "some draft")
    assert not result.allowed
    # Surfaced through the auditor layer, which is where the load was attempted.
    assert result.layer in ("auditor", "error")


def test_a_bug_in_the_tripwire_layer_blocks(vault):
    gate, _ = make_gate(vault, unlocked=["physics"])

    class Exploding(TripwireSet):
        def scan(self, *a, **k):
            raise AttributeError("bug introduced by a future edit")

    gate._tripwires = Exploding()
    result = gate.check("q", "harmless text")
    # The single broad except in OutputGate.check is what makes this hold. It
    # must stay broad.
    assert not result.allowed
    assert result.layer == "error"
    assert "AttributeError" in result.reason


def test_unconfigured_auditor_blocks(vault):
    manifest = Manifest.initial()
    settings = Settings.from_json({"models": {"main_path": "m.gguf"}})  # no auditor_path
    manager = ModelManager(settings, factory=lambda spec: ScriptedBackend(spec))
    gate = OutputGate(manifest, settings, TripwireSet.load(vault), manager)
    result = gate.check("q", "some draft")
    assert not result.allowed


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("boom"), ValueError("bad"), MemoryError(), OSError("disk"), TypeError("wrong")],
)
def test_any_ordinary_exception_becomes_a_block(vault, exc):
    gate, _ = make_gate(vault)

    class Exploding(TripwireSet):
        def scan(self, *a, **k):
            raise exc

    gate._tripwires = Exploding()
    result = gate.check("q", "draft")
    assert not result.allowed
    assert result.layer == "error"


def test_base_exceptions_propagate_rather_than_becoming_a_pass(vault):
    """KeyboardInterrupt and SystemExit are deliberately NOT caught.

    Swallowing them would break Ctrl-C and clean shutdown. Fail-closed survives
    anyway, and structurally rather than by catching: every caller acts only on
    an explicit `allowed=True`, so an exception that escapes produces no
    GateResult at all and therefore cannot produce a pass. "Blocked" and "never
    returned" are equally safe; only "returned allowed=True" is not.
    """
    gate, _ = make_gate(vault)

    class Interrupting(TripwireSet):
        def scan(self, *a, **k):
            raise KeyboardInterrupt("user pressed ctrl-c")

    gate._tripwires = Interrupting()
    with pytest.raises(KeyboardInterrupt):
        gate.check("q", "draft")


# --- reporting -------------------------------------------------------------


def test_block_detail_carries_the_layer_and_evidence(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=["physics"])
    detail = gate.check("q", "Use sodium.").to_block_detail()
    assert detail.layer == "tripwires"
    assert detail.topic == "chemistry"
    assert "sodium" in detail.evidence


def test_gate_report_counts_by_layer(vault):
    put_tripwires(vault, "chemistry", keywords=["sodium"])
    gate, _ = make_gate(vault, unlocked=["physics"], auditor_reply="VERDICT: PASS")
    report = GateReport()
    report.record(gate.check("q", "Use sodium."))
    report.record(gate.check("q", "Objects fall."))
    assert report.checks == 2
    assert report.blocks == 1
    assert report.by_layer["tripwires"] == 1
