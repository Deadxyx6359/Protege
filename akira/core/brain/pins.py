"""Which pin is which: a board's connector, and what each pin of a chip can be.

Asked to wire a display to D13, D11 and D10 of a Nucleo-G474RE, the chat model
read them as PA13, PA11 and PA10 and gave a pin plan for SPI2. A model does not
hold a board's pin map or a chip's alternate functions, and an answer that is
wrong about either is wired that way. So for a question naming a board or a
chip, these come from files and not from memory:

  * **A board's connector:** the Arduino-style names on a Nucleo board (D0 to
    D15, A0 to A5) and the chip pin behind each. Not on this computer in any
    file ST ships, so held here for the boards whose map has been checked
    against a published one (`BOARDS`), with where it came from.
  * **What a pin can be, and what is already on it:** from STM32CubeMX's own
    database, when the person has given Akira its folder. Every pin of the
    chip and the signals it can carry (`SPI1_SCK` on PA5 or PB3), the chip's
    peripherals, and, from the board's file, what the board itself uses a pin
    for (the debugger's SWO on PB3, the ST-LINK serial port on PA2 and PA3).

Before an answer, the pins the question names are given with all of that.
After it, a pin said to be a connector name it is not, or given a signal it
cannot carry, is named under the answer.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

# -- boards -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Board:
    name: str
    part: str
    """The chip on it, as far as its name says: STM32G474RE."""
    header: dict[str, str]
    """Connector name to chip pin: D13 to PA5."""
    uses: dict[str, str]
    """Pins the board itself uses, and for what."""
    source: str


BOARDS = {
    "NUCLEO-G474RE": Board(
        name="NUCLEO-G474RE",
        part="STM32G474RE",
        header={
            "D0": "PC5", "D1": "PC4", "D2": "PA10", "D3": "PB3", "D4": "PB5", "D5": "PB4",
            "D6": "PB10", "D7": "PA8", "D8": "PA9", "D9": "PC7", "D10": "PB6", "D11": "PA7",
            "D12": "PA6", "D13": "PA5", "D14": "PB9", "D15": "PB8",
            "A0": "PA0", "A1": "PA1", "A2": "PA4", "A3": "PB0", "A4": "PC1", "A5": "PC0",
        },
        uses={
            "PA5": "the green user LED, LD2 (in STM32CubeMX, untick LD2 under Bsp, or set "
                   "PA5 to Reset_State, to free it)",
            "PC13": "the blue user button, B1",
            "PA2": "the ST-LINK's virtual serial port (LPUART1 TX)",
            "PA3": "the ST-LINK's virtual serial port (LPUART1 RX)",
            "PA13": "the debugger (SWDIO)",
            "PA14": "the debugger (SWCLK)",
            "PB3": "the debugger's trace output (SWO)",
            "PB8": "BOOT0, read at reset unless the option bytes turn that off (nSWBOOT0 = 0)",
        },
        # Arm Mbed OS, targets/TARGET_STM/TARGET_STM32G4/TARGET_STM32G474xE/
        # TARGET_NUCLEO_G474RE/PinNames.h (ARDUINO_UNO_*, LED1, BUTTON1, CONSOLE_*),
        # agreeing with ST's own board file in STM32CubeMX for the debugger and
        # serial pins, and with the ST examples for D10 and D13.
        source="the board's published pin map (Mbed OS PinNames.h for NUCLEO_G474RE)",
    ),
}

_BOARD = re.compile(r"\bnucleo[-\s_]?([a-z]\d{3}[a-z]{2})\b", re.IGNORECASE)
_CONNECTOR = re.compile(r"\b(D1[0-5]|D[0-9]|A[0-5])\b")
_PIN = re.compile(r"\bP([A-K])(1[0-5]|[0-9])\b")


def board_of(text: str) -> Board | None:
    found = _BOARD.search(text)
    return BOARDS.get(f"NUCLEO-{found.group(1).upper()}") if found else None


def pins_named(text: str, board: Board | None) -> list[str]:
    """The chip pins \a text names, directly (PA5) or by the board's connector (D13)."""
    out: list[str] = []
    for found in re.finditer(rf"{_CONNECTOR.pattern}|{_PIN.pattern}", text):
        if found.group(1):
            pin = board.header.get(found.group(1)) if board is not None else None
        else:
            pin = f"P{found.group(2)}{found.group(3)}"
        if pin and pin not in out:
            out.append(pin)
    return out


