"""STM32CubeMX projects: what one is set up to do, and generating its code again.

**What it is set up to do** comes from its `.ioc` file, which CubeMX writes as
`key=value` lines: the chip, the clock, each pin's signal and label, and each
peripheral's settings (`SPI1.FirstBit=SPI_FIRSTBIT_LSB`). Said in a few lines, it
lets the chat answer "is my CubeMX setup right?" from the setup itself.

**Generating its code again** runs CubeMX without its window, on the project's
own `.ioc`: as clicking Generate Code does, it rewrites the generated files and
keeps what is between USER CODE lines. An agent that changed the `.ioc` uses it
to bring the code into line, asked first like any program run.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

GENERATE_TIMEOUT_S = 300.0
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
#: The most of a peripheral's settings said.
MAX_SETTINGS = 14


class CubeMXError(RuntimeError):
    """Said to the person."""


def installed() -> Path | None:
    """STM32CubeMX's folder, where its program and its own Java are."""
    places = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        places.append(Path(local, "Programs", "STM32CubeMX"))
    for root in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", "")):
        if root:
            places.append(Path(root, "STMicroelectronics", "STM32Cube", "STM32CubeMX"))
    return next((p for p in places if (p / "STM32CubeMX.exe").is_file()), None)


def project_file(folder: Path) -> Path | None:
    """The `.ioc` at the top of \a folder, or None."""
    try:
        return next(iter(sorted(Path(folder).glob("*.ioc"))), None)
    except OSError:
        return None


def settings(ioc: Path) -> dict[str, str]:
    try:
        text = ioc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    found: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            found[key.strip()] = value.strip().replace("\\:", ":").replace("\\#", "#")
    return found


def summary(ioc: Path) -> str:
    """What the project is set up to do, in a few lines: "" when it cannot be read."""
    found = settings(ioc)
    if not found:
        return ""
    part = found.get("Mcu.UserName") or found.get("Mcu.Name", "")
    clock = found.get("RCC.SYSCLKFreq_VALUE", "")
    toolchain = found.get("ProjectManager.TargetToolchain", "")
    head = f"The person's STM32CubeMX project, {ioc.name}: {part}"
    if clock.isdigit():
        head += f", system clock {int(clock) / 1e6:g} MHz"
    if toolchain:
        head += f", built with {toolchain}"
    lines = [head + "."]
    pins = []
    for key, signal in sorted(found.items()):
        if not key.endswith(".Signal") or key.startswith("VP_"):
            continue
        pin = key[:-len(".Signal")]
        label = found.get(f"{pin}.GPIO_Label", "")
        state = found.get(f"{pin}.PinState", "")
        said = f"{pin.split('-')[0]} {signal}"
        if label:
            said += f" ({label})"
        if state:
            said += f", starts {state.replace('GPIO_PIN_', '').lower()}"
        pins.append(said)
    if pins:
        lines.append("Pins: " + "; ".join(pins) + ".")
    ips = [found[k] for k in sorted(found, key=lambda k: int(k[6:]) if k[6:].isdigit() else 0)
           if re.fullmatch(r"Mcu\.IP\d+", k)]
    for ip in ips:
        if ip in ("NVIC", "RCC", "SYS", "GPIO") or ip.startswith("NUCLEO"):
            continue
        params = [(k[len(ip) + 1:], v) for k, v in found.items()
                  if k.startswith(ip + ".") and not k.endswith("IPParameters")
                  and "." not in k[len(ip) + 1:]]
        if params:
            shown = ", ".join(f"{k} {v}" for k, v in params[:MAX_SETTINGS])
            lines.append(f"{ip}: {shown}.")
        else:
            lines.append(f"{ip}: on, with CubeMX's defaults.")
    return "\n".join(lines)


def generate(folder: Path) -> str:
    """Generate the project's code again from its `.ioc`, as Generate Code does. What
    CubeMX said, briefly. Raises `CubeMXError`."""
    ioc = project_file(folder)
    if ioc is None:
        raise CubeMXError(f"{folder} has no .ioc file: it is not an STM32CubeMX project.")
    home = installed()
    if home is None:
        raise CubeMXError("STM32CubeMX was not found. Install it from st.com.")
    java = home / "jre" / "bin" / "java.exe"
    if not java.is_file():
        raise CubeMXError(f"STM32CubeMX's own Java is missing from {home}.")
    with tempfile.TemporaryDirectory(prefix="akira-cubemx-") as work:
        script = Path(work) / "generate.txt"
        script.write_text(f'config load "{ioc}"\nproject generate\nexit\n', encoding="utf-8")
        try:
            done = subprocess.run(
                [str(java), "--add-opens", "java.desktop/java.awt=ALL-UNNAMED",
                 "--add-exports", "java.desktop/sun.awt=ALL-UNNAMED", "-jar",
                 str(home / "STM32CubeMX.exe"), "-q", str(script)],
                cwd=str(home), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=GENERATE_TIMEOUT_S, stdin=subprocess.DEVNULL,
                creationflags=_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise CubeMXError(f"CubeMX did not finish within {GENERATE_TIMEOUT_S:.0f} "
                              "seconds.") from None
        except OSError as exc:
            raise CubeMXError(f"CubeMX could not be started: {exc}") from None
    out = (done.stdout or "") + (done.stderr or "")
    said = [line.strip() for line in out.splitlines()
            if line.strip().startswith(("OK", "KO", "Error", "ERROR")) or "Bye" in line]
    if any(line.startswith(("KO", "Error", "ERROR")) for line in said) or done.returncode:
        raise CubeMXError("CubeMX could not generate the code: "
                          + ("; ".join(said[-4:]) or f"exit code {done.returncode}"))
    return f"Generated the code of {ioc.name} again: " + ("; ".join(said[-4:]) or "done") + "."
