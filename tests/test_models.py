"""Model layer: specs, the manager's loading policy, and timeout behavior."""

from __future__ import annotations

import time

import pytest

from protege.models import ModelManager, ModelSpec, ModelUnavailable, Role, deadline_from
from protege.models.base import ChatMessage, GenerationTimeout
from protege.models.scripted import ScriptedBackend, always_block_auditor, always_pass_auditor
from protege.schemas import Settings


def _settings(**models) -> Settings:
    return Settings.from_json({"models": models})


def _factory(created: list[ModelSpec]):
    def make(spec: ModelSpec):
        created.append(spec)
        return ScriptedBackend(spec, patterns=[(r".*", "ok")])

    return make


# --- messages --------------------------------------------------------------


def test_chat_message_rejects_unknown_role():
    with pytest.raises(ValueError):
        ChatMessage(role="tool", content="x")


# --- manager: configuration ------------------------------------------------


def test_specs_derive_from_settings():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", main_ctx=8192, auditor_ctx=2048)
    manager = ModelManager(settings, factory=_factory([]))
    assert manager.spec_for(Role.MAIN).n_ctx == 8192
    assert manager.spec_for(Role.AUDITOR).n_ctx == 2048
    assert manager.spec_for(Role.AUDITOR).role is Role.AUDITOR


def test_unconfigured_model_raises_unavailable():
    manager = ModelManager(_settings(), factory=_factory([]))
    with pytest.raises(ModelUnavailable, match="MAIN"):
        with manager.acquire(Role.MAIN):
            pass


def test_status_is_not_ready_without_an_auditor():
    # An unconfigured auditor is not a reduced capability. Layer 5 cannot run,
    # and a layer that cannot run blocks -- so reporting "ready" would promise
    # a turn that always ends in a block.
    settings = _settings(main_path="m.gguf")
    manager = ModelManager(settings, factory=_factory([]))
    status = manager.status()
    assert status.main_configured
    assert not status.auditor_configured
    assert not status.ready
    assert "Layer 5" in status.detail


# --- manager: sequential vs concurrent -------------------------------------


def test_sequential_keeps_only_one_model_resident():
    created: list[ModelSpec] = []
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", loading="sequential")
    manager = ModelManager(settings, factory=_factory(created))

    with manager.acquire(Role.MAIN) as main:
        assert main.is_loaded
    with manager.acquire(Role.AUDITOR) as auditor:
        assert auditor.is_loaded
        # System RAM is the binding constraint on the target box, so the
        # previous model must actually be released, not merely dereferenced.
        assert not main.is_loaded

    assert [s.role for s in created] == [Role.MAIN, Role.AUDITOR]


def test_concurrent_keeps_both_resident():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", loading="concurrent")
    manager = ModelManager(settings, factory=_factory([]))
    with manager.acquire(Role.MAIN) as main:
        pass
    with manager.acquire(Role.AUDITOR):
        assert main.is_loaded


def test_reacquiring_reuses_the_loaded_backend():
    created: list[ModelSpec] = []
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", loading="concurrent")
    manager = ModelManager(settings, factory=_factory(created))
    with manager.acquire(Role.MAIN) as first:
        pass
    with manager.acquire(Role.MAIN) as second:
        assert first is second
    assert len(created) == 1


# --- manager: the shared-model fallback ------------------------------------


def test_identical_paths_share_one_backend():
    # Ministral 3B's weights were never published, so pointing AUDITOR at MAIN's
    # file is a supported configuration rather than a degraded one -- and it
    # preserves the same-family/matched-tokenizer argument exactly.
    created: list[ModelSpec] = []
    settings = _settings(main_path="m.gguf", auditor_path="m.gguf")
    manager = ModelManager(settings, factory=_factory(created))
    assert manager.shares_one_model
    with manager.acquire(Role.MAIN) as main:
        with manager.acquire(Role.AUDITOR) as auditor:
            assert main is auditor
    assert len(created) == 1, "a shared model must not be loaded twice"


def test_shared_model_path_comparison_ignores_case_and_relativity(tmp_path):
    target = tmp_path / "Model.gguf"
    settings = _settings(main_path=str(target), auditor_path=str(target).upper())
    manager = ModelManager(settings, factory=_factory([]))
    # normcase makes this correct on Windows, where the two spellings name the
    # same file. On POSIX they differ and sharing is correctly declined.
    import os

    assert manager.shares_one_model == (os.path.normcase("A") == os.path.normcase("a"))


