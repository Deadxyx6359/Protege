"""Answering about a chip or a library from its own files, and saying when it could not.

Asked how to read an analog pin on an STM32 Nucleo-G474RE, the local coding
model wrote code for the STM32F4: `ADC_SAMPLETIME_480CYCLES`, `Rank = 1`, a clock
macro the G4 does not have. A 7B model does not hold the exact names of every
vendor library, and nothing it writes says which ones it made up. So for a
question that names a chip or board:

  * **Before it answers**, the vendor's own header files, in the folders the
    person gave Akira (the library, or a folder such as ST's STM32CubeG4
    package), are read for the names the question needs: the functions and
    constants of the peripheral it asks about. The model is told to use those.
  * **After it answers**, every library name in its code is looked up in the
    same headers. One that is not there is named under the answer, with the
    closest that are; many, and the answer is called unreliable. All found,
    and it says they were checked.
  * **With nothing to check against**, the answer starts by saying so: the
    names and pin numbers in it are from memory and may be wrong.

This does not make the model right. It makes it say where it could not be
checked, which is what a person needs to know before they trust it. Pin and
channel numbers are in datasheets, not headers: those come from the documents
the person added, found by the chat's ordinary search.
"""

from __future__ import annotations

import difflib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from akira.core import files
from akira.core.config import config_dir

#: What a question may be about: a part number, or a board that names one.
_STM32 = re.compile(r"\bSTM32\s?([A-Z])(\d)(\w*)", re.IGNORECASE)
_NUCLEO = re.compile(r"\bnucleo[-\s]?([A-Z])(\d)(\d{2}\w*)", re.IGNORECASE)
_OTHERS = (
    (re.compile(r"\bESP32(?:-?[A-Z]\d)?\b", re.IGNORECASE), "esp32"),
    (re.compile(r"\bESP8266\b", re.IGNORECASE), "esp8266"),
    (re.compile(r"\bRP2040\b|\bRP2350\b|\braspberry pi pico\b", re.IGNORECASE), "pico"),
    (re.compile(r"\bATmega\d+\w*|\bATtiny\d+\w*|\bArduino (?:Uno|Nano|Mega)\b", re.IGNORECASE),
     "avr"),
    (re.compile(r"\bnRF5\d{3,4}\b", re.IGNORECASE), "nrf5"),
    (re.compile(r"\bSAMD\d{2}\w*\b", re.IGNORECASE), "samd"),
)

#: A question's words, and the peripherals whose headers they need.
_TOPICS = (
    (r"\badc\b|analog|voltage|millivolt|\bmv\b", ("adc",)),
    (r"\bdac\b", ("dac",)),
    (r"\bgpio\b|\bpin\b|\bled\b|button", ("gpio",)),
    (r"\buart\b|\busart\b|serial|printf|\bcom port", ("uart", "usart")),
    (r"timer|\bpwm\b|\btim\d*\b", ("tim",)),
    (r"\bi2c\b|\biic\b", ("i2c",)),
    (r"\bspi\b", ("spi",)),
    (r"\bdma\b", ("dma",)),
    (r"clock|\brcc\b|\bpll\b", ("rcc",)),
    (r"interrupt|\bnvic\b|\bexti\b", ("cortex", "exti")),
    # CAN the bus, not "can" the word.
    (r"(?-i:\bCAN\b)|fdcan|can bus", ("fdcan", "can")),
    (r"\brtc\b|real.time clock", ("rtc",)),
    (r"op.?amp|\bpga\b", ("opamp",)),
    (r"comparator|\bcomp\b", ("comp",)),
    (r"\bflash\b|eeprom", ("flash",)),
    (r"\busb\b", ("pcd",)),
)

#: A folder of an SDK holds examples and tools too; their headers are not the library.
_SKIPPED_DIRS = frozenset({".git", "projects", "examples", "example", "utilities", "docs",
                           "build", "debug", "release", "__pycache__", "node_modules"})
_HEADER = frozenset({".h", ".hpp", ".hh"})
MAX_HEADERS = 20_000
MAX_HEADER_BYTES = 6_000_000
#: The most of the headers' names given to the model before it answers.
MAX_REFERENCE_CHARS = 7_000

