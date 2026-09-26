"""A LoRA adapter, written as the GGUF file llama.cpp loads beside its model.

GGUF is a small format: a header, key-value metadata, a table of tensors, then
their data, each aligned to 32 bytes. An adapter is a GGUF file whose
`general.type` is `adapter`, whose `adapter.type` is `lora`, whose architecture
is the base model's, and whose tensors are pairs named after the model tensor
they adjust: `blk.3.attn_q.weight.lora_a` and `.lora_b`.

PEFT keeps `lora_A` as rank by inputs and `lora_B` as outputs by rank. GGUF
lists dimensions fastest first, so written as they are those become [inputs,
rank] and [rank, outputs], which is what llama.cpp checks against the model's
[inputs, outputs]. Written in 32-bit floats: an adapter is small.

Only NumPy is needed, so this runs in either Python.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Iterable

import numpy as np

ALIGNMENT = 32

_STRING, _UINT32, _FLOAT32 = 8, 4, 6
_F32 = 0

#: Hugging Face's names for a Qwen3 (and Llama-style) layer's weights, as GGUF names them.
_PARTS = {
    "self_attn.q_proj": "attn_q",
    "self_attn.k_proj": "attn_k",
    "self_attn.v_proj": "attn_v",
    "self_attn.o_proj": "attn_output",
    "mlp.gate_proj": "ffn_gate",
    "mlp.up_proj": "ffn_up",
    "mlp.down_proj": "ffn_down",
}

_PEFT = re.compile(r"(?:^|\.)layers\.(\d+)\.(.+?)\.lora_([AB])(?:\.[^.]+)?\.weight$")


class AdapterError(ValueError):
    """Why an adapter could not be written."""


def gguf_name(peft_name: str) -> str:
    """The GGUF tensor name for one of PEFT's LoRA weights."""
    found = _PEFT.search(peft_name)
    if found is None:
        raise AdapterError(f"{peft_name} is not a LoRA weight of a transformer layer.")
    layer, part, which = found.groups()
    if part not in _PARTS:
        raise AdapterError(f"{peft_name} adjusts {part}, which llama.cpp would not find.")
    return f"blk.{layer}.{_PARTS[part]}.weight.lora_{which.lower()}"


def _string(text: str) -> bytes:
    data = text.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _pad(size: int) -> int:
    return (ALIGNMENT - size % ALIGNMENT) % ALIGNMENT


def write(path: Path, tensors: Iterable[tuple[str, np.ndarray]], *, architecture: str,
          alpha: float, name: str = "") -> int:
    """Write the adapter \a tensors (PEFT names and arrays) to \a path. Returns how many.

    Every `lora_A` must have its `lora_B`, with ranks that agree.
    """
    named: dict[str, np.ndarray] = {}
    for peft_name, array in tensors:
        named[gguf_name(peft_name)] = np.ascontiguousarray(np.asarray(array, dtype=np.float32))
    if not named:
        raise AdapterError("There are no LoRA weights to write.")
    for key, a in named.items():
        if key.endswith(".lora_a"):
            b = named.get(key[:-1] + "b")
            if b is None or a.ndim != 2 or b.ndim != 2 or a.shape[0] != b.shape[1]:
                raise AdapterError(f"{key[:-7]} has no matching lora_b of the same rank.")
    if any(key.endswith(".lora_b") and key[:-1] + "a" not in named for key in named):
        raise AdapterError("A lora_b has no lora_a.")

    metadata = [("general.architecture", _STRING, architecture),
                ("general.type", _STRING, "adapter"),
                ("adapter.type", _STRING, "lora"),
                ("adapter.lora.alpha", _FLOAT32, float(alpha)),
                ("general.alignment", _UINT32, ALIGNMENT)]
    if name:
        metadata.append(("general.name", _STRING, name))

    header = bytearray(b"GGUF")
    header += struct.pack("<IQQ", 3, len(named), len(metadata))
    for key, kind, value in metadata:
        header += _string(key) + struct.pack("<I", kind)
        if kind == _STRING:
            header += _string(value)
        elif kind == _UINT32:
            header += struct.pack("<I", value)
        else:
            header += struct.pack("<f", value)

    offset = 0
    order = sorted(named)
    for key in order:
        array = named[key]
        header += _string(key) + struct.pack("<I", array.ndim)
        # Fastest-changing dimension first.
        for size in reversed(array.shape):
            header += struct.pack("<Q", size)
        header += struct.pack("<IQ", _F32, offset)
        offset += array.nbytes + _pad(array.nbytes)

    path = Path(path)
    part = path.with_name(path.name + ".part")
    with part.open("wb") as stream:
        stream.write(header)
        stream.write(b"\x00" * _pad(len(header)))
        for key in order:
            data = named[key].tobytes()
            stream.write(data)
            stream.write(b"\x00" * _pad(len(data)))
    part.replace(path)
    return len(order)


def read_header(path: Path) -> dict:
    """The metadata and tensor table of a GGUF file: for checking what was written."""
    data = Path(path).read_bytes()
    if data[:4] != b"GGUF":
        raise AdapterError("Not a GGUF file.")
    version, count, kv_count = struct.unpack_from("<IQQ", data, 4)
    at = 24

    def text() -> str:
        nonlocal at
        (size,) = struct.unpack_from("<Q", data, at)
        at += 8
        value = data[at:at + size].decode("utf-8")
        at += size
        return value

    metadata = {}
    for _ in range(kv_count):
        key = text()
        (kind,) = struct.unpack_from("<I", data, at)
        at += 4
        if kind == _STRING:
            metadata[key] = text()
        elif kind == _UINT32:
            (metadata[key],) = struct.unpack_from("<I", data, at)
            at += 4
        elif kind == _FLOAT32:
            (metadata[key],) = struct.unpack_from("<f", data, at)
            at += 4
        else:
            raise AdapterError(f"Unexpected metadata type {kind}.")
    tensors = {}
    for _ in range(count):
        key = text()
        (dims,) = struct.unpack_from("<I", data, at)
        at += 4
        shape = struct.unpack_from(f"<{dims}Q", data, at)
        at += 8 * dims
        kind, offset = struct.unpack_from("<IQ", data, at)
        at += 12
        tensors[key] = {"ne": list(shape), "type": kind, "offset": offset}
    return {"version": version, "metadata": metadata, "tensors": tensors,
            "data_start": at + _pad(at)}
