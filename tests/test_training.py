"""Training an adapter (E4): the file llama.cpp loads, and the process that trains it.

The trainer itself runs in the training environment with PyTorch, so here it
is a stand-in process that prints what the real one prints. What is tested is
the GGUF adapter's layout, that the card is lent for the length of it, that
the examples do not outlive the training, that a stop keeps nothing, and that
the trainer puts the network guard up before it imports anything that could
reach out.
"""

from __future__ import annotations

import ast
import contextlib
import json
from pathlib import Path

import numpy as np
import pytest

from akira.core.making import training
from akira.core.making.training import Trainer, TrainingError, examples_from
from akira.training.lora_gguf import AdapterError, gguf_name, read_header, write


# -- the adapter file ----------------------------------------------------------------------------


def peft_pair(layer, part, rank=4, inputs=16, outputs=8):
    prefix = f"base_model.model.model.layers.{layer}.{part}"
    a = np.arange(rank * inputs, dtype=np.float32).reshape(rank, inputs)
    b = np.arange(outputs * rank, dtype=np.float32).reshape(outputs, rank) / 10
    return [(f"{prefix}.lora_A.weight", a), (f"{prefix}.lora_B.weight", b)]


@pytest.mark.parametrize("peft, gguf", [
    ("base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight", "blk.0.attn_q.weight.lora_a"),
    ("base_model.model.model.layers.35.mlp.down_proj.lora_B.weight", "blk.35.ffn_down.weight.lora_b"),
    ("base_model.model.model.layers.2.self_attn.o_proj.lora_B.default.weight",
     "blk.2.attn_output.weight.lora_b"),
])
def test_peft_names_become_the_names_llama_cpp_looks_for(peft, gguf):
    assert gguf_name(peft) == gguf


def test_a_weight_llama_cpp_would_not_find_is_refused():
    with pytest.raises(AdapterError, match="would not find"):
        gguf_name("base_model.model.model.layers.0.self_attn.rotary.lora_A.weight")
    with pytest.raises(AdapterError):
        gguf_name("base_model.model.lm_head.weight")


def test_an_adapter_is_written_as_llama_cpp_reads_it(tmp_path):
    pairs = peft_pair(0, "self_attn.q_proj") + peft_pair(1, "mlp.up_proj", outputs=32)
    path = tmp_path / "adapter.gguf"
    assert write(path, pairs, architecture="qwen3", alpha=8, name="garden") == 4
    header = read_header(path)
    assert header["version"] == 3
    assert header["metadata"] == {"general.architecture": "qwen3", "general.type": "adapter",
                                  "adapter.type": "lora", "adapter.lora.alpha": 8.0,
                                  "general.alignment": 32, "general.name": "garden"}
    tensors = header["tensors"]
    # PEFT's lora_A is rank by inputs: fastest first, that is [inputs, rank].
    assert tensors["blk.0.attn_q.weight.lora_a"]["ne"] == [16, 4]
    assert tensors["blk.0.attn_q.weight.lora_b"]["ne"] == [4, 8]
    assert tensors["blk.1.ffn_up.weight.lora_b"]["ne"] == [4, 32]
    data = path.read_bytes()
    for name, (_, array) in zip(sorted(tensors), sorted(
            ((gguf_name(n), a) for n, a in pairs), key=lambda item: item[0])):
        start = header["data_start"] + tensors[name]["offset"]
        assert start % 32 == 0
        stored = np.frombuffer(data[start:start + array.nbytes], dtype=np.float32)
        assert np.array_equal(stored, array.ravel()), name
    assert not (tmp_path / "adapter.gguf.part").exists()


def test_an_unpaired_or_mismatched_adapter_is_refused(tmp_path):
    a_only = peft_pair(0, "self_attn.q_proj")[:1]
    with pytest.raises(AdapterError, match="no matching lora_b"):
        write(tmp_path / "x.gguf", a_only, architecture="qwen3", alpha=8)
    (a_name, a), (b_name, b) = peft_pair(0, "self_attn.q_proj")
    with pytest.raises(AdapterError, match="same rank"):
        write(tmp_path / "x.gguf", [(a_name, a), (b_name, b[:, :2])], architecture="qwen3",
              alpha=8)
    with pytest.raises(AdapterError, match="no LoRA weights"):
        write(tmp_path / "x.gguf", [], architecture="qwen3", alpha=8)