_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)", re.MULTILINE)
_FUNCTION = re.compile(r"^[ \t]*(?:extern\s+|static\s+|__STATIC_INLINE\s+|inline\s+|__weak\s+)*"
                       r"[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*[;{]",
                       re.MULTILINE)
_TYPEDEF = re.compile(r"\}\s*([A-Za-z_]\w*)\s*;|typedef\s+[\w\s\*]+?\b([A-Za-z_]\w*)\s*;")
_ENUM = re.compile(r"\benum\b[^{;]*\{([^}]*)\}", re.DOTALL)
_ENUM_ITEM = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:=|,|$)", re.MULTILINE)
_COMMENT = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)

#: A name in an answer worth looking up: a library's, by its shape.
_NAME = re.compile(r"\b_{0,2}[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b")
_CODE_BLOCK = re.compile(r"```[^\n]*\n(.*?)(?:```|\Z)", re.DOTALL)
_INLINE = re.compile(r"`([^`\n]+)`")
_DEFINED_HERE = re.compile(r"#\s*define\s+([A-Za-z_]\w*)|"
                           r"^[ \t]*(?:static[ \t]+|const[ \t]+|volatile[ \t]+)*[A-Za-z_]\w*[ \t\*]+"
                           r"([A-Za-z_]\w*)[ \t]*(?:=|;|\[|\()", re.MULTILINE)


# -- what a question is about -------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """The chip or board a question names."""

    name: str
    """As the person might say it: "STM32G474", "ESP32"."""
    family: str
    """The key its headers are found by: "stm32g4", "esp32"."""


def subject_of(text: str) -> Subject | None:
    """The chip or board \a text is about, or None."""
    found = _STM32.search(text) or _NUCLEO.search(text)
    if found:
        letter, digit, rest = found.group(1).upper(), found.group(2), found.group(3).upper()
        return Subject(f"STM32{letter}{digit}{rest}", f"stm32{letter.lower()}{digit}")
    for pattern, family in _OTHERS:
        found = pattern.search(text)
        if found:
            return Subject(found.group(0), family)
    return None


def topics_of(text: str) -> tuple[str, ...]:
    """The peripherals \a text asks about, as header names spell them."""
    out: list[str] = []
    for pattern, names in _TOPICS:
        if re.search(pattern, text, re.IGNORECASE):
            out += [n for n in names if n not in out]
    return tuple(out)


# -- the headers --------------------------------------------------------------------------------


def symbols_in(text: str) -> set[str]:
    """The names a C header declares: macros, functions, types and enum members."""
    clean = _COMMENT.sub(" ", text)
    names = set(_DEFINE.findall(clean))
    names.update(_FUNCTION.findall(clean))
    for pair in _TYPEDEF.findall(clean):
        names.update(n for n in pair if n)
    for body in _ENUM.findall(clean):
        names.update(_ENUM_ITEM.findall(body))
    return {n for n in names if len(n) > 2}


@dataclass
class Header:
    path: Path
    symbols: set[str]
    functions: dict[str, str] = field(default_factory=dict)
    """A function's name and the line that declares it, for the model to read."""


class HeaderIndex:
    """The names declared in the headers under some folders. Cached on disk by file."""

    def __init__(self, cache: Path | None = None) -> None:
        self._cache_path = cache if cache is not None else config_dir() / "cache" / "headers.json"
        self._cache: dict[str, dict] | None = None

    def headers(self, folders: Iterable[Path], may_read: Callable[[Path], bool]) -> list[Header]:
        found: list[Header] = []
        cache = self._load()
        changed = False
        count = 0
        for folder in folders:
            for path in _walk(folder):
                count += 1
                if count > MAX_HEADERS:
                    break
                if not may_read(path):
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size > MAX_HEADER_BYTES:
                    continue
                key = str(path)
                held = cache.get(key)
                if held is None or held.get("mtime") != stat.st_mtime or held.get("size") != stat.st_size:
                    try:
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        continue
                    held = {"mtime": stat.st_mtime, "size": stat.st_size,
                            "symbols": sorted(symbols_in(text)),
                            "functions": _prototypes(text)}
                    cache[key] = held
                    changed = True
                found.append(Header(path, set(held["symbols"]), dict(held.get("functions", {}))))
        if changed:
            self._save(cache)
        return found

    def _load(self) -> dict[str, dict]:
        if self._cache is None:
            try:
                raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
                self._cache = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _save(self, cache: dict[str, dict]) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(cache), encoding="utf-8")
            files.replace(temporary, self._cache_path)
        except OSError:
            pass


