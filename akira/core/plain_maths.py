"""Maths written as LaTeX, shown as plain text.

Every model Akira runs is told to write maths as plain text, because a reply is
shown as written and `$` and `\\frac` appear as they are. Asked to solve
x^2 - 5x + 6 = 0, the chat model still wrote "$ (x - 2)(x - 3) = 0 $" on every
line, and "$ x + 1.00 $" in the middle of an answer about dollars. So what is
shown is cleaned here, rather than hoped for: `$…$`, `$$…$$`, `\\(…\\)` and
`\\[…\\]` lose their marks, and the commands inside become the signs they stand
for. A dollar amount is left alone: math marks open on something that is not a
number. Code, fenced or inline, is left exactly as written.
"""

from __future__ import annotations

import re

_FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")

_DISPLAY = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]", re.DOTALL)
_PARENS = re.compile(r"\\\((.+?)\\\)")
#: `$…$` that does not open straight onto a number, so "$5 and $10" stays; a
#: price is written "$5", maths "$ 2x + 1 $" or "$x$".
_DOLLARS = re.compile(r"(?<![\\\w$])\$(?![\d.,])([^$\n]{1,300}?)(?<!\\)\$(?![\d\w])")

_SYMBOLS = {
    r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±", r"\mp": "∓",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\neq": "≠", r"\ne": "≠",
    r"\approx": "≈", r"\sim": "~", r"\infty": "∞", r"\pi": "π", r"\theta": "θ",
    r"\alpha": "α", r"\beta": "β", r"\gamma": "γ", r"\delta": "δ", r"\Delta": "Δ",
    r"\lambda": "λ", r"\mu": "μ", r"\sigma": "σ", r"\omega": "ω", r"\Omega": "Ω",
    r"\rightarrow": "→", r"\to": "→", r"\Rightarrow": "⇒", r"\implies": "⇒",
    r"\degree": "°", r"^\circ": "°", r"\%": "%", r"\$": "$", r"\,": " ", r"\;": " ",
    r"\quad": "  ", r"\qquad": "  ", r"\left": "", r"\right": "", r"\ldots": "…",
    r"\dots": "…", r"\cdots": "…",
}
_FRAC = re.compile(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_SQRT = re.compile(r"\\sqrt\s*\{([^{}]*)\}")
_TEXT = re.compile(r"\\(?:text|mathrm|mathbf|operatorname|textbf)\s*\{([^{}]*)\}")
_POWER = re.compile(r"\^\{([^{}]*)\}")
_INDEX = re.compile(r"_\{([^{}]*)\}")
_COMMAND = re.compile(r"\\([A-Za-z]+)")


def plain(maths: str) -> str:
    """LaTeX \a maths as plain text: `\\frac{200}{9}` is 200/9, `\\times` is ×."""
    text = maths
    for _ in range(6):  # innermost first: a root inside a fraction inside a fraction
        before = text
        text = _SQRT.sub(lambda m: "√" + _grouped(m[1]), text)
        text = _TEXT.sub(lambda m: m[1], text)
        text = _POWER.sub(lambda m: "^" + _grouped(m[1]), text)
        text = _INDEX.sub(lambda m: "_" + _grouped(m[1]), text)
        text = _FRAC.sub(lambda m: f"{_grouped(m[1])}/{_grouped(m[2])}", text)
        if text == before:
            break
    for command in sorted(_SYMBOLS, key=len, reverse=True):
        text = text.replace(command, _SYMBOLS[command])
    text = _COMMAND.sub(lambda m: m[1], text)
    text = text.replace("{", "").replace("}", "")
    return " ".join(text.split())


def _grouped(part: str) -> str:
    # A number or a name stands alone; "2a" under a line is (2a), not 2 then a.
    part = part.strip()
    return part if re.fullmatch(r"\d+(?:\.\d+)?|[A-Za-z]\w*", part) else f"({part})"


def plain_maths(text: str) -> str:
    """\a text with its LaTeX maths shown plainly, and its code left as written."""
    if "$" not in text and "\\" not in text:
        return text
    kept: list[str] = []

    def keep(found: re.Match) -> str:
        kept.append(found.group(0))
        return f"\x00{len(kept) - 1}\x00"

    text = _FENCE.sub(keep, text)
    text = _INLINE_CODE.sub(keep, text)
    text = _DISPLAY.sub(lambda m: plain(m[1] or m[2]), text)
    text = _PARENS.sub(lambda m: plain(m[1]), text)
    text = _DOLLARS.sub(lambda m: plain(m[1]) if _mathematical(m[1]) else m.group(0), text)
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m[1])], text)


def _mathematical(inside: str) -> bool:
    """Whether what `$…$` holds is maths, not the words between two prices."""
    return bool(re.search(r"[=^\\_+\-*/<>]|^\s*[A-Za-z]\s*$|\([^)]*\)", inside)) and \
        len(re.findall(r"[A-Za-z]{4,}", inside)) <= 3
