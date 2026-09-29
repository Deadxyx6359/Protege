#!/usr/bin/env python3
"""Train a behaviour adapter for Qwen3-4B from `behaviour_examples`, with Akira's own trainer.

    python tools/train_behaviour.py NAME [--epochs 2] [--rank 16]

It runs exactly as the Training screen does (`akira.core.making.training`):
the same environment, the same QLoRA settings, the same place for adapters,
so the result appears in Settings to switch on. Progress is printed as it
comes; the card is busy until it ends.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from akira.core.making.training import Trainer, TrainingError  # noqa: E402
from behaviour_examples import build  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("name")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--rank", type=int, default=16)
    args = parser.parse_args(argv)

    examples = build()
    finished = threading.Event()
    outcome: dict = {}
    started = time.time()

    def progress(update: dict) -> None:
        if update.get("stage") == "training" and "step" in update:
            print(f"step {update['step']}/{update.get('steps', '?')}  epoch "
                  f"{update.get('epoch', '?')}  loss {update.get('loss', 0):.3f}  "
                  f"{time.time() - started:.0f}s", flush=True)
        elif update.get("stage"):
            print(f"{update['stage']}", flush=True)

    def done(why: str, adapter) -> None:
        outcome["why"], outcome["adapter"] = why, adapter
        finished.set()

    try:
        Trainer().start(args.name, examples, epochs=args.epochs, rank=args.rank,
                        on_progress=progress, on_done=done)
    except TrainingError as exc:
        print(f"could not start: {exc}")
        return 1
    finished.wait()
    if outcome["why"]:
        print(f"failed: {outcome['why']}")
        return 1
    adapter = outcome["adapter"]
    print(json.dumps({"adapter": adapter.gguf, "model": adapter.model, "steps": adapter.steps,
                      "loss": adapter.loss, "seconds": round(adapter.seconds)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