def _walk(folder: Path) -> Iterable[Path]:
    try:
        for root, dirs, names in os.walk(folder):
            dirs[:] = [d for d in dirs if d.lower() not in _SKIPPED_DIRS]
            for name in names:
                if Path(name).suffix.lower() in _HEADER:
                    yield Path(root) / name
    except OSError:
        return


def _prototypes(text: str) -> dict[str, str]:
    clean = _COMMENT.sub(" ", text)
    out: dict[str, str] = {}
    for found in _FUNCTION.finditer(clean):
        name = found.group(1)
        if name in ("if", "while", "for", "switch", "return", "sizeof"):
            continue
        line = " ".join(found.group(0).split()).rstrip("{").strip()
        if len(line) <= 200:
            out.setdefault(name, line if line.endswith(";") else line + ";")
    return out


def family_headers(headers: list[Header], family: str) -> list[Header]:
    """The headers of \a family: an STM32 series' by their names, else by their folders."""
    if family.startswith("stm32"):
        mark = family + "xx"
        return [h for h in headers if mark in h.path.name.lower()
                or mark in str(h.path).lower().replace("\\", "/")]
    return [h for h in headers if family in str(h.path).lower()]


# -- before and after an answer ------------------------------------------------------------------


@dataclass
class Grounding:
    """What was found for one message, and how its answer is checked."""

    subject: Subject | None = None
    reference: str = ""
    """Added to the prompt for this turn: the library's own names, or that there are none."""
    headers: list[Header] = field(default_factory=list)
    documented: bool = False
    """Whether anything documents the subject: its headers, or a document passage naming it."""
    teaching: bool = False

    @property
    def banner(self) -> str:
        """Said before the answer when nothing could be checked."""
        if self.subject is None or self.documented:
            return ""
        return (f"**Not checked:** nothing on this computer documents the {self.subject.name}, "
                "so the names, settings and pin numbers below are from memory and may be "
                "wrong. Add its datasheet, and the vendor's library files, in Library → "
                "Documents, then ask again.\n\n")

    def check(self, reply: str) -> str:
        """A note on the library names in \a reply that its headers do not have, or ""."""
        if self.subject is None or not self.headers:
            return ""
        names = _names_in(reply)
        if not names:
            return ""
        known: set[str] = set().union(*(h.symbols for h in self.headers))
        firsts = {_first(n) for n in known}
        checked, missing = [], []
        registers: dict[str, set[str]] = {}
        for name in names:
            if "->" in name:
                # Judged by the peripheral's bit names; a peripheral the headers
                # do not know is not judged.
                instance, register = name.split("->")
                if instance not in registers:
                    registers[instance] = _registers(instance, known)
                if not registers[instance]:
                    continue
                checked.append(name)
                if register not in registers[instance]:
                    missing.append(name)
            elif _first(name) in firsts:
                checked.append(name)
                if name not in known:
                    missing.append(name)
        if not checked:
            return ""
        where = self.subject.name
        if not missing:
            return (f"\n\nChecked: the {len(checked)} {where} library "
                    f"name{'' if len(checked) == 1 else 's'} in this answer "
                    f"{'is' if len(checked) == 1 else 'are all'} in the library's own files on "
                    "this computer. Pin and channel numbers are not checked this way: compare "
                    "them with the datasheet.")
        lines = []
        for name in missing[:8]:
            if "->" in name:
                instance, register = name.split("->")
                close = [f"{instance}->{c}" for c in difflib.get_close_matches(
                    register, sorted(registers[instance]), n=2, cutoff=0.5)]
            else:
                close = _closest(name, known)
            lines.append(f"- `{name}`" + (" (the closest there: "
                                          + ", ".join(f"`{c}`" for c in close) + ")"
                                          if close else ""))
        more = len(missing) - len(lines)
        verdict = ("\n\nThis answer is not reliable as written: don't use it until those are "
                   "corrected." if len(missing) >= 3 or len(missing) * 4 >= len(checked) else "")
        return (f"\n\nCheck before using: {len(missing)} of the {len(checked)} {where} library "
                f"names in this answer are not in the library's files on this computer, so "
                "they are probably wrong:\n" + "\n".join(lines)
                + (f"\n- and {more} more" if more > 0 else "") + verdict)


