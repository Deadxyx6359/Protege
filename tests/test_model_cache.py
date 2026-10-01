"""A model on the graphics card is loaded with flash attention and an 8-bit context cache.

On a 6 GB card the 8B model with a 16-bit cache took 5.96 GB, and anything else on
the card pushed part of it into ordinary memory: answers came at half a word a
second. With these it takes 5.47 GB, at the same speed. A build or a model that
cannot is loaded as before rather than not at all. llama.cpp is faked here.
"""

from __future__ import annotations

import pytest

from akira.models import llama_backend
from akira.models.base import ModelSpec, Role


class FakeLlama:
    made: list[dict] = []
    refuse = False

    def __init__(self, **kwargs):
        if self.refuse and "flash_attn" in kwargs:
            raise ValueError("flash attention is not supported here")
        FakeLlama.made.append(kwargs)

    def close(self):
        pass


@pytest.fixture
def fake(monkeypatch, tmp_path):
    FakeLlama.made = []
    FakeLlama.refuse = False
    monkeypatch.setattr(llama_backend.llama_cpp, "Llama", FakeLlama)
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    return model


def load(model, layers=-1):
    return llama_backend.LlamaBackend(ModelSpec(path=str(model), role=Role.MAIN, n_ctx=8192,
                                                n_gpu_layers=layers))


def test_on_the_card_the_cache_is_smaller(fake):
    load(fake)
    (made,) = FakeLlama.made
    assert made["flash_attn"] is True
    assert made["type_k"] == made["type_v"] == llama_backend.llama_cpp.GGML_TYPE_Q8_0
    assert made["n_ctx"] == 8192 and made["n_gpu_layers"] == -1


def test_on_the_processor_alone_nothing_changes(fake):
    load(fake, layers=0)
    (made,) = FakeLlama.made
    assert not {"flash_attn", "type_k", "type_v"} & set(made)


def test_a_model_that_cannot_is_loaded_as_before(fake):
    FakeLlama.refuse = True
    load(fake)
    (made,) = FakeLlama.made
    assert not {"flash_attn", "type_k", "type_v"} & set(made)
