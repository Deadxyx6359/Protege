#!/usr/bin/env python3
"""Measure what a model actually costs on this machine.

    python tools/bench_model.py models/Qwen3-8B-Q4_K_M.gguf --ctx 8192
    python tools/bench_model.py models/X.gguf --ctx 4096 8192 16384

Reports VRAM after load, prompt-processing and generation speed. Written
because the arithmetic for "will a 4.7 GB model plus its KV cache fit in 6 GB"
is close enough to the limit that estimating it is not good enough — the README
already records one case where the intuitive answer (offload fewer layers to
save memory) was exactly backwards.

A configuration that does not fit does not fail cleanly: llama.cpp either
spills to host memory and runs at a fraction of the speed, or the allocation
fails partway through. Both are worth finding here rather than mid-answer.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PROMPT = (
    "Explain, in about eighty words, why a continuous-curvature corner looks "
    "smoother than a circular one."
)


def vram_used_mib() -> int | None:
    """VRAM in use on the dGPU, straight from nvidia-smi.

    Read from the driver rather than from llama.cpp's own accounting: the
    question is what the card is actually holding, including the CUDA context
    and the compute buffers, not what the weights nominally weigh.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.stdout.strip().splitlines()
    return int(first[0]) if first else None


def bench(path: Path, n_ctx: int, n_gpu_layers: int, max_tokens: int) -> dict:
    from protege.models.base import ChatMessage, ModelSpec, Role
    from protege.models.llama_backend import LlamaBackend

    baseline = vram_used_mib()

    spec = ModelSpec(path=str(path), role=Role.MAIN, n_ctx=n_ctx, n_gpu_layers=n_gpu_layers)

    # The constructor loads the weights, so the timer has to wrap it. Timing a
    # later call instead measures nothing and reports a load time of 0.0s.
    load_start = time.monotonic()
    backend = LlamaBackend(spec)
    backend.count_tokens("warm")
    load_s = time.monotonic() - load_start

    after_load = vram_used_mib()

    first_token: list[float] = []
    start = time.monotonic()

    def on_token(_chunk: str) -> None:
        if not first_token:
            first_token.append(time.monotonic() - start)

    result = backend.generate(
        [ChatMessage(role="user", content=PROMPT)],
        max_tokens=max_tokens,
        temperature=0.7,
        on_token=on_token,
    )
    elapsed = time.monotonic() - start
    peak = vram_used_mib()
    backend.close()

    completion = result.completion_tokens or max(1, len(result.text) // 4)
    return {
        "ctx": n_ctx,
        "gpu_layers": n_gpu_layers,
        "load_s": load_s,
        "vram_load": None if after_load is None or baseline is None else after_load - baseline,
        "vram_peak": None if peak is None or baseline is None else peak - baseline,
        "ttft_s": first_token[0] if first_token else float("nan"),
        "tok_s": completion / elapsed if elapsed else 0.0,
        "tokens": completion,
        "text": result.text.strip(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench_model", description=__doc__)
    parser.add_argument("model", help="path to a .gguf")
    parser.add_argument("--ctx", type=int, nargs="+", default=[8192],
                        help="context sizes to try (default: 8192)")
    parser.add_argument("--gpu-layers", type=int, default=-1,
                        help="-1 offloads everything (default)")
    parser.add_argument("--max-tokens", type=int, default=120)
    parser.add_argument("--show", action="store_true", help="print the reply")
    args = parser.parse_args(argv)

    path = Path(args.model)
    if not path.is_file():
        print(f"no such model: {path}", file=sys.stderr)
        return 2

    total = vram_used_mib()
    print(f"model      {path.name}  ({path.stat().st_size / 1024**3:.2f} GB)")
    print(f"gpu layers {args.gpu_layers}")
    if total is not None:
        print(f"vram in use before starting: {total} MiB")
    print()
    print(f"{'ctx':>7}  {'load':>6}  {'vram':>9}  {'peak':>9}  {'ttft':>7}  {'tok/s':>7}")
    print("-" * 56)

    for n_ctx in args.ctx:
        try:
            row = bench(path, n_ctx, args.gpu_layers, args.max_tokens)
        except Exception as exc:  # noqa: BLE001 - report and continue to the next size
            print(f"{n_ctx:>7}  failed: {type(exc).__name__}: {exc}")
            continue

        vram = "—" if row["vram_load"] is None else f"{row['vram_load']} MiB"
        peak = "—" if row["vram_peak"] is None else f"{row['vram_peak']} MiB"
        print(
            f"{row['ctx']:>7}  {row['load_s']:>5.1f}s  {vram:>9}  {peak:>9}  "
            f"{row['ttft_s']:>6.2f}s  {row['tok_s']:>7.1f}"
        )
        if args.show:
            print(f"\n{row['text']}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