class Grounder:
    """Finds, for a message, what the vendor's files say, and checks the answer after."""

    def __init__(self, folders: Callable[[], list[Path]],
                 may_read: Callable[[Path], bool],
                 index: HeaderIndex | None = None) -> None:
        self._folders = folders
        self._may_read = may_read
        self._index = index if index is not None else HeaderIndex()

    def __call__(self, message: str, found: str = "") -> Grounding:
        """What is known for \a message; \a found is what the chat's search turned up."""
        grounding = Grounding(teaching=teaching(message))
        subject = subject_of(message)
        if subject is None:
            return grounding
        grounding.subject = subject
        headers = family_headers(self._index.headers(self._folders(), self._may_read),
                                 subject.family)
        grounding.headers = headers
        # A passage from the person's documents that names the chip documents it:
        # "STM32G4" for any of the series, or the part itself.
        named = any(mark and mark.lower() in found.lower()
                    for mark in (subject.family, subject.name[:9]))
        grounding.documented = bool(headers) or named
        grounding.reference = _reference(subject, headers, topics_of(message),
                                         documented=grounding.documented)
        return grounding


def _reference(subject: Subject, headers: list[Header], topics: tuple[str, ...], *,
               documented: bool) -> str:
    unsure = ("If you are not sure of an exact name, value, pin or step, say which, and do not "
              "present it as certain. If you cannot work out how to do it, say so plainly "
              "instead of guessing. Never cite a page, section, table or figure of a document "
              "you have not been given here: name the document to look in instead.")
    if not headers:
        if documented:
            return (f"The person asks about the {subject.name}. Use the passages from their "
                    f"documents for its exact names and pin numbers. {unsure}")
        return (f"The person asks about the {subject.name}, and nothing on this computer "
                "documents it: no datasheet and no library files. Say at the start that you "
                "cannot check exact names, register settings or pin numbers, and mark any you "
                f"give as unverified. Never use names from a different chip family. {unsure}")
    chosen = [h for h in headers if any(_about(h.path.name, t) for t in topics)] or []
    lines: list[str] = []
    used = 0
    for header in sorted(chosen, key=lambda h: (len(h.path.name), h.path.name)):
        block = _digest(header, topics)
        if not block or used + len(block) > MAX_REFERENCE_CHARS:
            continue
        lines.append(block)
        used += len(block)
    rcc = [h for h in headers if "_hal_rcc" in h.path.name.lower()]
    clocks = sorted({n for h in rcc for n in h.symbols
                     if n.startswith("__HAL_RCC_") and n.endswith("_CLK_ENABLE")
                     and any(t.upper() in n for t in topics)})
    if clocks and used < MAX_REFERENCE_CHARS:
        lines.append("Clock enable macros: " + ", ".join(clocks[:12]))
    head = (f"The person asks about the {subject.name}. These are names from its own library "
            f"files on this computer ({len(headers)} headers found). Use these exact names; a "
            "name from another chip family, such as an STM32F4 one on a G4, is wrong. Akira "
            f"checks the names in your code against these files after you answer. {unsure}")
    return head + ("\n\n" + "\n\n".join(lines) if lines else "")


def _about(filename: str, topic: str) -> bool:
    name = filename.lower()
    return bool(re.search(rf"_(?:hal|ll)_{re.escape(topic)}(?:_ex)?\.h", name)
                or re.search(rf"(?:^|[_/]){re.escape(topic)}(?:[_.]|$)", name))


