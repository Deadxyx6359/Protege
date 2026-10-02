"""Tools for firmware: boards, pins, a chip's own names and registers, and CubeMX.

  * `list_boards`, `read_serial` and `read_register` read boards plugged in by USB
    (`device.read`): which there are, what one prints, and a register of the chip
    while its program runs, by name (`SPI1.CR1`), its fields said.
  * `flash_firmware` writes a built program to the board (`device.write`), asked
    every time: what was on it is gone after.
  * `generate_cubemx_code` regenerates an STM32CubeMX project's code from its
    `.ioc` (`shell.run` for the project's folder), asked first.
  * `stm32_pins` and `find_vendor_names` look up what a board's and a chip's own
    files say: which pin is which and what each can carry, and the exact names in
    the vendor's library. They read only folders the person allowed reading.

See `akira.core.firmware` for how each is done.
"""

from __future__ import annotations

import re
from pathlib import Path

from akira.core.brain import pins as pin_facts
from akira.core.brain.grounding import HeaderIndex, family_headers, subject_of
from akira.core.firmware import boards, cubemx, registers
from akira.security.paths import real

from ..schema import Parameter, Requirement, Tool, ToolContext, ToolError, ToolResult


def _allowed_folders(context: ToolContext) -> list[Path]:
    """The folders the person allowed reading, and the one being worked in."""
    folders: list[Path] = []
    for capability in ("files.read", "docs.read"):
        grant = context.policy.granted(capability)
        for scope in (grant.scopes if grant is not None else ()):
            if scope and Path(scope) not in folders:
                folders.append(Path(scope))
    return folders


def _may_read(context: ToolContext):
    return lambda path: bool(context.policy.allows("files.read", str(path))
                             or context.policy.allows("docs.read", str(path)))


def _part(context: ToolContext, given: str) -> str:
    """The chip: as given, or from the project being worked in."""
    if given.strip():
        found = subject_of(given)
        return found.name if found is not None else given.strip().upper()
    if context.workspace:
        ioc = cubemx.project_file(Path(context.workspace))
        if ioc is not None and _may_read(context)(ioc):
            name = cubemx.settings(ioc).get("Mcu.UserName", "")
            if name:
                return name
    raise ToolError("say which chip, such as STM32G474RE, or work in its CubeMX project")


# -- boards -------------------------------------------------------------------------------------


def _run_list(arguments: dict, context: ToolContext) -> ToolResult:
    lines = []
    try:
        found = boards.probes()
        lines += [f"ST-LINK {p.serial or '?'} on {p.board or 'an unnamed board'}"
                  + (f" (firmware {p.firmware})" if p.firmware else "") for p in found]
        if not found:
            lines.append("No ST-LINK is connected.")
    except boards.BoardError as exc:
        lines.append(f"ST-LINKs could not be listed: {exc}")
    try:
        lines += [f"Serial port {p.name}: {p.description}" for p in boards.ports()]
    except boards.BoardError as exc:
        lines.append(str(exc))
    return ToolResult.success("\n".join(lines))


list_boards = Tool(
    name="list_boards",
    summary="List the boards plugged in: ST-LINK probes and serial ports.",
    parameters=(),
    requires=(Requirement("device.read"),),
    run=_run_list,
)


def _run_serial(arguments: dict, context: ToolContext) -> ToolResult:
    port = str(arguments["port"]).strip().upper()
    try:
        said = boards.listen(port, int(arguments.get("baud") or 115200),
                             float(arguments.get("seconds") or 5))
    except boards.BoardError as exc:
        return ToolResult.failure(str(exc))
    if not said.strip():
        return ToolResult.success(f"{port} said nothing in that time. Check the baud rate, "
                                  "and that the board is running and printing.")
    return ToolResult.success(f"What {port} said:\n\n{said}")


read_serial = Tool(
    name="read_serial",
    summary="Read what a board prints on a serial port, for a few seconds.",
    parameters=(Parameter("port", "string", "The port, such as COM6."),
                Parameter("baud", "integer", "Baud rate.", required=False, default=115200),
                Parameter("seconds", "number", "How long to listen, up to 30.",
                          required=False, default=5)),
    requires=(Requirement("device.read"),),
    run=_run_serial,
)


