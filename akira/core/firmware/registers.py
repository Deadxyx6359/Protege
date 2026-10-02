"""A chip's registers by name, from its own CMSIS device header.

`SPI1.CR1` is turned into an address, and the value read back into its bit
fields, from the header ST ships for the chip (stm32g474xx.h): the peripherals'
base addresses (`SPI1_BASE`), each kind of peripheral's register layout (the
`SPI_TypeDef` struct, field by field), and each register's fields (`SPI_CR1_BR_Pos`,
`SPI_CR1_BR_Msk` and the comment that says what BR is). Nothing about a chip is
held here: a part whose header is in the library can be read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_COMMENT_BLOCK = re.compile(r"/\*(?!!<).*?\*/", re.DOTALL)
_DEFINE = re.compile(r"^\s*#\s*define\s+(\w+)[ \t]+(.+?)\s*$", re.MULTILINE)
_STRUCT = re.compile(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+_TypeDef)\s*;", re.DOTALL)
_FIELD = re.compile(r"^\s*(?:__IO|__I|__O|volatile|const|\s)*\s*(uint8_t|uint16_t|uint32_t)\s+"
                    r"(\w+)\s*(?:\[\s*(\w+)\s*\])?\s*;", re.MULTILINE)
_INSTANCE = re.compile(r"\(\s*\(\s*(\w+_TypeDef)\s*\*\s*\)\s*(\w+)\s*\)")
_SIZES = {"uint8_t": 1, "uint16_t": 2, "uint32_t": 4}
_NUMBER = re.compile(r"\A(0[xX][0-9A-Fa-f]+|\d+)[uUlL]*\Z")


@dataclass(frozen=True)
class Field:
    name: str
    position: int
    width: int
    meaning: str = ""


@dataclass
class Register:
    name: str
    offset: int
    size: int
    fields: list[Field] = field(default_factory=list)


@dataclass
class Peripheral:
    name: str
    kind: str
    base: int
    registers: dict[str, Register]


def _number(text: str, macros: dict[str, str], depth: int = 0) -> int | None:
    """An address expression from the header: (PERIPH_BASE + 0x00010000UL)."""
    if depth > 12:
        return None
    text = text.split("/*", 1)[0].strip()
    while text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    total, sign = 0, 1
    for token in re.split(r"\s*([+-])\s*", text):
        if token == "+":
            sign = 1
            continue
        if token == "-":
            sign = -1
            continue
        found = _NUMBER.match(token)
        if found:
            value = int(found.group(1), 0)
        elif re.fullmatch(r"\w+", token) and token in macros:
            value = _number(macros[token], macros, depth + 1)
            if value is None:
                return None
        else:
            return None
        total += sign * value
    return total


class DeviceMap:
    """The peripherals, registers and fields one device header declares."""

    def __init__(self, peripherals: dict[str, Peripheral]) -> None:
        self.peripherals = peripherals

    @classmethod
    def from_header(cls, text: str) -> "DeviceMap":
        meanings = {name: comment.strip() for name, comment in re.findall(
            r"^\s*#\s*define\s+(\w+)\s+\w+_Msk\s*/\*!<\s*(.*?)\s*\*/", text, re.MULTILINE)}
        clean = _COMMENT_BLOCK.sub(" ", text)
        macros = {name: value for name, value in _DEFINE.findall(clean)}
        layouts: dict[str, list[tuple[str, int, int]]] = {}
        for body, kind in _STRUCT.findall(clean):
            offset, registers, known = 0, [], True
            for line in body.splitlines():
                line = line.split("/*", 1)[0]
                if not line.strip():
                    continue
                found = _FIELD.match(line)
                if found is None:
                    # A field of a type not sized here: what follows cannot be placed.
                    known = False
                    break
                size, name, count = _SIZES[found.group(1)], found.group(2), found.group(3)
                n = int(macros.get(count, count), 0) if count else 1
                if not name.upper().startswith("RESERVED"):
                    for i in range(n):
                        registers.append((f"{name}[{i}]" if count else name,
                                          offset + i * size, size))
                offset += size * n
            if registers and known:
                layouts[kind] = registers
        peripherals: dict[str, Peripheral] = {}
        for name, value in macros.items():
            found = _INSTANCE.fullmatch(value.strip())
            if not found or found.group(1) not in layouts:
                continue
            base = _number(found.group(2), macros)
            if base is None:
                continue
            kind = found.group(1)
            registers = {r: Register(r, off, size) for r, off, size in layouts[kind]}
            peripherals[name] = Peripheral(name, kind, base, registers)
        mapped = cls(peripherals)
        mapped._fields(macros, meanings)
        return mapped

    def _fields(self, macros: dict[str, str], meanings: dict[str, str]) -> None:
        positions = {name[:-4]: value for name, value in macros.items() if name.endswith("_Pos")}
        for peripheral in self.peripherals.values():
            stems = _stems(peripheral)
            for register in peripheral.registers.values():
                bare = register.name.split("[", 1)[0]
                for stem in stems:
                    lead = f"{stem}_{bare}_"
                    found = [(n, p) for n, p in positions.items() if n.startswith(lead)]
                    if not found:
                        continue
                    for name, position in found:
                        mask = macros.get(name + "_Msk", "")
                        width_match = re.match(r"\(\s*(0x[0-9A-Fa-f]+|\d+)UL\s*<<", mask)
                        if not width_match:
                            continue
                        pos = _number(position, macros)
                        if pos is None:
                            continue
                        width = int(width_match.group(1), 0).bit_length()
                        register.fields.append(Field(name[len(lead):], pos, width,
                                                     meanings.get(name, "")))
                    register.fields.sort(key=lambda f: f.position)
                    break

    def find(self, spec: str) -> tuple[Peripheral, Register, int]:
        """`SPI1.CR1`, `GPIOA.ODR` or `GPIOA.AFR[1]`: the peripheral, the register and
        its address. Raises `KeyError` naming what is there instead."""
        name, _, register = spec.strip().upper().partition(".")
        peripheral = self.peripherals.get(name)
        if peripheral is None:
            close = sorted(p for p in self.peripherals if p.startswith(name.rstrip("0123456789")))
            raise KeyError(f"no peripheral {name}" + (f"; there is {', '.join(close[:8])}"
                                                      if close else ""))
        found = peripheral.registers.get(register)
        if found is None:
            raise KeyError(f"{name} has no register {register}; it has "
                           + ", ".join(list(peripheral.registers)[:24]))
        return peripheral, found, peripheral.base + found.offset

    @staticmethod
    def decode(register: Register, value: int) -> list[tuple[Field, int]]:
        return [(f, (value >> f.position) & ((1 << f.width) - 1)) for f in register.fields]


def _stems(peripheral: Peripheral) -> list[str]:
    """What a peripheral's bit names begin with: SPI_TypeDef's are SPI_CR1_..., and
    ADC_Common_TypeDef's ADC_CCR_..., so ADC_COMMON then ADC."""
    kind = peripheral.kind[:-len("_TypeDef")].upper()
    stems = [kind]
    if "_" in kind:
        stems.append(kind.split("_", 1)[0])
    bare = peripheral.name.rstrip("0123456789")
    if bare not in stems:
        stems.append(bare)
    return stems


def header_for(part: str, folders: Iterable[Path]) -> Path | None:
    """The CMSIS device header for \a part (STM32G474RE: stm32g474xx.h) in \a folders."""
    found = re.match(r"STM32([A-Z]\d{3})", part.upper())
    if not found:
        return None
    wanted = f"stm32{found.group(1).lower()}xx.h"
    for folder in folders:
        for candidate in Path(folder).rglob(wanted):
            if "CMSIS" in candidate.parts or "Include" in candidate.parts:
                return candidate
    return None


def described(spec: str, register: Register, address: int, value: int) -> str:
    """A read register, in words: `SPI1.CR1 (0x40013000) = 0x0000037C`, then each field."""
    lines = [f"{spec.upper()} (0x{address:08X}) = 0x{value:0{register.size * 2}X}"]
    for each, field_value in DeviceMap.decode(register, value):
        meaning = f"  ({each.meaning})" if each.meaning else ""
        bits = (f"bit {each.position}" if each.width == 1
                else f"bits {each.position + each.width - 1}:{each.position}")
        lines.append(f"  {each.name} = {field_value}  [{bits}]{meaning}")
    return "\n".join(lines)
