"""The rebuilt core: configuration, routing, and running a turn.

Everything here runs against a fake backend. Exercising this against a real
GGUF would make the suite take minutes and would measure the model rather than
the code — and the interesting failures (truncation, cancellation, fallback)
are all in the code.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest

from protege.core.config import AppConfig, ModelConfig, autoconfigure
from protege.core.conversation import (
    Cancelled,
    Conversation,
    Responder,
    build_prompt,
    route_for,
)
from protege.core.models import HEAVY_BYTES, ModelRouter, Route
from protege.models.base import GenerationResult


@pytest.fixture(autouse=True)
def tiny_models_allowed(monkeypatch):
    """Let a few hundred bytes stand in for a model file.

    `discover_models` rejects anything under 100 MB, which is right in
    production and absurd in a test — writing real-sized files would make the
    suite move gigabytes.
    """
    monkeypatch.setattr("protege.core.config._MIN_MODEL_BYTES", 8)


def write_model(path, extra=0):
    """A file that passes the GGUF header check."""
    path.write_bytes(b"GGUF" + bytes(64 + extra))
    return path


class FakeBackend:
    """A backend that streams a fixed script."""

    is_loaded = True
    n_ctx = 2048

    def __init__(self, pieces: list[str] | None = None) -> None:
        self.pieces = pieces or ["Hello", " there."]
        self.seen: list = []
        self.closed = False

    def count_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def generate(self, messages, *, max_tokens=512, temperature=0.7, top_p=0.95,
                 stop=(), deadline=None, on_token=None):
        self.seen = list(messages)
        for piece in self.pieces:
            if on_token is not None:
                on_token(piece)
        return GenerationResult(text="".join(self.pieces), completion_tokens=len(self.pieces))

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def wired():
    """A responder whose router always yields one fake backend."""

    def build(pieces=None, max_tokens=128):
        backend = FakeBackend(pieces)
        config = AppConfig(models={"chat": ModelConfig(path="fake.gguf", max_tokens=max_tokens)})
        router = ModelRouter(config)

        @contextmanager
        def acquire(route):
            yield backend

        router.acquire = acquire  # type: ignore[method-assign]
        router.resolve = lambda route: Route.CHAT  # type: ignore[method-assign]
        return Responder(router, config), backend

    return build


# -- streaming ---------------------------------------------------------------


def test_tokens_reach_the_caller_in_order(wired):
    responder, _ = wired(["one ", "two ", "three"])
    conversation = Conversation()
    conversation.add("user", "count")

    chunks: list[str] = []
    responder.respond(conversation, on_token=chunks.append)

    assert "".join(chunks) == "one two three"


def test_reasoning_blocks_never_reach_the_caller(wired):
    """A model that narrates between <think> tags must not have that shown.

    Not cosmetic: the reasoning is not the answer, and displaying it presents
    the model's scratch work as its response.
    """
    responder, _ = wired(["Answer: ", "<think>", "deliberating", "</think>", "42"])
    conversation = Conversation()
    conversation.add("user", "the question")

    chunks: list[str] = []
    responder.respond(conversation, on_token=chunks.append)

    streamed = "".join(chunks)
    assert "deliberating" not in streamed
    assert streamed == "Answer: 42"


# -- cancellation ------------------------------------------------------------


def test_cancelling_unwinds_the_generation(wired):
    """A Python thread cannot be killed, so Stop has to raise out of the stream."""
    responder, _ = wired(["a", "b", "c"])
    conversation = Conversation()
    conversation.add("user", "stop me")

    with pytest.raises(Cancelled):
        responder.respond(conversation, on_token=lambda _: None, is_cancelled=lambda: True)


def test_cancelling_midway_keeps_what_already_arrived(wired):
    """Discarding a partial answer would punish pressing Stop."""
    responder, _ = wired(["keep ", "this ", "drop", "this"])
    conversation = Conversation()
    conversation.add("user", "partial")

    chunks: list[str] = []
    # Cancel once two pieces are through.
    with pytest.raises(Cancelled):
        responder.respond(
            conversation,
            on_token=chunks.append,
            is_cancelled=lambda: len(chunks) >= 2,
        )

    assert "".join(chunks) == "keep this "


# -- prompt assembly ---------------------------------------------------------


def test_prompt_always_leads_with_the_system_message(wired):
    responder, backend = wired()
    conversation = Conversation()
    conversation.add("user", "hello")
    responder.respond(conversation)

    assert backend.seen[0].role == "system"
    assert backend.seen[-1].content == "hello"


def test_truncation_drops_the_oldest_and_keeps_the_newest():
    """The last exchanges carry the context; the opening small talk does not."""
    backend = FakeBackend()
    conversation = Conversation()
    for i in range(200):
        role = "user" if i % 2 == 0 else "assistant"
        conversation.add(role, f"message number {i} " * 20)

    messages = build_prompt(conversation, backend, reply_budget=256)

    assert messages[0].role == "system"
    assert messages[-1].content.startswith("message number 199")
    assert len(messages) < len(conversation.messages)


def test_empty_messages_are_not_sent():
    """The streaming placeholder is appended before generation starts."""
    backend = FakeBackend()
    conversation = Conversation()
    conversation.add("user", "real")
    conversation.add("assistant")  # the placeholder the stream writes into

    messages = build_prompt(conversation, backend, reply_budget=128)

    assert [m.content for m in messages[1:]] == ["real"]


# -- titles ------------------------------------------------------------------


def test_title_comes_from_the_opening_question():
    conversation = Conversation()
    conversation.add("user", "What is a squircle?")
    assert conversation.derive_title() == "What is a squircle?"


def test_long_titles_are_elided():
    conversation = Conversation()
    conversation.add("user", "word " * 100)
    title = conversation.derive_title(limit=20)
    assert len(title) <= 20
    assert title.endswith("…")


def test_title_of_an_empty_conversation():
    assert Conversation().derive_title() == "New chat"


# -- routing -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("fix this python traceback", Route.CODE),
        ("write a regex for postcodes", Route.CODE),
        ("```\nprint(1)\n```", Route.CODE),
        ("what should I have for dinner", Route.CHAT),
        ("summarise this paragraph", Route.CHAT),
    ],
)
def test_route_heuristic(text, expected):
    assert route_for(text) is expected


def test_unconfigured_route_falls_back_rather_than_failing(tmp_path):
    """Routing is an optimisation. One that errors when it cannot apply is worse
    than not having it."""
    model = write_model(tmp_path / "only.gguf")
    config = AppConfig(models={"chat": ModelConfig(path=str(model))})
    router = ModelRouter(config)

    assert router.resolve(Route.CODE) is Route.CHAT
    assert router.resolve(Route.CHAT) is Route.CHAT


def test_router_reports_nothing_usable_when_the_file_is_missing():
    config = AppConfig(models={"chat": ModelConfig(path="does-not-exist.gguf")})
    router = ModelRouter(config)

    assert not router.any_usable
    status = router.status(Route.CHAT)
    assert status.configured and not status.file_present
    assert status.detail == "file missing"


# -- configuration -----------------------------------------------------------


def test_autoconfigure_claims_empty_routes(tmp_path):
    # Sizes are on the scaled-down byte scale: small is under the fast-route
    # threshold (250), large is bigger but still "fits on the card" (500).
    write_model(tmp_path / "small.gguf")
    write_model(tmp_path / "large.gguf", extra=300)

    config = AppConfig()
    assert autoconfigure(config, tmp_path)
    assert config.models["chat"].path.endswith("large.gguf")
    assert config.models["fast"].path.endswith("small.gguf")


def test_autoconfigure_never_overwrites_a_chosen_model(tmp_path):
    """A default that silently undoes a deliberate choice is worse than none."""
    write_model(tmp_path / "found.gguf")
    config = AppConfig(models={"chat": ModelConfig(path="chosen.gguf")})

    autoconfigure(config, tmp_path)

    assert config.models["chat"].path == "chosen.gguf"


def test_autoconfigure_is_a_no_op_without_models(tmp_path):
    config = AppConfig()
    assert not autoconfigure(config, tmp_path)
    assert config.models == {}


def test_a_model_too_large_for_the_card_is_offloaded_partially(tmp_path, monkeypatch):
    """6 GB of VRAM. A 13 GB model has to be split, not refused."""
    big = write_model(tmp_path / "big.gguf", extra=256)
    monkeypatch.setattr("protege.core.config._FITS_ON_GPU_BYTES", 32)

    config = AppConfig()
    autoconfigure(config, tmp_path)

    assert config.models["chat"].n_gpu_layers > 0


def test_config_round_trips_through_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path))
    original = AppConfig(
        appearance="light",
        reduce_motion=True,
        models={"chat": ModelConfig(path="m.gguf", n_ctx=4096)},
    )
    original.save()

    loaded = AppConfig.load()

    assert loaded.appearance == "light"
    assert loaded.reduce_motion is True
    assert loaded.models["chat"].n_ctx == 4096


def test_a_corrupt_config_does_not_stop_startup(tmp_path, monkeypatch):
    """Losing a preference is an annoyance. Refusing to launch over it is a bug."""
    monkeypatch.setenv("PROTEGE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text("{not json at all", encoding="utf-8")

    loaded = AppConfig.load()

    assert loaded.appearance == "auto"


def test_heavy_threshold_is_below_this_machines_ram():
    """The one-heavy-model-at-a-time rule exists because of 15.7 GB total."""
    assert HEAVY_BYTES < 8 * 1024**3


# -- what counts as a model --------------------------------------------------


def test_a_file_without_the_gguf_header_is_not_discovered(tmp_path):
    """Renaming something to .gguf should not get it loaded as weights."""
    (tmp_path / "impostor.gguf").write_bytes(b"PK\x03\x04 this is a zip")
    write_model(tmp_path / "real.gguf")

    from protege.core.config import discover_models

    assert [p.name for p in discover_models(tmp_path)] == ["real.gguf"]


def test_a_barely_started_download_is_not_discovered(tmp_path, monkeypatch):
    """The size floor is the only defence against a partial file here, and it
    only catches the very beginning of one — see the note in config.py."""
    monkeypatch.setattr("protege.core.config._MIN_MODEL_BYTES", 4096)
    (tmp_path / "downloading.gguf").write_bytes(b"GGUF" + b"\x00" * 100)

    from protege.core.config import discover_models

    assert discover_models(tmp_path) == []


# -- route planning ----------------------------------------------------------
#
# The rules encode measurements taken on this machine, so these tests are as
# much a record of that decision as a check on the code.


@pytest.fixture(autouse=True)
def sizes_in_bytes(monkeypatch):
    """Scale the planner's size thresholds down from gigabytes to bytes.

    The rules are all *relative* — does this file fit on the card, is it roomier
    than that one — so shrinking every threshold by the same factor preserves
    every decision. Writing files at the real scale does not: `truncate` on NTFS
    allocates rather than sparsifying, so an earlier version of these tests put
    109 GB of placeholder models in the temp directory and took the suite from
    27 seconds to minutes.
    """
    monkeypatch.setattr("protege.core.config._MIN_MODEL_BYTES", 8)
    monkeypatch.setattr("protege.core.config._SMALL_MODEL_BYTES", 250)
    monkeypatch.setattr("protege.core.config._ROOMY_MODEL_BYTES", 450)
    monkeypatch.setattr("protege.core.config._FITS_ON_GPU_BYTES", 500)


def gguf(path, gigabytes):
    """A stand-in model whose *size in bytes* mirrors its size in gigabytes."""
    body = max(0, int(gigabytes * 100) - 4)
    path.write_bytes(b"GGUF" + bytes(body))
    return path


def test_the_code_route_prefers_a_coder(tmp_path):
    from protege.core.config import plan_routes

    chat = gguf(tmp_path / "Qwen3-8B-Q4_K_M.gguf", 4.7)
    coder = gguf(tmp_path / "Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf", 4.4)

    plan = plan_routes([coder, chat])

    assert plan["chat"].path == str(chat)
    assert plan["code"].path == str(coder)


def test_without_a_coder_the_chat_model_answers_code_too(tmp_path):
    """Worse than a dedicated coder, but not broken."""
    from protege.core.config import plan_routes

    chat = gguf(tmp_path / "Qwen3-8B-Q4_K_M.gguf", 4.7)
    plan = plan_routes([chat])

    assert plan["code"].path == plan["chat"].path


def test_a_model_that_fits_the_card_beats_a_bigger_one_that_does_not(tmp_path):
    """Fitting matters more than parameter count: spilling to host memory is
    the difference between 32 tok/s and 2."""
    from protege.core.config import plan_routes

    fits = gguf(tmp_path / "Qwen3-8B-Q4_K_M.gguf", 4.7)
    huge = gguf(tmp_path / "Mistral-Small-24B-Q4_K_M.gguf", 13.4)

    plan = plan_routes([huge, fits])

    assert plan["chat"].path == str(fits)
    assert plan["chat"].n_gpu_layers == -1


def test_the_only_model_is_used_even_if_it_does_not_fit(tmp_path):
    from protege.core.config import plan_routes

    huge = gguf(tmp_path / "Mistral-Small-24B-Q4_K_M.gguf", 13.4)
    plan = plan_routes([huge])

    assert plan["chat"].path == str(huge)
    assert plan["chat"].n_gpu_layers > 0, "a model that does not fit is split, not refused"
    assert plan["chat"].n_ctx == 4096


def test_a_roomier_model_gets_more_context(tmp_path):
    """Measured: the 4.36 GB coder holds 16K in 5700 MiB; the 4.68 GB chat
    model only holds 8K in 5800 MiB."""
    from protege.core.config import plan_routes

    roomy = gguf(tmp_path / "Small-Coder-7B.gguf", 4.4)
    tight = gguf(tmp_path / "Big-8B.gguf", 4.8)

    plan = plan_routes([roomy, tight])

    assert plan["code"].n_ctx == 16384
    assert plan["chat"].n_ctx == 8192


def test_a_coder_gets_a_lower_temperature_and_a_longer_budget(tmp_path):
    """Code wants to be reproducible more than it wants to be interesting."""
    from protege.core.config import plan_routes

    coder = gguf(tmp_path / "Qwen2.5-Coder-7B.gguf", 4.4)
    chat = gguf(tmp_path / "Qwen3-8B.gguf", 4.7)

    plan = plan_routes([coder, chat])

    assert plan["code"].temperature < plan["chat"].temperature
    assert plan["code"].max_tokens > plan["chat"].max_tokens


def test_a_small_model_claims_the_fast_route(tmp_path):
    from protege.core.config import plan_routes

    tiny = gguf(tmp_path / "Qwen3-1.7B.gguf", 1.1)
    chat = gguf(tmp_path / "Qwen3-8B.gguf", 4.7)

    plan = plan_routes([tiny, chat])

    assert plan["fast"].path == str(tiny)
    assert plan["chat"].path == str(chat)


def test_one_model_does_not_become_its_own_fast_route(tmp_path):
    """Two routes pointing at one model is not a fast path."""
    from protege.core.config import plan_routes

    only = gguf(tmp_path / "Tiny-1B.gguf", 1.0)
    plan = plan_routes([only])

    assert "fast" not in plan
    assert plan["chat"].path == str(only)


def test_planning_nothing_yields_nothing(tmp_path):
    from protege.core.config import plan_routes

    assert plan_routes([]) == {}
