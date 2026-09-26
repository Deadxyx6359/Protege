"""Train a LoRA adapter (E4). Run only by the training environment's Python:

    models/train/env/Scripts/python.exe -I akira/training/_trainer.py <job.json>

Before anything else, Akira's network guard goes up and every Hugging Face
library is told it is offline. Only then are PyTorch, transformers, PEFT and
bitsandbytes imported: they carry a model downloader, and this is how it can
never be used. `verify_offline.py` checks that the guard comes first.

The base model is read from its folder and loaded in 4 bits (QLoRA); a LoRA of
the job's rank is trained on the examples, a conversation per line, learning
only the assistant's words. Progress is written to stdout as one JSON object a
line. At the end the adapter is saved as PEFT's files and as the GGUF adapter
llama.cpp loads beside the quantised model. Creating the job's stop file stops
the training between steps, and nothing is saved.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

OFFLINE = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
    "TOKENIZERS_PARALLELISM": "false",
}

#: The layers a LoRA adjusts: every projection in attention and the MLP.
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def say(**fields) -> None:
    print(json.dumps(fields), flush=True)


def examples(path: Path, tokenizer, longest: int):
    """Each conversation as token ids, with labels on the assistant's words only."""
    import torch

    made = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        messages = json.loads(line)["messages"]
        ids: list[int] = []
        labels: list[int] = []
        for index, message in enumerate(messages):
            if message["role"] != "assistant":
                continue
            prompt = tokenizer.apply_chat_template(messages[:index], tokenize=False,
                                                   add_generation_prompt=True,
                                                   enable_thinking=False)
            whole = prompt + message["content"] + "<|im_end|>\n"
            prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
            whole_ids = tokenizer(whole, add_special_tokens=False)["input_ids"]
            # Everything before this reply is context: it is not learned, only read.
            ids = whole_ids
            labels = [-100] * len(prompt_ids) + whole_ids[len(prompt_ids):]
        if not ids:
            continue
        ids, labels = ids[-longest:], labels[-longest:]
        if all(label == -100 for label in labels):
            continue
        made.append((torch.tensor([ids]), torch.tensor([labels])))
    return made


def main(argv: list[str]) -> int:
    repo = Path(__file__).resolve().parents[2]
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    # 1. The guard, before any library that could reach out is even imported.
    from akira.security import netguard

    netguard.install()
    os.environ.update(OFFLINE)

    job = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    out = Path(job["out"])
    stop = Path(job["stop_file"])

    # 2. Only now the libraries.
    say(stage="loading")
    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    if not torch.cuda.is_available():
        say(error="PyTorch cannot see the graphics card, so training cannot run.")
        return 1
    base = job["base"]
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(
        base, local_files_only=True, device_map={"": 0}, dtype=torch.bfloat16,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16))
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False})
    rank, alpha = int(job["rank"]), float(job["alpha"])
    model = get_peft_model(model, LoraConfig(r=rank, lora_alpha=alpha, lora_dropout=0.05,
                                             target_modules=TARGETS, task_type="CAUSAL_LM"))

    data = examples(Path(job["examples"]), tokenizer, int(job["longest"]))
    if not data:
        say(error="None of the examples had a reply to learn from.")
        return 1
    epochs, accumulate = int(job["epochs"]), int(job["accumulate"])
    steps = math.ceil(len(data) * epochs / accumulate)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                                  lr=float(job["learning_rate"]), weight_decay=0.0)
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer, lambda step: min(1.0, (step + 1) / 10) * max(0.0, 1 - step / max(1, steps)))
    say(stage="training", examples=len(data), steps=steps)

    model.train()
    started, step, seen, total = time.monotonic(), 0, 0, 0.0
    for epoch in range(epochs):
        order = torch.randperm(len(data), generator=torch.Generator().manual_seed(epoch)).tolist()
        for index in order:
            if stop.exists():
                say(stopped=True)
                return 2
            ids, labels = data[index]
            loss = model(input_ids=ids.to(0), labels=labels.to(0)).loss / accumulate
            loss.backward()
            total += float(loss.detach()) * accumulate
            seen += 1
            if seen % accumulate == 0 or seen == len(data) * epochs:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)
                step += 1
                say(stage="training", step=step, steps=steps, epoch=epoch + 1,
                    loss=round(total / accumulate, 4),
                    seconds=round(time.monotonic() - started, 1))
                total = 0.0

    say(stage="saving")
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out / "peft"))
    from safetensors.numpy import load_file

    from akira.training.lora_gguf import write

    weights = load_file(str(out / "peft" / "adapter_model.safetensors"))
    written = write(out / "adapter.gguf", weights.items(),
                    architecture=str(job.get("architecture") or "qwen3"), alpha=alpha,
                    name=str(job.get("name") or "adapter"))
    say(done=True, tensors=written, gguf=str(out / "adapter.gguf"),
        seconds=round(time.monotonic() - started, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
