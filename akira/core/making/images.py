"""Pictures (E1): SDXL-Turbo, through stable-diffusion.cpp, on the graphics card.

`sd-cli.exe` (stable-diffusion.cpp, the Vulkan build) is a program of its own,
run with a fixed list of arguments and nothing else. Like the browser, it is out
of the sight of Akira's network guard, so what holds it is what it is given: a
model file, the VAE, a prompt in a file, a size, a seed and where to write the
picture. It is never given `--rpc-servers`, its one way of reaching another
machine, and the server that ships beside it was deleted. The firewall rule in
the README covers it too.

SDXL-Turbo in half precision is 6.9 GB, more than the card holds with anything
else on it, so `prepare` turns it once into an 8-bit copy of about 4 GB, which
`sd-cli` itself does. While a picture is made the language models are set
aside (`ModelRouter.set_aside`): the card is the picture's for those seconds,
and the next answer loads its model again.

The prompt is the person's, or an agent's. It is written to a file for
`sd-cli` to read, so no part of it is ever read as an argument. Nothing about a
picture is kept here: it is handed back as PNG bytes and the working folder is
removed.
"""

from __future__ import annotations

import contextlib
import random
import re
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager

from akira.core.config import MODELS_DIR

IMAGE_DIR = MODELS_DIR / "image"
PROGRAM = IMAGE_DIR / "bin" / "sd-cli.exe"
SDXL = IMAGE_DIR / "sd_xl_turbo_1.0_fp16.safetensors"
VAE = IMAGE_DIR / "sdxl_vae.safetensors"
#: The 8-bit copy `prepare` makes, which fits the card.
QUANTIZED = IMAGE_DIR / "sd_xl_turbo_1.0.q8_0.gguf"

#: Sizes a picture may be. SDXL-Turbo was trained at 512 by 512; it does a little
#: either side, in steps of 64.
SIDES = tuple(range(384, 1025, 64))

#: SDXL-Turbo makes a picture in one to four steps.
MAX_STEPS = 8

MAX_PROMPT = 1_000

#: How long one picture may take, and making the 8-bit copy.
PICTURE_S = 300
PREPARE_S = 1_800

#: The arguments `sd-cli` may be given, and no others.
ALLOWED_FLAGS = frozenset({"-M", "-m", "--vae", "--prompt-file", "--negative-prompt-file",
                           "-W", "-H", "--steps", "--cfg-scale", "--sampling-method", "-s",
                           "-o", "--type", "--vae-tiling", "--diffusion-fa", "-t", "--backend",
                           "--list-devices"})

#: What a discrete graphics card calls itself. A laptop has an integrated one
#: too, listed first, which would be far slower and borrow the computer's memory.
_DISCRETE = re.compile(r"nvidia|geforce|rtx|gtx|radeon rx|arc a", re.IGNORECASE)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ImageError(Exception):
    """Why a picture cannot be made, said so a person, or an agent, can act on it."""


@dataclass(frozen=True)
class Picture:
    png: bytes
    prompt: str
    width: int
    height: int
    steps: int
    seed: int
    seconds: float


def unavailable() -> str:
    """Why pictures cannot be made on this computer at all, or ""."""
    gone = [path for path in (PROGRAM, VAE) if not path.is_file()]
    if not (QUANTIZED.is_file() or SDXL.is_file()):
        gone.append(SDXL)
    if gone:
        names = ", ".join(str(path.relative_to(MODELS_DIR.parent)) for path in gone)
        return f"The picture files are not in place: {names}."
    return ""


def clean_prompt(text: str) -> str:
    """\a text as a prompt: one line, no control characters, at most `MAX_PROMPT` long."""
    text = " ".join(_CONTROL.sub(" ", str(text or "")).split())
    if not text:
        raise ImageError("Say what the picture should show.")
    if len(text) > MAX_PROMPT:
        raise ImageError(f"A prompt is at most {MAX_PROMPT:,} characters.")
    return text


def check_size(width: int, height: int, steps: int) -> None:
    if int(width) not in SIDES or int(height) not in SIDES:
        raise ImageError(f"Each side is from {SIDES[0]} to {SIDES[-1]} pixels, in steps of 64; "
                         "512 by 512 is what the model does best.")
    if not 1 <= int(steps) <= MAX_STEPS:
        raise ImageError(f"SDXL-Turbo takes 1 to {MAX_STEPS} steps; 4 is plenty.")


def command(model: Path, prompt_file: Path, negative_file: Path, out: Path, *, width: int,
            height: int, steps: int, seed: int, device: str = "") -> list[str]:
    """What `sd-cli` is run with to make one picture. Only `ALLOWED_FLAGS` appear."""
    arguments = [str(PROGRAM), "-m", str(model), "--vae", str(VAE),
                 "--prompt-file", str(prompt_file), "--negative-prompt-file", str(negative_file),
                 "-W", str(width), "-H", str(height), "--steps", str(steps),
                 # Turbo is trained without guidance: 1.0 turns it off.
                 "--cfg-scale", "1.0", "--sampling-method", "euler_a", "-s", str(seed),
                 "-o", str(out), "--vae-tiling", "--diffusion-fa"]
    if device:
        arguments += ["--backend", device]
    return arguments


def pick_device(listed: str) -> str:
    """The device to draw on, from what `sd-cli --list-devices` printed: the
    discrete graphics card, or "" to leave the choice to sd-cli."""
    names = []
    for line in listed.splitlines():
        name, _, description = line.partition("\t")
        if name.strip() and description.strip():
            names.append((name.strip(), description.strip()))
    for name, description in names:
        if _DISCRETE.search(description) and re.fullmatch(r"[A-Za-z]+\d*", name):
            return name
    return ""