def _run_register(arguments: dict, context: ToolContext) -> ToolResult:
    spec = str(arguments["register"]).strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*(\[\d+\])?", spec):
        raise ToolError("name a register as PERIPHERAL.REGISTER, such as SPI1.CR1")
    part = _part(context, str(arguments.get("chip") or ""))
    header = registers.header_for(part, _allowed_folders(context))
    if header is None or not _may_read(context)(header):
        return ToolResult.failure(
            f"The {part}'s device header (CMSIS) is not in a folder Akira may read. Add the "
            "vendor's firmware package, such as STM32CubeG4, in Library → Documents.")
    try:
        mapped = registers.DeviceMap.from_header(header.read_text(encoding="utf-8",
                                                                  errors="replace"))
        peripheral, register, address = mapped.find(spec)
    except (OSError, KeyError) as exc:
        return ToolResult.failure(str(exc).strip("'\""))
    try:
        (value,) = boards.read_words(address, 1)
    except boards.BoardError as exc:
        return ToolResult.failure(str(exc))
    if register.size < 4:
        value &= (1 << (register.size * 8)) - 1
    return ToolResult.success(registers.described(spec, register, address, value)
                              + f"\n\n(From {header.name}, read while the program ran.)")


read_register = Tool(
    name="read_register",
    summary=("Read a register of the chip on the board while it runs, by name such as "
             "SPI1.CR1, and say what each of its fields is set to."),
    parameters=(Parameter("register", "string", "PERIPHERAL.REGISTER, such as SPI1.CR1."),
                Parameter("chip", "string", "The chip, such as STM32G474RE; the project's "
                                            "own when left out.", required=False)),
    requires=(Requirement("device.read"),),
    run=_run_register,
)


def _image(arguments: dict) -> Path:
    path = real(arguments["path"])
    if path.is_dir():
        built = sorted([*path.glob("build/*/*.elf"), *path.glob("build/*.elf")],
                       key=lambda p: p.stat().st_mtime)
        if not built:
            raise ToolError(f"no built program (.elf) in {path}: build it first")
        path = built[-1]
    return path


#: In `ToolContext.extra`: the program the person was shown, as it was then. Given a
#: folder, the newest build is chosen; chosen again after the question, a build that
#: finished meanwhile would have been written instead of the one said yes to.
SHOWN = "flash_image"


def _stamp(image: Path) -> tuple[str, int, int]:
    found = image.stat()
    return str(image), found.st_size, found.st_mtime_ns


def _describe_flash(arguments: dict, context: ToolContext) -> str:
    image = _image(arguments)
    context.extra.pop(SHOWN, None)
    try:
        context.extra[SHOWN] = _stamp(image)
        size = f"{image.stat().st_size / 1024:.0f} KB file"
    except OSError:
        size = "file not found"
    return (f"Program the board with\n{image}\n({size})\n\nThe program on the board now "
            "is replaced, and the board restarts running this one.")


def _run_flash(arguments: dict, context: ToolContext) -> ToolResult:
    shown = context.extra.pop(SHOWN, None)
    image = Path(shown[0]) if shown else _image(arguments)
    if shown:
        try:
            now = _stamp(image)
        except OSError:
            now = None
        if now != shown:
            return ToolResult.failure(
                f"{image.name} changed after the person was asked (a build may have "
                "finished), so the board was not programmed. Ask again to write the new one.")
    try:
        said = boards.flash(image)
    except boards.BoardError as exc:
        return ToolResult.failure(f"The board was not programmed: {exc}")
    return ToolResult.success(f"Programmed the board with {image.name}, verified, and "
                              f"restarted it.\n\n{said}")


flash_firmware = Tool(
    name="flash_firmware",
    summary=("Write a built program (.elf, .hex or .bin, or a project folder's newest "
             "build) to the board, replacing what is on it. Asks the person every time."),
    parameters=(Parameter("path", "string", "The built program, or the project folder."),),
    requires=(Requirement("device.write"), Requirement("files.read", scope_from="path")),
    reversible=False,
    run=_run_flash,
    describe=_describe_flash,
)


def _describe_generate(arguments: dict, context: ToolContext) -> str:
    folder = real(arguments["path"])
    ioc = cubemx.project_file(folder)
    return (f"Generate the code of {ioc.name if ioc else 'this project'} again with "
            f"STM32CubeMX, in\n{folder}\n\nThe files CubeMX makes are written again; what is "
            "between USER CODE lines is kept.")


def _run_generate(arguments: dict, context: ToolContext) -> ToolResult:
    try:
        return ToolResult.success(cubemx.generate(real(arguments["path"])))
    except cubemx.CubeMXError as exc:
        return ToolResult.failure(str(exc))


generate_cubemx_code = Tool(
    name="generate_cubemx_code",
    summary=("Generate an STM32CubeMX project's code again from its .ioc, as Generate Code "
             "does, after changing the .ioc. Asks the person first."),
    parameters=(Parameter("path", "string", "The project's folder, where its .ioc is."),),
    requires=(Requirement("shell.run", scope_from="path"),),
    reversible=False,
    run=_run_generate,
    describe=_describe_generate,
)


