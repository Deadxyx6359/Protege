"""One generation at a time, and never a model freed under a running one.

The router used to hold its lock only while *loading*, then hand the model out
unguarded. While the chat turn was the only thing that generated, that was
enough. Once the scheduler could run an agent while a turn streamed, two
threads could generate on one llama.cpp model at once — which it does not
support — and a thread loading a second large model would evict the first
while it was still generating: freed memory being read, a native crash rather
than an exception. A settings change from the UI thread could do the same.

These drive the real `acquire` with a fake llama module, so they exercise the
locking itself rather than a replacement for it.
"""

from __future__ import annotations

import threading
import time

import pytest

from akira.core.config import AppConfig, ModelConfig
from akira.core.models import ModelRouter, Route


@pytest.fixture(autouse=True)
def tiny_models_allowed(monkeypatch):
    monkeypatch.setattr("akira.core.config._MIN_MODEL_BYTES", 8)


class Probe:
    """How many callers were inside at once, across every backend."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.inside = 0
        self.peak = 0
        self.used_after_close = False


class SlowBackend:
    n_ctx = 2048

    def __init__(self, spec, probe: Probe) -> None:
        self.spec = spec
        self.probe = probe
        self.closed = False
        self.is_loaded = True

    def work(self, *, hold=None, pause=0.03, entered=None) -> None:
        with self.probe.lock:
            self.probe.inside += 1
            self.probe.peak = max(self.probe.peak, self.probe.inside)
        try:
            if entered is not None:
                entered.set()
            if hold is not None:
                hold.wait(5)
            else:
                time.sleep(pause)
            if self.closed:
                self.probe.used_after_close = True
        finally:
            with self.probe.lock:
                self.probe.inside -= 1

    def close(self) -> None:
        self.closed = True
        self.is_loaded = False


class FakeLlama:
    def __init__(self, probe: Probe) -> None:
        self.probe = probe
        self.created: list[SlowBackend] = []

    def library_available(self) -> bool:
        return True

    def LlamaBackend(self, spec) -> SlowBackend:  # noqa: N802 - mirrors the real name
        backend = SlowBackend(spec, self.probe)
        self.created.append(backend)
        return backend


@pytest.fixture
def probe():
    return Probe()


@pytest.fixture
def llama(probe, monkeypatch):
    fake = FakeLlama(probe)
    monkeypatch.setattr(ModelRouter, "_backend_module", staticmethod(lambda: fake))
    return fake


def config_for(tmp_path, **files) -> AppConfig:
    models = {}
    for route, name in files.items():
        path = tmp_path / name
        path.write_bytes(b"GGUF" + bytes(64))
        models[route] = ModelConfig(path=str(path))
    return AppConfig(models=models)


def work(router, route, **kwargs) -> None:
    with router.acquire(route) as backend:
        backend.work(**kwargs)


def in_thread(target, *args, **kwargs) -> threading.Thread:
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


def test_two_callers_never_generate_at_once(tmp_path, llama, probe):
    router = ModelRouter(config_for(tmp_path, chat="chat.gguf"))
    threads = [in_thread(work, router, Route.CHAT) for _ in range(4)]
    for thread in threads:
        thread.join(10)
    assert probe.peak == 1


def test_a_second_large_model_waits_rather_than_evicting_one_in_use(tmp_path, llama, probe):
    router = ModelRouter(config_for(tmp_path, chat="chat.gguf", code="code.gguf"))
    hold, entered = threading.Event(), threading.Event()
    first = in_thread(work, router, Route.CHAT, hold=hold, entered=entered)
    assert entered.wait(5)
    chat = llama.created[0]

    second = in_thread(work, router, Route.CODE)
    time.sleep(0.2)
    assert not chat.closed, "the chat model was evicted while it was generating"
    assert len(llama.created) == 1, "the code model loaded over a running generation"

    hold.set()
    first.join(5)
    second.join(5)
    assert chat.closed, "once free, it is evicted to make room, as before"
    assert not probe.used_after_close


def test_changing_a_model_mid_generation_neither_blocks_nor_frees_it(tmp_path, llama, probe):
    router = ModelRouter(config_for(tmp_path, chat="old.gguf"))
    hold, entered = threading.Event(), threading.Event()
    running = in_thread(work, router, Route.CHAT, hold=hold, entered=entered)
    assert entered.wait(5)
    old = llama.created[0]

    started = time.monotonic()
    router.update(config_for(tmp_path, chat="new.gguf"))
    assert time.monotonic() - started < 1.0, "a settings change waited out a generation"
    assert not old.closed, "the model was freed while it was generating"

    hold.set()
    running.join(5)
    work(router, Route.CHAT)
    assert old.closed, "the next use unloads the stale model"
    assert str(llama.created[-1].spec.path).endswith("new.gguf")
    assert not probe.used_after_close


def test_a_change_with_nothing_running_unloads_straight_away(tmp_path, llama):
    router = ModelRouter(config_for(tmp_path, chat="old.gguf"))
    work(router, Route.CHAT)
    old = llama.created[0]
    router.update(config_for(tmp_path, chat="new.gguf"))
    assert old.closed


def test_closing_waits_for_a_running_generation_and_declines_rather_than_crash(tmp_path, llama):
    router = ModelRouter(config_for(tmp_path, chat="chat.gguf"))
    hold, entered = threading.Event(), threading.Event()
    running = in_thread(work, router, Route.CHAT, hold=hold, entered=entered)
    assert entered.wait(5)
    backend = llama.created[0]

    assert router.unload_all(timeout=0.2) is False
    assert not backend.closed, "it unloaded a model mid-generation"

    hold.set()
    running.join(5)
    assert router.unload_all() is True and backend.closed


def test_a_generation_that_raises_does_not_keep_the_model(tmp_path, llama):
    router = ModelRouter(config_for(tmp_path, chat="chat.gguf"))
    with pytest.raises(RuntimeError):
        with router.acquire(Route.CHAT):
            raise RuntimeError("the model fell over")
    after = in_thread(work, router, Route.CHAT)
    after.join(2)
    assert not after.is_alive(), "the lock was left held after an exception"


# -- lending the graphics card ---------------------------------------------------------------------


def test_setting_models_aside_unloads_them_and_keeps_them_out_until_done(tmp_path, llama):
    from akira.core.models import ModelUnavailable

    router = ModelRouter(config_for(tmp_path, chat="chat.gguf"))
    work(router, Route.CHAT)
    loaded = llama.created[0]
    with router.set_aside():
        assert loaded.closed, "the model stayed on the card"
        waiting = in_thread(work, router, Route.CHAT)
        time.sleep(0.2)
        assert waiting.is_alive() and len(llama.created) == 1, "a model loaded meanwhile"
    waiting.join(5)
    assert not waiting.is_alive() and len(llama.created) == 2, "the next answer loads it again"

    hold, entered = threading.Event(), threading.Event()
    running = in_thread(work, router, Route.CHAT, hold=hold, entered=entered)
    assert entered.wait(5)
    with pytest.raises(ModelUnavailable, match="still answering"):
        with router.set_aside(timeout=0.2):
            pass
    assert not llama.created[-1].closed, "it unloaded a model mid-generation"
    hold.set()
    running.join(5)


def test_while_the_card_is_lent_for_long_work_a_caller_is_told_at_once(tmp_path, llama):
    from akira.core.models import ModelUnavailable

    router = ModelRouter(config_for(tmp_path, chat="chat.gguf"))
    with router.set_aside(lent_for="The graphics card is training an adapter until it ends."):
        started = time.monotonic()
        with pytest.raises(ModelUnavailable, match="training an adapter"):
            with router.acquire(Route.CHAT):
                pass
        assert time.monotonic() - started < 0.5, "it waited instead of saying why"
        assert router.lent
    assert router.lent == ""
    work(router, Route.CHAT)