# -- what a chip's pins can be ------------------------------------------------------------------


@dataclass
class ChipPins:
    """One chip's pins, from STM32CubeMX's database."""

    part: str
    signals: dict[str, list[str]] = field(default_factory=dict)
    """Pin to the signals it can carry: PA5 to [..., SPI1_SCK, TIM2_CH1, ...]."""
    instances: set[str] = field(default_factory=set)
    """The peripherals the chip has: SPI1, ADC1, LPUART1, ..."""
    board_uses: dict[str, str] = field(default_factory=dict)
    """From the board's own file, when there is one: pin to what the board puts on it."""

    def pins_for(self, signal: str) -> list[str]:
        return [pin for pin, carried in self.signals.items() if signal in carried]

    @property
    def all_signals(self) -> set[str]:
        return set().union(*self.signals.values()) if self.signals else set()


def _pattern(name: str) -> list[set[str] | None]:
    """A database file's part pattern: STM32G474R(B-C-E)Tx to one set per letter
    (None for x, any letter)."""
    out: list[set[str] | None] = []
    for found in re.finditer(r"\(([A-Z0-9](?:-[A-Z0-9])*)\)|(.)", name):
        if found.group(1):
            out.append(set(found.group(1).split("-")))
        else:
            letter = found.group(2)
            out.append(None if letter == "x" else {letter.upper()})
    return out


def _matches(part: str, pattern: list[set[str] | None]) -> bool:
    part = part.upper()
    if len(part) > len(pattern):
        return False
    return all(choice is None or letter in choice for letter, choice in zip(part, pattern))


def _databases(folders: Iterable[Path]) -> list[Path]:
    """STM32CubeMX's `db` folders under \a folders: its install folder, or `db` itself."""
    found: list[Path] = []
    for folder in folders:
        for candidate in (folder / "db", folder, folder.parent):
            if (candidate / "mcu").is_dir() and candidate not in found:
                found.append(candidate)
                break
    return found


_cache: dict[str, tuple[float, ChipPins]] = {}


def chip_pins(folders: Iterable[Path], may_read: Callable[[Path], bool], part: str,
              board: Board | None = None) -> ChipPins | None:
    """\a part's pins from STM32CubeMX's database in \a folders, or None.

    Only a part named down to its package (STM32G474RE, not STM32G474): pins
    are numbered per package.
    """
    part = part.upper()
    if not re.fullmatch(r"STM32[A-Z]\d{3}[A-Z]{2}\w*", part):
        return None
    for database in _databases(folders):
        mcu = database / "mcu"
        try:
            names = [n for n in os.listdir(mcu) if n.upper().startswith(part[:9])
                     and n.lower().endswith(".xml")]
        except OSError:
            continue
        chosen = [n for n in names if _matches(part, _pattern(n[:-4]))]
        if len(chosen) != 1:
            continue
        path = mcu / chosen[0]
        if not may_read(path):
            continue
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        held = _cache.get(str(path))
        if held is None or held[0] != stamp:
            pins = _read_chip(path, part)
            if pins is None:
                continue
            _cache[str(path)] = (stamp, pins)
            held = _cache[str(path)]
        pins = held[1]
        if board is not None and not pins.board_uses:
            pins.board_uses = _board_uses(database, board, may_read)
        return pins
    return None


def _read_chip(path: Path, part: str) -> ChipPins | None:
    try:
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError):
        return None
    pins = ChipPins(part)
    for element in root:
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "IP" and element.get("InstanceName"):
            pins.instances.add(element.get("InstanceName"))
        elif tag == "Pin" and element.get("Type") == "I/O":
            # "PB8-BOOT0" and "PC14-OSC32_IN" are PB8 and PC14.
            name = re.split(r"[-/ ]", element.get("Name", ""))[0]
            signals = [s.get("Name") for s in element
                       if s.tag.rsplit("}", 1)[-1] == "Signal" and s.get("Name")
                       and s.get("Name") != "GPIO"]
            pins.signals[name] = signals
    return pins if pins.signals else None


