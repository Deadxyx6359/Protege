"""Pictures (E1): SDXL-Turbo through stable-diffusion.cpp, on the graphics card.

`sd-cli` is a stand-in here, which writes a PNG where it is told to and records
how it was run, so no test needs the 7 GB model or the card. What is tested is
what it is given and never given, that the prompt is never an argument, that
the language models are set aside while it runs, and that nothing is left
behind. The last test makes a real picture when the files are in place.
"""

from __future__ import annotations

import contextlib
import subprocess
from pathlib import Path

import pytest

from akira.core.making import images
from akira.core.making.images import ALLOWED_FLAGS, ImageError, ImageMaker

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class Ran:
    def __init__(self, returncode=0, stderr=b"", stdout=b""):
        self.returncode, self.stderr, self.stdout = returncode, stderr, stdout


@pytest.fixture
def in_place(tmp_path, monkeypatch):
    """The picture files, as empty stand-ins in a folder of the test's own."""
    folder = tmp_path / "image"
    (folder / "bin").mkdir(parents=True)
    for name in ("bin/sd-cli.exe", "sdxl_vae.safetensors", "sd_xl_turbo_1.0.q8_0.gguf"):
        (folder / name).write_bytes(b"x")
    monkeypatch.setattr(images, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(images, "IMAGE_DIR", folder)
    monkeypatch.setattr(images, "PROGRAM", folder / "bin" / "sd-cli.exe")
    monkeypatch.setattr(images, "VAE", folder / "sdxl_vae.safetensors")
    monkeypatch.setattr(images, "SDXL", folder / "sd_xl_turbo_1.0_fp16.safetensors")
    monkeypatch.setattr(images, "QUANTIZED", folder / "sd_xl_turbo_1.0.q8_0.gguf")
    return folder


LISTED = (b"Vulkan0\tIntel(R) Iris(R) Xe Graphics\r\n"
          b"Vulkan1\tNVIDIA GeForce RTX 3060 Laptop GPU\r\nCPU\t12th Gen Intel(R) Core(TM)\r\n")


def stand_in(runs, *, writes=PNG, returncode=0, stderr=b""):
    def run(arguments, **options):
        if arguments[1:] == ["--list-devices"]:
            return Ran(0, b"", LISTED)
        seen = {"arguments": arguments, "options": options}
        if "--prompt-file" in arguments:
            seen["prompt"] = Path(arguments[arguments.index("--prompt-file") + 1]).read_text(
                encoding="utf-8")
            seen["folder"] = Path(arguments[arguments.index("-o") + 1]).parent
        runs.append(seen)
        if writes is not None and "-o" in arguments:
            Path(arguments[arguments.index("-o") + 1]).write_bytes(writes)
        return Ran(returncode, stderr)
    return run


def test_a_picture_is_made_with_the_prompt_in_a_file_and_nothing_is_left(in_place):
    runs, aside = [], []

    @contextlib.contextmanager
    def set_aside():
        aside.append("in")
        yield
        aside.append("out")

    maker = ImageMaker(set_aside=set_aside, run=stand_in(runs))
    sneaky = 'a fox" --rpc-servers evil.example:50052 -o C:/Windows/x.png'
    picture = maker.make(sneaky, seed=7)
    [run] = runs
    arguments = run["arguments"]
    assert picture.png == PNG and picture.seed == 7 and (picture.width, picture.height) == (512, 512)
    assert run["prompt"] == sneaky, "the prompt was not what sd-cli read"
    assert sneaky not in arguments and "--rpc-servers" not in arguments
    assert {part for part in arguments[1:] if part.startswith("-")} <= ALLOWED_FLAGS
    assert arguments[arguments.index("-m") + 1].endswith("q8_0.gguf")
    assert arguments[arguments.index("--cfg-scale") + 1] == "1.0"
    # The NVIDIA card, not the integrated one listed first.
    assert arguments[arguments.index("--backend") + 1] == "Vulkan1"
    assert aside == ["in", "out"], "the language models were not set aside"
    assert run["options"]["stdin"] == subprocess.DEVNULL
    assert not run["folder"].exists(), "the working folder was left behind"


def test_the_first_picture_makes_the_8_bit_copy_first(in_place):
    (in_place / "sd_xl_turbo_1.0.q8_0.gguf").unlink()
    (in_place / "sd_xl_turbo_1.0_fp16.safetensors").write_bytes(b"x")
    runs = []

    def run(arguments, **options):
        if arguments[1:] == ["--list-devices"]:
            return Ran(0, b"", LISTED)
        runs.append(arguments)
        out = Path(arguments[arguments.index("-o") + 1])
        out.write_bytes(b"g" * 2_000_000 if "convert" in arguments else PNG)
        return Ran()

    ImageMaker(run=run).make("a fox")
    assert runs[0][1:3] == ["-M", "convert"]
    assert runs[1][runs[1].index("-m") + 1].endswith("q8_0.gguf")


def test_the_card_is_borrowed_as_the_shell_says(in_place, monkeypatch):
    lent = []

    @contextlib.contextmanager
    def set_aside():
        lent.append(True)
        yield

    monkeypatch.setattr(images, "_SET_ASIDE", images.contextlib.nullcontext)
    images.lend_card(set_aside)
    ImageMaker(run=stand_in([])).make("a fox")
    assert lent == [True]


@pytest.mark.parametrize("prompt, options, why", [
    ("", {}, "Say what"),
    ("\x00\x01  ", {}, "Say what"),
    ("x" * (images.MAX_PROMPT + 1), {}, "at most"),
    ("a fox", {"width": 500}, "steps of 64"),
    ("a fox", {"height": 2048}, "steps of 64"),
    ("a fox", {"steps": 0}, "1 to"),
    ("a fox", {"steps": 50}, "1 to"),
])
def test_what_cannot_be_made_is_refused_before_anything_runs(in_place, prompt, options, why):
    runs = []
    with pytest.raises(ImageError, match=why):
        ImageMaker(run=stand_in(runs)).make(prompt, **options)
    assert runs == []


@pytest.mark.parametrize("listed, device", [
    (LISTED.decode(), "Vulkan1"),
    ("Vulkan0\tAMD Radeon RX 7600\nCPU\tRyzen\n", "Vulkan0"),
    ("Vulkan0\tIntel(R) Iris(R) Xe Graphics\nCPU\tIntel\n", ""),
    ("", ""),
    ("Vulkan1\tNVIDIA; --rpc-servers x\n", "Vulkan1"),
    ("--rpc-servers\tNVIDIA\n", ""),
])
def test_the_discrete_card_is_the_one_drawn_on(listed, device):
    assert images.pick_device(listed) == device


def test_a_prompt_is_one_line_without_control_characters():
    assert images.clean_prompt("a\nfox\tin\x07 snow ") == "a fox in snow"


def test_without_the_files_it_says_which_are_missing(in_place):
    (in_place / "sdxl_vae.safetensors").unlink()
    assert "sdxl_vae.safetensors" in images.unavailable()
    with pytest.raises(ImageError, match="not in place"):
        ImageMaker(run=stand_in([])).make("a fox")


@pytest.mark.parametrize("returncode, writes, stderr, why", [
    (1, None, b"loading...\nerror: out of memory\n", "out of memory"),
    (0, None, b"", "could not be made"),
    (0, b"GIF89a", b"", "did not write a PNG"),
])
def test_a_failure_says_why(in_place, returncode, writes, stderr, why):
    runs = []
    with pytest.raises(ImageError, match=why):
        ImageMaker(run=stand_in(runs, writes=writes, returncode=returncode,
                                stderr=stderr)).make("a fox")
    assert not runs[0]["folder"].exists()


def test_a_run_that_takes_too_long_is_stopped(in_place):
    def run(arguments, **options):
        raise subprocess.TimeoutExpired(arguments, options["timeout"])

    with pytest.raises(ImageError, match="too long"):
        ImageMaker(run=run).make("a fox")


def test_sd_cli_is_never_given_a_flag_outside_the_list(in_place, monkeypatch):
    original = images.command
    monkeypatch.setattr(images, "command",
                        lambda *a, **k: original(*a, **k) + ["--rpc-servers", "x:1"])
    runs = []
    with pytest.raises(ImageError, match="never is"):
        ImageMaker(run=stand_in(runs)).make("a fox")
    assert runs == []


def test_the_8_bit_copy_is_made_once_and_only_kept_whole(in_place):
    (in_place / "sd_xl_turbo_1.0.q8_0.gguf").unlink()
    (in_place / "sd_xl_turbo_1.0_fp16.safetensors").write_bytes(b"x")
    runs = []

    def converting(arguments, **options):
        runs.append(arguments)
        Path(arguments[arguments.index("-o") + 1]).write_bytes(b"g" * 2_000_000)
        return Ran()

    maker = ImageMaker(run=converting)
    maker.prepare()
    maker.prepare()
    assert len(runs) == 1 and runs[0][1:3] == ["-M", "convert"] and maker.prepared

    (in_place / "sd_xl_turbo_1.0.q8_0.gguf").unlink()
    with pytest.raises(ImageError, match="8-bit copy"):
        ImageMaker(run=lambda arguments, **options: Ran(1, b"error: bad file")).prepare()
    assert not (in_place / "sd_xl_turbo_1.0.q8_0.gguf").exists()
    assert not (in_place / "sd_xl_turbo_1.0.q8_0.part.gguf").exists()


# -- stopping ------------------------------------------------------------------------------------


def waits_to_be_stopped(runs, started):
    """Stands in for `run_stoppable` on a long job: returns only when stopped."""
    def run(arguments, **options):
        if arguments[1:] == ["--list-devices"]:
            return Ran(0, b"", LISTED)
        runs.append(arguments)
        if "-o" in arguments:
            Path(arguments[arguments.index("-o") + 1]).write_bytes(b"half")
        started.set()
        assert options["stop"].wait(5), "it was never stopped"
        raise images.Stopped()
    return run


def test_a_picture_being_made_can_be_stopped_and_nothing_is_left(in_place):
    import threading

    runs, started, outcome = [], threading.Event(), {}
    maker = ImageMaker(run=waits_to_be_stopped(runs, started))

    def work():
        try:
            maker.make("a fox")
        except ImageError as exc:
            outcome["error"] = exc

    worker = threading.Thread(target=work)
    worker.start()
    assert started.wait(5)
    folder = Path(runs[0][runs[0].index("-o") + 1]).parent
    maker.stop()
    worker.join(5)
    assert isinstance(outcome.get("error"), images.Stopped) and str(outcome["error"]) == "Stopped."
    assert not folder.exists(), "the half-made picture was left behind"


def test_stopping_the_8_bit_copy_leaves_no_part_of_it(in_place):
    import threading

    (in_place / "sd_xl_turbo_1.0.q8_0.gguf").unlink()
    (in_place / "sd_xl_turbo_1.0_fp16.safetensors").write_bytes(b"x")
    runs, started = [], threading.Event()
    maker = ImageMaker(run=waits_to_be_stopped(runs, started))
    threading.Timer(0.05, lambda: started.wait(5) and maker.stop()).start()
    with pytest.raises(images.Stopped):
        maker.prepare()
    assert len(runs) == 1, "a stopped copy was tried again"
    assert not (in_place / "sd_xl_turbo_1.0.q8_0.part.gguf").exists()
    assert not maker.prepared


def test_a_stop_asked_for_when_idle_does_not_stop_the_next_picture(in_place):
    maker = ImageMaker(run=stand_in([]))
    maker.stop()
    assert maker.make("a fox").png == PNG


def test_the_runner_really_ends_a_stopped_process_and_one_out_of_time():
    import sys
    import threading
    import time

    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    stop = threading.Event()
    threading.Timer(0.3, stop.set).start()
    began = time.monotonic()
    with pytest.raises(images.Stopped):
        images.run_stoppable(sleeper, timeout=60, cwd=".", stop=stop)
    assert time.monotonic() - began < 5
    with pytest.raises(subprocess.TimeoutExpired):
        images.run_stoppable(sleeper, timeout=0.5, cwd=".", stop=threading.Event())
    done = images.run_stoppable([sys.executable, "-c", "print('made')"], timeout=30, cwd=".",
                                capture_output=True)
    assert done.returncode == 0 and done.stdout.strip() == b"made"


# -- for real ------------------------------------------------------------------------------------


def test_a_real_picture_on_the_card():
    if images.unavailable() or not images.QUANTIZED.is_file():
        pytest.skip(images.unavailable() or "the 8-bit copy has not been made yet")
    picture = ImageMaker().make("a red apple on a white table, studio photo", seed=1, steps=2)
    assert picture.png[:8] == b"\x89PNG\r\n\x1a\n" and len(picture.png) > 50_000
