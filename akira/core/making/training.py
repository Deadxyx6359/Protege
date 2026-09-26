"""Training a LoRA adapter (E4): the person's own conversations, taught to a smaller model.

The base is Qwen3-4B, the one that trains within the card's six gigabytes
(QLoRA: the model in 4 bits, a small adapter learned beside it). The work is
done by `akira/training/_trainer.py`, run by the training environment's Python
(`models/train/env`) as a process of its own: that environment holds PyTorch
and Hugging Face's libraries, which Akira's own Python never has. The trainer
installs Akira's network guard and forces every library offline before it
imports them.

The examples are conversations the person chose, each taught as it went: the
model learns to answer as the assistant did, not to write the person's side.
They are written for the trainer beside the adapter and deleted once training
ends, however it ends; the adapter is what is kept.

Training holds the graphics card for as long as it takes, often an hour or
more. So it is lent (`ModelRouter.set_aside` with `lent_for`), and anything
wanting a model meanwhile is told why at once, rather than kept waiting.
Stopping ends it between steps and keeps nothing.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager

from akira.core.config import MODELS_DIR, REPO_ROOT

TRAIN_DIR = MODELS_DIR / "train"
PYTHON = TRAIN_DIR / "env" / "Scripts" / "python.exe"
BASE = TRAIN_DIR / "Qwen3-4B"
#: The model an adapter is used with, as llama.cpp loads it.
RUNNER = TRAIN_DIR / "Qwen3-4B-Q4_K_M.gguf"
ADAPTERS = TRAIN_DIR / "adapters"
TRAINER = REPO_ROOT / "akira" / "training" / "_trainer.py"

#: Fewer than this teaches nothing; more than this takes too long on this card.
MIN_EXAMPLES, MAX_EXAMPLES = 5, 2_000

#: The longest a single example is, in tokens; longer ones keep their end.
LONGEST = 1_024

#: How long a stopped trainer has to finish its step before it is ended.
STOP_GRACE_S = 120

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,58}[A-Za-z0-9]$|^[A-Za-z0-9]$")


class TrainingError(Exception):
    """Why training cannot start, or why it failed, said so a person can act on it."""


@dataclass(frozen=True)
class Adapter:
    """An adapter trained here."""

    name: str
    folder: str
    gguf: str
    model: str
    """The model it is used with."""
    made: float
    examples: int
    steps: int
    loss: float
    seconds: float


def unavailable() -> str:
    """Why training cannot run on this computer at all, or ""."""
    gone = [path for path in (PYTHON, BASE / "config.json", RUNNER, TRAINER)
            if not path.is_file()]
    if gone:
        names = ", ".join(str(path.relative_to(REPO_ROOT)) if REPO_ROOT in path.parents
                          else str(path) for path in gone)
        return f"The training files are not in place: {names}."
    return ""


def examples_from(conversations: list[list[tuple[str, str]]]) -> list[dict]:
    """Conversations, each a list of (role, text), as the trainer's examples.

    Only the person's and the assistant's words are kept, empty ones dropped,
    and a conversation with no reply to learn from is left out.
    """
    made = []
    for conversation in conversations:
        messages = [{"role": role, "content": text.strip()} for role, text in conversation
                    if role in ("user", "assistant") and text and text.strip()]
        if any(m["role"] == "assistant" for m in messages) and messages[0]["role"] == "user":
            made.append({"messages": messages})
    return made


def adapters() -> list[Adapter]:
    """Every adapter trained here, newest first."""
    found = []
    for meta in ADAPTERS.glob("*/meta.json"):
        try:
            raw = json.loads(meta.read_text(encoding="utf-8"))
            adapter = Adapter(**{key: raw[key] for key in Adapter.__dataclass_fields__})
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if Path(adapter.gguf).is_file():
            found.append(adapter)
    return sorted(found, key=lambda a: a.made, reverse=True)


def folder_for(name: str) -> Path:
    if not _NAME.match(name or ""):
        raise TrainingError("Name the adapter with letters, numbers, spaces, dots, dashes or "
                            "underscores, up to 60 characters.")
    return ADAPTERS / name.strip().replace(" ", "-").lower()


class Trainer:
    """One training at a time, run in the training environment, with the card lent to it."""

    def __init__(self, set_aside: Callable[..., ContextManager[Any]] | None = None,
                 popen: Callable[..., Any] = subprocess.Popen,
                 clock: Callable[[], float] = time.time) -> None:
        self._set_aside = set_aside if set_aside is not None else (
            lambda **_: contextlib.nullcontext())
        self._popen = popen
        self._clock = clock
        self._thread: threading.Thread | None = None
        self._process: Any = None
        self._stop_file: Path | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self, name: str, examples: list[dict], *, epochs: int = 2, rank: int = 16,
              on_progress: Callable[[dict], None] = lambda update: None,
              on_done: Callable[[str, Adapter | None], None] = lambda why, made: None) -> Path:
        """Start training an adapter called \a name on \a examples. Returns its folder.

        \a on_progress and \a on_done are called on the training's own thread.
        Raises `TrainingError` when it cannot start.
        """
        with self._lock:
            if self.running:
                raise TrainingError("An adapter is already being trained.")
            problem = unavailable()
            if problem:
                raise TrainingError(problem)
            folder = folder_for(name)
            if folder.exists():
                raise TrainingError(f"There is already an adapter called {name!r}.")
            if not MIN_EXAMPLES <= len(examples) <= MAX_EXAMPLES:
                raise TrainingError(f"Choose from {MIN_EXAMPLES} to {MAX_EXAMPLES:,} "
                                    f"conversations; {len(examples)} were chosen.")
            if not 1 <= int(epochs) <= 5 or int(rank) not in (8, 16, 32):
                raise TrainingError("Train for 1 to 5 passes, at rank 8, 16 or 32.")
            folder.mkdir(parents=True)
            examples_file = folder / "examples.jsonl"
            examples_file.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                             for e in examples), encoding="utf-8")
            self._stop_file = folder / "stop"
            job = {"name": name, "base": str(BASE), "examples": str(examples_file),
                   "out": str(folder), "stop_file": str(self._stop_file),
                   "epochs": int(epochs), "rank": int(rank), "alpha": 2 * int(rank),
                   "learning_rate": 2e-4, "accumulate": 4, "longest": LONGEST,
                   "architecture": "qwen3"}
            (folder / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
            self._thread = threading.Thread(target=self._run, name="akira-training", daemon=True,
                                            args=(name, folder, len(examples), on_progress,
                                                  on_done))
            self._thread.start()
        return folder

    def stop(self) -> None:
        """Stop between steps; nothing is kept. Ended outright if it does not stop in time."""
        stop, process = self._stop_file, self._process
        if stop is not None:
            with contextlib.suppress(OSError):
                stop.touch()
        if process is not None:
            def end_it() -> None:
                try:
                    process.wait(timeout=STOP_GRACE_S)
                except Exception:  # noqa: BLE001 - it is ended either way
                    with contextlib.suppress(Exception):
                        process.kill()
            threading.Thread(target=end_it, name="akira-training-stop", daemon=True).start()

    def _run(self, name: str, folder: Path, count: int, on_progress, on_done) -> None:
        last: dict = {}
        finished: dict = {}
        problem = ""
        lent = (f"The graphics card is training the adapter “{name}”. Answers wait until it "
                "finishes or is stopped.")
        try:
            with self._set_aside(timeout=600.0, lent_for=lent):
                env = {key: value for key, value in os.environ.items()
                       if not key.upper().startswith("PYTHON")}
                env.update({"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                            "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})
                errors = folder / "training.log"
                with errors.open("wb") as log:
                    self._process = self._popen(
                        [str(PYTHON), "-I", str(TRAINER), str(folder / "job.json")],
                        stdout=subprocess.PIPE, stderr=log, stdin=subprocess.DEVNULL,
                        cwd=str(REPO_ROOT), env=env,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    for raw in self._process.stdout:
                        line = raw.decode("utf-8", "replace").strip() if isinstance(
                            raw, bytes) else str(raw).strip()
                        if not line.startswith("{"):
                            continue
                        try:
                            update = json.loads(line)
                        except ValueError:
                            continue
                        if update.get("stage") == "training" and "step" in update:
                            last = update
                        if update.get("done"):
                            finished = update
                        if update.get("error"):
                            problem = str(update["error"])
                        with contextlib.suppress(Exception):
                            on_progress(update)
                    code = self._process.wait()
            if self._stop_file is not None and self._stop_file.exists():
                problem = "Training was stopped, so nothing was kept."
            elif code != 0 or not finished:
                problem = problem or ("Training failed: " + _tail(folder / "training.log"))
        except Exception as exc:  # noqa: BLE001 - a crashed trainer must not be silent
            problem = f"Training could not run: {exc}"
        finally:
            self._process = None
            with contextlib.suppress(OSError):
                (folder / "examples.jsonl").unlink()
        if problem:
            shutil.rmtree(folder, ignore_errors=True)
            on_done(problem, None)
            return
        adapter = Adapter(name, str(folder), str(finished.get("gguf") or folder / "adapter.gguf"),
                          str(RUNNER), self._clock(), count, int(last.get("step") or 0),
                          float(last.get("loss") or 0.0), float(finished.get("seconds") or 0.0))
        (folder / "meta.json").write_text(json.dumps(asdict(adapter), indent=1), encoding="utf-8")
        on_done("", adapter)


def _tail(log: Path) -> str:
    try:
        lines = [line.strip() for line in log.read_text(encoding="utf-8", errors="replace")
                 .splitlines() if line.strip()]
    except OSError:
        return "it said nothing."
    errors = [line for line in lines if "error" in line.lower()]
    return ((errors or lines or ["it said nothing."])[-1])[:300]