# -- the examples --------------------------------------------------------------------------------


def test_examples_keep_the_conversation_and_drop_what_teaches_nothing():
    made = examples_from([
        [("system", "be nice"), ("user", "Hi"), ("assistant", "Hello! "), ("user", "Bye"),
         ("assistant", "")],
        [("user", "Only a question")],
        [("assistant", "Talking first"), ("user", "Hm")],
    ])
    assert made == [{"messages": [{"role": "user", "content": "Hi"},
                                  {"role": "assistant", "content": "Hello!"},
                                  {"role": "user", "content": "Bye"}]}]


# -- running the trainer -------------------------------------------------------------------------


@pytest.fixture
def in_place(tmp_path, monkeypatch):
    train = tmp_path / "train"
    for path in ("env/Scripts/python.exe", "Qwen3-4B/config.json", "Qwen3-4B-Q4_K_M.gguf"):
        (train / path).parent.mkdir(parents=True, exist_ok=True)
        (train / path).write_bytes(b"x")
    monkeypatch.setattr(training, "PYTHON", train / "env" / "Scripts" / "python.exe")
    monkeypatch.setattr(training, "BASE", train / "Qwen3-4B")
    monkeypatch.setattr(training, "RUNNER", train / "Qwen3-4B-Q4_K_M.gguf")
    monkeypatch.setattr(training, "ADAPTERS", train / "adapters")
    return train


class FakeProcess:
    def __init__(self, lines, code=0, before=None):
        self._lines, self._code, self._before = lines, code, before
        self.killed = False

    @property
    def stdout(self):
        for line in self._lines:
            if callable(line):
                line = line()
                if line is None:
                    continue
            yield (json.dumps(line) + "\n").encode()

    def wait(self, timeout=None):
        return self._code

    def kill(self):
        self.killed = True


def conversations(n=6):
    return examples_from([[("user", f"Question {i}"), ("assistant", f"Answer {i}")]
                          for i in range(n)])


def run(trainer, name="garden notes", examples=None, **options):
    progress, done = [], []
    trainer.start(name, conversations() if examples is None else examples,
                  on_progress=progress.append, on_done=lambda why, made: done.append((why, made)),
                  **options)
    trainer._thread.join(10)
    return progress, done


def test_a_training_lends_the_card_and_keeps_the_adapter_not_the_examples(in_place):
    lent, seen = [], {}

    @contextlib.contextmanager
    def set_aside(timeout, lent_for):
        lent.append(lent_for)
        yield

    def popen(arguments, **options):
        seen.update(arguments=arguments, options=options)
        folder = Path(json.loads(Path(arguments[3]).read_text())["out"])
        seen["examples"] = (folder / "examples.jsonl").read_text(encoding="utf-8")

        def made():
            (folder / "adapter.gguf").write_bytes(b"GGUF")
            return {"done": True, "gguf": str(folder / "adapter.gguf"), "seconds": 12.5}

        return FakeProcess([{"stage": "loading"},
                            {"stage": "training", "step": 1, "steps": 3, "loss": 2.1},
                            {"stage": "training", "step": 3, "steps": 3, "loss": 1.4}, made])

    progress, done = run(Trainer(set_aside=set_aside, popen=popen))
    [(why, adapter)] = done
    assert why == "" and adapter.name == "garden notes" and adapter.steps == 3
    assert adapter.loss == 1.4 and adapter.examples == 6
    assert lent and "garden notes" in lent[0], "the card was not lent"
    arguments = seen["arguments"]
    assert arguments[0].endswith("python.exe") and arguments[1] == "-I"
    assert arguments[2].endswith("_trainer.py")
    assert seen["options"]["env"]["HF_HUB_OFFLINE"] == "1"
    assert not any(key.upper().startswith("PYTHON") for key in seen["options"]["env"])
    assert seen["examples"].count("\n") == 6
    folder = Path(adapter.folder)
    assert not (folder / "examples.jsonl").exists(), "the conversations outlived the training"
    assert [a.name for a in training.adapters()] == ["garden notes"]
    assert [u.get("stage") for u in progress][:2] == ["loading", "training"]


