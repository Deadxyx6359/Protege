"""Boards connected to this computer: the ST-LINK on a Nucleo, and serial ports.

Through ST's own STM32CubeProgrammer command line (STM32_Programmer_CLI), found
where ST's VS Code extension keeps it or where STM32CubeProgrammer installs:

  * **What is connected:** the ST-LINK probes, and the board each is on.
  * **Reading the running chip:** words of memory, read in hot-plug mode, which
    neither resets nor halts the program running on it.
  * **Programming it:** a built program written to its flash, verified, and the
    chip reset to run it. What was on it before is gone, so this always asks.

And serial ports through pyserial: which there are, and what one says for a few
seconds, such as a board's printf over the ST-LINK's virtual COM port.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

#: How long the programmer may take: a flash of half a megabyte takes seconds.
PROGRAMMER_TIMEOUT_S = 120.0
#: The most of a serial port read at once, in seconds and characters.
MAX_LISTEN_S = 30.0
MAX_SERIAL_CHARS = 20_000
#: Where a .bin is written, having no addresses of its own: the start of flash.
FLASH_START = 0x08000000

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_WORDS = re.compile(r"^\s*0x([0-9A-Fa-f]{8})\s*:\s*((?:[0-9A-Fa-f]{8}\s*)+)$", re.MULTILINE)


class BoardError(RuntimeError):
    """Said to the person: what went wrong with the board or the programmer."""


def programmer() -> Path | None:
    """STM32_Programmer_CLI, the newest found, or None."""
    found = shutil.which("STM32_Programmer_CLI")
    if found:
        return Path(found)
    places = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        places += sorted(Path(local, "stm32cube", "bundles", "programmer").glob(
            "*/bin/STM32_Programmer_CLI.exe"), key=lambda p: p.stat().st_mtime)
    for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if root:
            places += list(Path(root, "STMicroelectronics", "STM32Cube",
                                "STM32CubeProgrammer", "bin").glob("STM32_Programmer_CLI.exe"))
    return places[-1] if places else None


def _run(arguments: list[str], timeout: float = PROGRAMMER_TIMEOUT_S) -> str:
    cli = programmer()
    if cli is None:
        raise BoardError("ST's programmer (STM32_Programmer_CLI) was not found. Install "
                         "STM32CubeProgrammer, or ST's STM32 extension for VS Code.")
    try:
        done = subprocess.run([str(cli), *arguments], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise BoardError(f"The programmer did not finish within {timeout:.0f} seconds.") \
            from None
    except OSError as exc:
        raise BoardError(f"The programmer could not be started: {exc}") from None
    out = (done.stdout or "") + (done.stderr or "")
    error = next((line.strip() for line in out.splitlines()
                  if line.strip().lower().startswith("error")), "")
    if done.returncode != 0 or error:
        raise BoardError(_explained(error or f"The programmer stopped (exit code "
                                             f"{done.returncode})."))
    return out


def _explained(error: str) -> str:
    text = error.removeprefix("Error:").strip()
    if "No STM32 target found" in text or "No debug probe detected" in text \
            or "ST-LINK error" in text:
        return (f"{text}. Is the board plugged in by USB, and nothing else (a debugger, "
                "CubeIDE, another programmer) using its ST-LINK?")
    return text


@dataclass(frozen=True)
class Probe:
    serial: str
    board: str
    firmware: str


def probes() -> list[Probe]:
    """The ST-LINK probes connected now."""
    out = _run(["-l", "st-link"], timeout=30.0)
    found: list[Probe] = []
    for block in re.split(r"ST-Link Probe \d+\s*:", out)[1:]:
        def value(label: str) -> str:
            match = re.search(rf"{label}\s*:\s*(.+)", block)
            return match.group(1).strip() if match else ""
        found.append(Probe(value("ST-LINK SN"), value("Board Name"), value("ST-LINK FW")))
    return found


def read_words(address: int, count: int = 1) -> list[int]:
    """\a count 32-bit words from \a address on the running chip, without stopping it."""
    if not 0 <= address <= 0xFFFFFFFF or address % 4:
        raise BoardError(f"0x{address:X} is not a word's address.")
    count = max(1, min(int(count), 64))
    out = _run(["-c", "port=SWD", "mode=HOTPLUG", "-r32", f"0x{address:08X}", str(count * 4)],
               timeout=30.0)
    words: list[int] = []
    for _start, row in _WORDS.findall(out):
        words += [int(word, 16) for word in row.split()]
    if len(words) < count:
        raise BoardError("The programmer read nothing back from the chip.")
    return words[:count]


def flash(image: Path) -> str:
    """Write \a image (.elf, .hex or .bin) to the chip's flash, verify it, and reset the
    chip to run it. What the programmer said, briefly."""
    suffix = image.suffix.lower()
    if suffix not in (".elf", ".hex", ".bin"):
        raise BoardError("Only a built program can be written: an .elf, .hex or .bin file.")
    if not image.is_file():
        raise BoardError(f"No such file: {image}")
    write = ["-w", str(image)] + ([f"0x{FLASH_START:08X}"] if suffix == ".bin" else [])
    out = _run(["-c", "port=SWD", *write, "-v", "-rst"])
    kept = [line.strip() for line in out.splitlines()
            if re.search(r"download|verif|erase|reset|size|device name", line, re.IGNORECASE)]
    return "\n".join(kept[-12:]) or "Written."


# -- serial ports -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Port:
    name: str
    description: str


def ports() -> list[Port]:
    """The serial ports there are now: COM6 "STMicroelectronics STLink Virtual COM Port"."""
    try:
        from serial.tools import list_ports
    except ImportError:
        raise BoardError("pyserial is not installed, so serial ports cannot be read.") from None
    return [Port(p.device, p.description or "") for p in list_ports.comports()]


def listen(port: str, baud: int = 115200, seconds: float = 5.0) -> str:
    """What \a port says in \a seconds (at most `MAX_LISTEN_S`), as text."""
    try:
        import serial
    except ImportError:
        raise BoardError("pyserial is not installed, so serial ports cannot be read.") from None
    if not re.fullmatch(r"COM\d{1,3}|/dev/tty\w+", port):
        raise BoardError(f"{port} is not a serial port's name, such as COM6.")
    seconds = max(0.5, min(float(seconds), MAX_LISTEN_S))
    chunks: list[bytes] = []
    try:
        with serial.Serial(port, int(baud), timeout=0.2) as stream:
            deadline = time.monotonic() + seconds
            size = 0
            while time.monotonic() < deadline and size < MAX_SERIAL_CHARS:
                piece = stream.read(1024)
                if piece:
                    chunks.append(piece)
                    size += len(piece)
    except (serial.SerialException, OSError, ValueError) as exc:
        raise BoardError(f"{port} could not be read: {exc}. Is another program (a serial "
                         "monitor) holding it open?") from None
    return b"".join(chunks).decode("utf-8", errors="replace")[:MAX_SERIAL_CHARS]