def _board_uses(database: Path, board: Board, may_read: Callable[[Path], bool]) -> dict[str, str]:
    """What the board's own STM32CubeMX file puts on its pins: PB3 to T_SWO."""
    boards = database / "plugins" / "boardmanager" / "boards"
    try:
        names = [n for n in os.listdir(boards)
                 if f"_{board.name}_".upper() in n.upper() and n.endswith("_Board.ioc")]
    except OSError:
        return {}
    uses: dict[str, str] = {}
    for name in names[:1]:
        path = boards / name
        if not may_read(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for found in re.finditer(r"^(P[A-K]\d{1,2})[^.\n]*\.GPIO_Label=(.+)$", text, re.MULTILINE):
            uses[found.group(1)] = found.group(2).strip()
    return uses


# -- before and after an answer ------------------------------------------------------------------


def facts(board: Board | None, chip: ChipPins | None, pins: list[str],
          topics: tuple[str, ...]) -> str:
    """The pin facts for a question, for the prompt. "" when there are none."""
    lines: list[str] = []
    if board is not None:
        named = [(name, pin) for name, pin in board.header.items() if pin in pins]
        if named:
            lines.append(f"On the {board.name}, from {board.source}: "
                         + ", ".join(f"{name} is {pin}" for name, pin in named)
                         + ". Use these chip pins; a connector name is not a pin number "
                         "(D13 is not PA13).")
    for pin in pins:
        said = []
        use = (board.uses.get(pin) if board is not None else None) or (
            chip.board_uses.get(pin) if chip is not None else None)
        if use:
            said.append(f"on this board it is also {use}")
        if chip is not None and pin in chip.signals:
            carried = chip.signals[pin]
            wanted = [s for s in carried if any(s.upper().startswith(t.upper()) for t in topics)]
            if wanted:
                said.append("it can be " + ", ".join(wanted))
            elif topics:
                said.append(f"it has no {' or '.join(t.upper() for t in topics)} signal, so here "
                            "it can only be a plain GPIO pin, such as an output for a chip select")
            else:
                said.append("it can be, among others, " + ", ".join(carried[:12]))
        if said:
            lines.append(f"{pin}: " + "; ".join(said) + ".")
    if chip is not None and pins:
        # Where each peripheral the question needs can go, for an instance a
        # named pin can carry: SPI1's clock is on PA5 or PB3.
        instances = sorted({s.split("_")[0] for pin in pins for s in chip.signals.get(pin, [])
                            if any(s.upper().startswith(t.upper()) for t in topics)})
        for instance in instances[:3]:
            roles = sorted({s for s in chip.all_signals if s.startswith(instance + "_")})
            placed = [f"{s} on {' or '.join(chip.pins_for(s))}" for s in roles]
            if placed:
                lines.append(f"{instance}'s pins on this chip: " + "; ".join(placed) + ".")
        if "spi" in topics:
            lines.append("A pin used as chip select can be any free pin set as a GPIO output; "
                         "it need not be the peripheral's own NSS pin.")
    if not lines:
        return ""
    where = "STM32CubeMX's database on this computer" if chip is not None else "the board map"
    return f"Pins, from {where}:\n" + "\n".join(lines)


#: A wire, as a person describes one: "CLK to D13", "DI -> PA7", "CS on D10".
_WIRE = re.compile(
    r"\b(SCLK|SCK|CLK|SDI|DIN|DI|MOSI|SDO|DOUT|MISO|SCS|NSS|CS|SS|SDA|SCL)\b"
    r"\s*(?:pin\s*)?(?:to|->|→|=|on|:|goes to|is on|connected to)\s*(?:the\s+)?"
    r"(?:nucleo'?s?\s+|board'?s?\s+)?(?:pin\s+)?(D1[0-5]|D[0-9]|A[0-5]|P[A-K](?:1[0-5]|[0-9]))\b",
    re.IGNORECASE)

#: What each wire needs of the pin it is on: the end of a signal's name, or a plain GPIO.
_ROLES = {"SCLK": "SCK", "SCK": "SCK", "CLK": "SCK", "SDI": "MOSI", "DIN": "MOSI",
          "DI": "MOSI", "MOSI": "MOSI", "SDO": "MISO", "DOUT": "MISO", "MISO": "MISO",
          "SDA": "SDA", "SCL": "SCL", "SCS": "", "NSS": "", "CS": "", "SS": ""}


def wiring(text: str, board: Board | None, chip: ChipPins | None) -> str:
    """The person's wiring, as described in \a text, checked against the chip: "" when
    there is none, or nothing to check it with.

    Given the facts pin by pin, the chat model still told a person whose wiring
    was right to move chip select to the SPI's own NSS pin. So the verdict is
    worked out here and said outright.
    """
    if chip is None:
        return ""
    wires: list[tuple[str, str, str]] = []
    for found in _WIRE.finditer(text):
        name, place = found.group(1).upper(), found.group(2).upper()
        pin = board.header.get(place) if board is not None and place.startswith(("D", "A")) \
            else place
        if pin and pin in chip.signals and (name, place, pin) not in wires:
            wires.append((name, place, pin))
    if not wires:
        return ""
    lines: list[str] = []
    buses: list[set[str]] = []
    good = True
    for name, place, pin in wires:
        where = f"{place} ({pin})" if place != pin else pin
        role = _ROLES[name]
        use = (board.uses.get(pin) if board is not None else None) or chip.board_uses.get(pin)
        also = f" On this board it is also {use}." if use else ""
        if not role:
            lines.append(f"{name} on {where}: a chip select is a plain GPIO output that the code "
                         f"sets, so any free pin works, and {pin} is fine.{also}")
            continue
        carried = [s for s in chip.signals[pin] if s.endswith("_" + role)]
        if carried:
            buses.append({s.split("_")[0] for s in carried})
            lines.append(f"{name} on {where}: right, {pin} can be "
                         f"{' or '.join(carried)}.{also}")
        else:
            good = False
            where_else = sorted({p for p, carried_by in chip.signals.items()
                                 if any(s.endswith("_" + role) for s in carried_by)})
            lines.append(f"{name} on {where}: {pin} cannot be any {role} signal; it would "
                         f"have to move to one of {', '.join(where_else[:8])}.")
    shared = set.intersection(*buses) if buses else set()
    if good and buses and not shared:
        good = False
        lines.append("Those pins are on different peripherals, so they cannot work together.")
    verdict = (f"The wiring works, on {sorted(shared)[0]}: tell the person so, and do not tell "
               "them to change it." if good and shared else
               "The wiring works." if good else
               "The wiring needs changing, as said above.")
    return "The person's wiring, checked against the chip:\n" + "\n".join(lines) + "\n" + verdict


_SAID_AS = re.compile(rf"{_CONNECTOR.pattern}\W{{0,3}}(?:\(|is|=|→|->|/|:|to|on)?\s*\(?\s*"
                      rf"{_PIN.pattern}|{_PIN.pattern}\s*\(\s*{_CONNECTOR.pattern}\s*\)")
_SIGNAL = re.compile(r"\b((?:[A-Z]+[0-9]*)_(?:[A-Z0-9]+))\b")
_NOT_USED = re.compile(r"\b(?:not used|unused|not needed|not required|instead|rather than|"
                       r"(?:do not|don't|doesn't|does not) (?:use|need))\b", re.IGNORECASE)


def check(reply: str, board: Board | None, chip: ChipPins | None) -> list[str]:
    """What \a reply says of pins that the board map or the chip's database contradicts."""
    problems: list[str] = []
    if board is not None:
        for found in _SAID_AS.finditer(reply):
            if found.group(1):
                name, pin = found.group(1), f"P{found.group(2)}{found.group(3)}"
            else:
                name, pin = found.group(6), f"P{found.group(4)}{found.group(5)}"
            real = board.header.get(name)
            note = f"{name} is {real} on the {board.name}, not {pin}"
            if real and real != pin and note not in problems:
                problems.append(note)
    if chip is not None:
        known = chip.all_signals
        for line in reply.splitlines():
            if _NOT_USED.search(line):
                # "NSS (SPI1_NSS): not used, PB6 is the chip select" pairs nothing.
                continue
            pins = {f"P{m.group(1)}{m.group(2)}" for m in _PIN.finditer(line)}
            if board is not None:
                pins |= {board.header[m.group(1)] for m in _CONNECTOR.finditer(line)
                         if m.group(1) in board.header}
            pins &= set(chip.signals)
            if not pins:
                continue
            for signal in {m.group(1) for m in _SIGNAL.finditer(line)} & known:
                if not any(signal in chip.signals[pin] for pin in pins):
                    where = chip.pins_for(signal)
                    note = (f"{signal} cannot be on {', '.join(sorted(pins))}; on the "
                            f"{chip.part} it is on {' or '.join(where)}")
                    if note not in problems:
                        problems.append(note)
    return problems