def _digest(header: Header, topics: tuple[str, ...]) -> str:
    functions = [line for name, line in sorted(header.functions.items())
                 if name.startswith(("HAL_", "LL_")) and not name.endswith("Callback")]
    groups: dict[str, list[str]] = {}
    for name in sorted(header.symbols):
        if name.startswith("_") or not name.isupper() or name.endswith(("_H", "_H_")):
            continue
        parts = name.split("_")
        if len(parts) < 3 or not any(t.upper() in parts[0] for t in topics):
            continue
        groups.setdefault("_".join(parts[:2]) + "_", []).append(name)
    lines = [f"From {header.path.name}:"]
    if functions:
        lines.append("Functions: " + " ".join(functions[:40]))
    for prefix, names in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:14]:
        shown = names if len(names) <= 16 else names[:16] + [f"... {len(names) - 16} more"]
        lines.append(f"{prefix}*: " + ", ".join(shown))
    return "\n".join(lines) if len(lines) > 1 else ""


def _names_in(reply: str) -> list[str]:
    # In code blocks, in `inline code`, and in the sentences: a teaching answer
    # names most of what it uses in its sentences, and not always in backticks.
    # "ADC1->SQR5 and ADC_CR2_ADON", from another STM32 family, were written in a
    # sentence and not checked.
    blocks = _CODE_BLOCK.findall(reply)
    prose = _CODE_BLOCK.sub(" ", reply)
    code = "\n".join([*blocks, *_INLINE.findall(prose)])
    text = code + "\n" + _INLINE.sub(" ", prose)
    own = {n for pair in _DEFINED_HERE.findall(code) for n in pair if n}
    out: list[str] = []
    for name in _NAME.findall(text):
        if name in own or name in out or not any(c.isupper() for c in name):
            continue
        # A variable of the person's own, such as adc_value, is not a library's.
        if name.lower() == name:
            continue
        out.append(name)
    for found in _REGISTER.finditer(text):
        access = f"{found[1]}->{found[2]}"
        if access not in out:
            out.append(access)
    return out


#: A register reached through its peripheral: ADC1->SQR1, GPIOA->MODER.
_REGISTER = re.compile(r"\b([A-Z][A-Z0-9]*)->([A-Z][A-Z0-9]*)\b")


def _peripherals(instance: str) -> list[str]:
    """What a peripheral's own names may start with: ADC1 → ADC1, ADC; GPIOA → GPIOA, GPIO."""
    names = [instance]
    bare = instance.rstrip("0123456789")
    if bare and bare != instance:
        names.append(bare)
    if len(instance) > 4 and instance[-1].isalpha() and instance[:-1] not in names:
        names.append(instance[:-1])
    return names


def _registers(instance: str, known: set[str]) -> set[str]:
    """The registers \a instance has, read from its bit names: ADC_SQR1_SQ1 says ADC has
    SQR1. Empty when the headers name none of its registers.

    Every prefix it may go by, together: ADC1's own names (ADC12_COMMON...) said
    nothing of CR, which ADC_CR_ADEN does.
    """
    found: set[str] = set()
    for prefix in _peripherals(instance):
        lead = prefix + "_"
        found |= {name[len(lead):].split("_", 1)[0] for name in known
                  if name.startswith(lead) and name.count("_") >= 2}
    return found


def _first(name: str) -> str:
    return name.lstrip("_").split("_", 1)[0]


def _closest(name: str, known: set[str]) -> list[str]:
    stem = "_".join(name.lstrip("_").split("_")[:2])
    pool = [k for k in known if k.lstrip("_").startswith(stem)] or \
           [k for k in known if _first(k) == _first(name)]
    return difflib.get_close_matches(name, pool, n=2, cutoff=0.55)


# -- teaching -----------------------------------------------------------------------------------

_TEACH = re.compile(
    r"(?:don'?t|do not|without) (?:just )?(?:writ(?:e|ing)|giv(?:e|ing)) (?:me )?(?:it|the|a|any)"
    r"(?: whole| full| complete)? ?(?:code|program|answer|solution|sketch)?"
    r"|teach me|help me (?:understand|learn)|walk me through|show me how to go about"
    r"|how (?:do|would|should) i go about|explain how (?:to|i)|i want to learn",
    re.IGNORECASE)

TEACHING = ("The person wants to learn to do this themselves. Explain the steps in order, what "
            "each is for, the mistakes people make and how to check each step worked. Do not "
            "write the whole program for them; a line or two to show an exact name is fine.")


def teaching(text: str) -> bool:
    """Whether \a text asks to be taught rather than given the answer."""
    return bool(_TEACH.search(text))