def _flags(arguments: list[str]) -> set[str]:
    return {part for part in arguments[1:] if part.startswith("-") and not part[1:2].isdigit()}


#: How the language models are set aside while a picture is made: the shell hands
#: in `ModelRouter.set_aside` once (`lend_card`), so a tool can make a picture
#: without knowing about the router.
_SET_ASIDE: Callable[[], ContextManager[Any]] = contextlib.nullcontext

#: One picture at a time, whoever asks.
_ONE_AT_A_TIME = threading.Lock()


def lend_card(set_aside: Callable[[], ContextManager[Any]]) -> None:
    """Have every picture made set the language models aside with \a set_aside."""
    global _SET_ASIDE
    _SET_ASIDE = set_aside


class ImageMaker:
    """Makes pictures, one at a time, with the graphics card to itself."""

    def __init__(self, set_aside: Callable[[], ContextManager[Any]] | None = None,
                 run: Callable[..., Any] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._set_aside = set_aside
        self._run = run if run is not None else subprocess.run
        self._clock = clock
        self._device: str | None = None

    @property
    def prepared(self) -> bool:
        return QUANTIZED.is_file()

    def device(self) -> str:
        """The discrete graphics card, asked of sd-cli once, or "" if there is none."""
        if self._device is None:
            try:
                listed = self._launch([str(PROGRAM), "--list-devices"], 60, IMAGE_DIR)
                output = listed.stdout
                if isinstance(output, bytes):
                    output = output.decode("utf-8", "replace")
                self._device = pick_device(str(output or ""))
            except ImageError:
                self._device = ""
        return self._device

    def _launch(self, arguments: list[str], timeout: float, cwd: Path) -> Any:
        stray = _flags(arguments) - ALLOWED_FLAGS
        if stray:
            raise ImageError(f"sd-cli was about to be given {sorted(stray)}, which it never is.")
        try:
            return self._run(arguments, capture_output=True, timeout=timeout, cwd=str(cwd),
                             stdin=subprocess.DEVNULL,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired:
            raise ImageError("Making the picture took too long, so it was stopped.") from None
        except OSError as exc:
            raise ImageError(f"sd-cli could not be started: {exc}") from None

    def prepare(self) -> None:
        """Make the 8-bit copy of SDXL-Turbo that fits the card, once. Slow: minutes."""
        if self.prepared:
            return
        problem = unavailable()
        if problem:
            raise ImageError(problem)
        # Named .gguf, since the extension may say what to write.
        part = QUANTIZED.with_name(QUANTIZED.stem + ".part.gguf")
        # Once more if it fails: reading 7 GB while the computer is busy can.
        for attempt in range(2):
            done = self._launch([str(PROGRAM), "-M", "convert", "-m", str(SDXL), "-o",
                                 str(part), "--type", "q8_0"], PREPARE_S, IMAGE_DIR)
            if done.returncode == 0 and part.is_file() and part.stat().st_size >= 1_000_000:
                part.replace(QUANTIZED)
                return
            with contextlib.suppress(OSError):
                part.unlink()
        raise ImageError("The 8-bit copy of the model could not be made: " + _said(done))

    def make(self, prompt: str, *, negative: str = "", width: int = 512, height: int = 512,
             steps: int = 4, seed: int | None = None) -> Picture:
        """One picture of \a prompt. Raises `ImageError` with the reason."""
        prompt = clean_prompt(prompt)
        negative = " ".join(_CONTROL.sub(" ", str(negative or "")).split())[:MAX_PROMPT]
        check_size(width, height, steps)
        problem = unavailable()
        if problem:
            raise ImageError(problem)
        with _ONE_AT_A_TIME:
            # The half-precision original does not fit the card beside anything,
            # so the first picture makes the 8-bit copy: minutes, once.
            self.prepare()
            return self._make(prompt, negative, int(width), int(height), int(steps), seed)

    def _make(self, prompt: str, negative: str, width: int, height: int, steps: int,
              seed: int | None) -> Picture:
        seed = int(seed) if seed is not None and int(seed) >= 0 else random.randrange(2**31)
        folder = Path(tempfile.mkdtemp(prefix="akira-picture-"))
        try:
            prompt_file, negative_file = folder / "prompt.txt", folder / "negative.txt"
            prompt_file.write_text(prompt, encoding="utf-8")
            negative_file.write_text(negative, encoding="utf-8")
            out = folder / "picture.png"
            arguments = command(QUANTIZED, prompt_file, negative_file, out, width=width,
                                height=height, steps=steps, seed=seed, device=self.device())
            started = self._clock()
            set_aside = self._set_aside if self._set_aside is not None else _SET_ASIDE
            with set_aside():
                done = self._launch(arguments, PICTURE_S, folder)
            if done.returncode != 0 or not out.is_file():
                raise ImageError("The picture could not be made: " + _said(done))
            png = out.read_bytes()
            if png[:8] != b"\x89PNG\r\n\x1a\n":
                raise ImageError("sd-cli did not write a PNG.")
            return Picture(png, prompt, width, height, steps, seed,
                           round(self._clock() - started, 1))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


def _said(done: Any) -> str:
    """The last useful line `sd-cli` printed, for a reason."""
    text = ""
    for stream in (getattr(done, "stderr", b""), getattr(done, "stdout", b"")):
        if isinstance(stream, bytes):
            stream = stream.decode("utf-8", "replace")
        text += str(stream or "")
    # Progress bars redraw with carriage returns; none of them says why.
    lines = [line.strip() for line in text.replace("\r", "\n").splitlines()
             if line.strip() and not line.strip().startswith("|")]
    errors = [line for line in lines if "error" in line.lower() or "fail" in line.lower()]
    return (errors or lines or ["it said nothing"])[-1][:300]