def test_shared_model_is_reported_as_sequential():
    settings = _settings(main_path="m.gguf", auditor_path="m.gguf", loading="concurrent")
    manager = ModelManager(settings, factory=_factory([]))
    # One context, serialized by the lock. Calling it "concurrent" would imply
    # a second model is resident and 5GB of RAM is spoken for.
    assert manager.status().loading_mode == "sequential"
    assert manager.status().shared


def test_unrelated_paths_are_not_shared():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf")
    assert not ModelManager(settings, factory=_factory([])).shares_one_model


def test_empty_paths_are_not_treated_as_shared():
    # Two unset paths are both "", which must not be read as "same model".
    assert not ModelManager(_settings(), factory=_factory([])).shares_one_model


# --- manager: settings changes ---------------------------------------------


def test_changing_model_path_unloads():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf")
    manager = ModelManager(settings, factory=_factory([]))
    with manager.acquire(Role.MAIN) as main:
        pass
    manager.update_settings(_settings(main_path="other.gguf", auditor_path="a.gguf"))
    assert not main.is_loaded


def test_unrelated_settings_change_keeps_models_loaded():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", temperature=0.7)
    manager = ModelManager(settings, factory=_factory([]))
    with manager.acquire(Role.MAIN) as main:
        pass
    manager.update_settings(_settings(main_path="m.gguf", auditor_path="a.gguf", temperature=0.1))
    # Reloading 5GB because a temperature slider moved would be a bad trade.
    assert main.is_loaded


def test_close_releases_everything():
    settings = _settings(main_path="m.gguf", auditor_path="a.gguf", loading="concurrent")
    manager = ModelManager(settings, factory=_factory([]))
    with manager.acquire(Role.MAIN) as main:
        pass
    with manager.acquire(Role.AUDITOR) as auditor:
        pass
    manager.close()
    assert not main.is_loaded and not auditor.is_loaded


# --- timeouts --------------------------------------------------------------


def test_generation_past_deadline_raises_rather_than_returning_partial_text():
    # The critical property: a timed-out generation must not return the text it
    # managed to produce. A truncated auditor verdict beginning "VERDICT: PASS"
    # would otherwise parse as a pass.
    backend = ScriptedBackend(replies=["VERDICT: PASS"], latency_s=0.5)
    with pytest.raises(GenerationTimeout):
        backend.generate([ChatMessage(role="user", content="x")], deadline=deadline_from(0.05))


def test_generation_within_deadline_succeeds():
    backend = ScriptedBackend(replies=["fine"], latency_s=0.01)
    result = backend.generate([ChatMessage(role="user", content="x")], deadline=deadline_from(5.0))
    assert result.text == "fine"


def test_already_expired_deadline_raises_immediately():
    backend = ScriptedBackend(replies=["fine"])
    started = time.monotonic()
    with pytest.raises(GenerationTimeout):
        backend.generate([ChatMessage(role="user", content="x")], deadline=time.monotonic() - 1)
    assert time.monotonic() - started < 0.5


# --- the scripted double itself --------------------------------------------


def test_scripted_backend_fails_loudly_when_over_called():
    # A test double that silently repeats its last answer turns an unexpected
    # extra model call into a passing test.
    backend = ScriptedBackend(replies=["one"])
    backend.generate([ChatMessage(role="user", content="x")])
    with pytest.raises(AssertionError, match="ran out of replies"):
        backend.generate([ChatMessage(role="user", content="x")])


def test_scripted_patterns_take_priority_over_the_queue():
    backend = ScriptedBackend(replies=["queued"], patterns=[(r"secret", "matched")])
    assert backend.generate([ChatMessage(role="user", content="a secret thing")]).text == "matched"
    assert backend.generate([ChatMessage(role="user", content="ordinary")]).text == "queued"


def test_scripted_records_calls_for_assertion():
    backend = ScriptedBackend(replies=["a"])
    backend.generate([ChatMessage(role="system", content="sys"), ChatMessage(role="user", content="u")])
    assert [m.role for m in backend.calls[0]] == ["system", "user"]


def test_scripted_auditor_helpers():
    assert "PASS" in always_pass_auditor().generate([ChatMessage(role="user", content="x")]).text
    blocked = always_block_auditor("chemistry").generate([ChatMessage(role="user", content="x")]).text
    assert "BLOCK" in blocked and "chemistry" in blocked