def test_a_failed_training_keeps_nothing_and_says_why(in_place):
    def popen(arguments, **options):
        return FakeProcess([{"stage": "loading"},
                            {"error": "PyTorch cannot see the graphics card, so training "
                                      "cannot run."}], code=1)

    _, done = run(Trainer(popen=popen))
    [(why, adapter)] = done
    assert "cannot see the graphics card" in why and adapter is None
    assert not any((in_place / "adapters").iterdir())


def test_stopping_keeps_nothing(in_place):
    trainer = Trainer()

    def popen(arguments, **options):
        return FakeProcess([{"stage": "training", "step": 1, "steps": 9, "loss": 2.0},
                            lambda: trainer.stop(), {"stopped": True}], code=2)

    trainer._popen = popen
    _, done = run(trainer)
    [(why, adapter)] = done
    assert "stopped" in why and adapter is None
    assert not any((in_place / "adapters").iterdir())


@pytest.mark.parametrize("name, examples, options, why", [
    ("", None, {}, "Name the adapter"),
    ("../escape", None, {}, "Name the adapter"),
    ("fine", [], {}, "Choose from"),
    ("fine", None, {"epochs": 9}, "1 to 5"),
    ("fine", None, {"rank": 12}, "rank 8, 16 or 32"),
])
def test_what_cannot_be_trained_is_refused_before_anything_runs(in_place, name, examples,
                                                                   options, why):
    ran = []
    trainer = Trainer(popen=lambda *a, **k: ran.append(a))
    with pytest.raises(TrainingError, match=why):
        trainer.start(name, conversations() if examples is None else examples, **options)
    assert ran == []


def test_one_training_at_a_time_and_names_are_not_reused(in_place):
    def popen(arguments, **options):
        folder = Path(json.loads(Path(arguments[3]).read_text())["out"])
        (folder / "adapter.gguf").write_bytes(b"GGUF")
        return FakeProcess([{"done": True, "gguf": str(folder / "adapter.gguf")}])

    run(Trainer(popen=popen))
    with pytest.raises(TrainingError, match="already an adapter"):
        Trainer(popen=popen).start("garden notes", conversations())


# -- the trainer's own rules ---------------------------------------------------------------------


def test_the_trainer_puts_the_guard_up_before_it_imports_anything_that_reaches_out():
    source = Path(training.TRAINER).read_text(encoding="utf-8")
    main = next(node for node in ast.walk(ast.parse(source))
                if isinstance(node, ast.FunctionDef) and node.name == "main")
    order = []
    for node in ast.walk(main):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "install":
            order.append(("guard", node.lineno))
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names]
            module = getattr(node, "module", None) or names[0]
            if module.split(".")[0] in ("torch", "transformers", "peft", "safetensors",
                                        "bitsandbytes", "accelerate", "huggingface_hub"):
                order.append(("library", node.lineno))
    guard = min(line for kind, line in order if kind == "guard")
    assert all(line > guard for kind, line in order if kind == "library")
    assert "local_files_only=True" in source and "HF_HUB_OFFLINE" in source
    # Nothing at the top of the file brings a library in before the guard.
    tree = ast.parse(source)
    top = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import)
           for alias in node.names}
    assert not top & {"torch", "transformers", "peft", "huggingface_hub"}


def test_akira_itself_never_imports_the_trainer():
    root = Path(training.REPO_ROOT) / "akira"
    for path in root.rglob("*.py"):
        if "training" in path.relative_to(root).parts[:1]:
            continue
        text = path.read_text(encoding="utf-8")
        assert "akira.training._trainer" not in text and "from akira.training import _trainer" \
            not in text, path