# -- what the vendor's own files say ------------------------------------------------------------


def _run_pins(arguments: dict, context: ToolContext) -> ToolResult:
    asked = " ".join(str(arguments.get(k) or "") for k in ("board", "pins", "signals"))
    board = pin_facts.board_of(str(arguments.get("board") or "")) or pin_facts.board_of(asked)
    part = board.part if board is not None else _part(context, str(arguments.get("board") or ""))
    chip = pin_facts.chip_pins([real(arguments["folder"])], _may_read(context), part, board)
    named = pin_facts.pins_named(str(arguments.get("pins") or ""), board)
    lines = []
    facts = pin_facts.facts(board, chip, named, tuple(
        t.lower() for t in re.findall(r"[A-Za-z]+", str(arguments.get("signals") or ""))
        if t.lower() in ("spi", "i2c", "uart", "usart", "lpuart", "tim", "adc", "dac", "can",
                         "fdcan")) or ("spi", "i2c", "usart", "adc", "tim"))
    if facts:
        lines.append(facts)
    if chip is not None:
        for signal in re.findall(r"\b[A-Z]+\d*_[A-Z0-9]+\b", str(arguments.get("signals") or "").upper()):
            where = chip.pins_for(signal)
            lines.append(f"{signal}: " + (" or ".join(where) if where else "on no pin of "
                                          f"the {part}"))
    if chip is None:
        lines.append("STM32CubeMX's chip database is not in that folder, so what each pin "
                     "can carry is not known here. Give STM32CubeMX's folder, or its db folder.")
    return ToolResult.success("\n".join(lines) or "Nothing was found for that.")


stm32_pins = Tool(
    name="stm32_pins",
    summary=("Look up pins: a Nucleo board's connector (D13 is PA5), what each pin can carry, "
             "and which pins carry a signal such as SPI1_SCK."),
    parameters=(Parameter("folder", "string", "STM32CubeMX's folder, or its db folder."),
                Parameter("board", "string", "The board or chip, such as NUCLEO-G474RE.",
                          required=False),
                Parameter("pins", "string", "Pins or connector names, such as D13 D11 PB6.",
                          required=False),
                Parameter("signals", "string", "Signals or buses, such as SPI1_SCK or i2c.",
                          required=False)),
    requires=(Requirement("files.read", scope_from="folder"),),
    run=_run_pins,
)


_INDEX = HeaderIndex()


def _run_names(arguments: dict, context: ToolContext) -> ToolResult:
    words = [w.upper() for w in re.findall(r"[A-Za-z0-9]+", str(arguments["words"]))]
    if not words:
        raise ToolError("give words to look for, such as SPI FIRSTBIT")
    part = _part(context, str(arguments.get("chip") or ""))
    subject = subject_of(part)
    family = subject.family if subject is not None else ""
    headers = _INDEX.headers([real(arguments["folder"])], _may_read(context))
    if family:
        headers = family_headers(headers, family)
    if not headers:
        return ToolResult.failure(f"No {part} library headers are in that folder. Give the "
                                  "vendor's firmware package, such as STM32Cube_FW_G4.")
    found: dict[str, str] = {}
    for header in headers:
        for name in header.symbols:
            upper = name.upper()
            if all(w in upper for w in words):
                found.setdefault(name, header.functions.get(name, "") or header.path.name)
        if len(found) > 200:
            break
    if not found:
        return ToolResult.success(f"No name in the {part}'s library has all of: "
                                  + " ".join(words) + ". Try fewer words.")
    shown = sorted(found.items(), key=lambda kv: (len(kv[0]), kv[0]))[:60]
    return ToolResult.success(f"Names in the {part}'s own library with "
                              + " ".join(words) + ":\n"
                              + "\n".join(f"{name}  ({where})" for name, where in shown)
                              + (f"\n… and {len(found) - 60} more" if len(found) > 60 else ""))


find_vendor_names = Tool(
    name="find_vendor_names",
    summary=("Find exact names in the chip vendor's library (HAL, LL, CMSIS) that contain "
             "all the given words, with each function's declaration."),
    parameters=(Parameter("folder", "string", "The vendor's firmware package, such as "
                                              "STM32Cube_FW_G4_V1.6.3."),
                Parameter("words", "string", "Words the names contain, such as SPI FIRSTBIT."),
                Parameter("chip", "string", "The chip, such as STM32G474RE; the project's "
                                            "own when left out.", required=False)),
    requires=(Requirement("files.read", scope_from="folder"),),
    run=_run_names,
)


ALL = (list_boards, read_serial, read_register, flash_firmware, generate_cubemx_code,
       stm32_pins, find_vendor_names)
