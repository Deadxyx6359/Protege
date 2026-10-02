"""What an agent is told about the folder it works in, when the folder is of a kind
with rules of its own.

An STM32CubeMX project is one. Asked to add a display driver to one, the
implementer edited a main.c it guessed was at the top of the project, then wrote
a second one there; declared `hspi1` again in its own file, which CubeMX had
already defined; and wrote "// Add user sources here" to find a line that reads
"# Add user sources here". Every one of those is in the project's own files. So
the agent is told, from them: where main.c is, where its own code may go and
survive the next generation, what CubeMX already made (the peripherals'
handles and how each was set up, and the pins' names from their labels), and
where a new source file is added to the build.

Read only where the person allowed reading, like anything else an agent sees.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

#: The most of a project's own files read to describe it.
MAX_BYTES = 400_000

_HANDLE = re.compile(r"^([A-Z0-9]+_HandleTypeDef)\s+(\w+)\s*;", re.MULTILINE)
_LABEL = re.compile(r"^#define\s+(\w+)_Pin\s+(GPIO_PIN_\d+)\s*$", re.MULTILINE)
_PORT = re.compile(r"^#define\s+(\w+)_GPIO_Port\s+(GPIO[A-K])\s*$", re.MULTILINE)
_BLOCK = re.compile(r"/\*\s*USER CODE BEGIN (\w+)\s*\*/")
_INIT = re.compile(r"^static void (MX_\w+_Init)\(void\)\s*\{(.*?)^\}", re.MULTILINE | re.DOTALL)
_SETTING = re.compile(r"^\s*\w+\.Init\.(\w+)\s*=\s*([^;]+);", re.MULTILINE)


def notes(folder: str, may_read: Callable[[Path], bool]) -> str:
    """What to tell an agent about \a folder, or "" when nothing is known of its kind."""
    if not folder:
        return ""
    root = Path(folder)
    try:
        ioc = next(iter(sorted(root.glob("*.ioc"))), None)
    except OSError:
        return ""
    if ioc is None:
        return ""
    return _cubemx(root, ioc, may_read)


def _read(path: Path, may_read: Callable[[Path], bool]) -> str:
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES or not may_read(path):
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _cubemx(root: Path, ioc: Path, may_read: Callable[[Path], bool]) -> str:
    main_c = next((p for p in (root / "Core" / "Src" / "main.c", root / "Src" / "main.c")
                   if p.is_file()), None)
    main_h = next((p for p in (root / "Core" / "Inc" / "main.h", root / "Inc" / "main.h")
                   if p.is_file()), None)
    source = _read(main_c, may_read) if main_c else ""
    header = _read(main_h, may_read) if main_h else ""
    lines = [f"This folder is an STM32CubeMX project ({ioc.name}). CubeMX writes its files "
             "again each time the person generates code, and keeps only what is between a "
             "/* USER CODE BEGIN x */ line and its /* USER CODE END x */ line: put your code "
             "in main.c only between those, and the rest of a change in files of your own."]
    if main_c is not None:
        blocks = list(dict.fromkeys(_BLOCK.findall(source)))
        lines.append(f"main.c is {main_c}" + (
            f"; its USER CODE blocks: {', '.join(blocks)} (Includes for #include lines, PD for "
            "#define lines, 2 for code that runs once after the peripherals are set up, "
            "WHILE and 3 inside the main loop)" if blocks else "") + ".")
    if main_h is not None:
        lines.append(f"main.h is {main_h}; include \"main.h\" in your own files for the HAL "
                     "and the names below.")
    handles = _HANDLE.findall(source)
    if handles:
        lines.append("CubeMX already defines these in main.c; in another file, write `extern` "
                     "and the line again, or take a pointer to it, and never define it again: "
                     + " ".join(f"{kind} {name};" for kind, name in handles))
    for name, body in _INIT.findall(source):
        settings = _SETTING.findall(body)
        if settings and name != "MX_GPIO_Init":
            lines.append(f"{name} sets: " + ", ".join(f"{k} = {v.strip()}"
                                                       for k, v in settings[:14]) + ".")
    pins = dict(_LABEL.findall(header))
    ports = dict(_PORT.findall(header))
    # The crystal's and the debugger's pins are the board's, not the person's to use.
    named = [f"{label}_Pin ({pins[label]}) on {label}_GPIO_Port ({ports[label]})"
             for label in pins if label in ports and not label.startswith(("RCC_OSC", "T_SW"))]
    if named:
        lines.append("Pins named in CubeMX, for HAL_GPIO_WritePin and the like: "
                     + "; ".join(named) + ".")
    cmake = root / "CMakeLists.txt"
    text = _read(cmake, may_read)
    if text:
        marker = next((line.strip() for line in text.splitlines()
                       if "user sources" in line.lower()), "")
        lines.append(f"A new .c file is built only once it is listed in {cmake}"
                     + (f", in target_sources(...) under the line `{marker}`" if marker else "")
                     + ", as a path from the project folder, such as Core/Src/name.c.")
        lines.append("build_project builds it with its own preset and says what the compiler "
                     "found.")
    lines.append("Where those tools are offered: stm32_pins and find_vendor_names give the "
                 "board's pins and the chip library's exact names; after a change to the .ioc, "
                 "generate_cubemx_code brings the code in line; flash_firmware puts the build "
                 "on the board (the person is asked each time), and read_serial or "
                 "read_register shows what it does there.")
    return "\n".join(lines)
