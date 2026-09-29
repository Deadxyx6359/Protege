"""Letters in a word, counted rather than guessed.

Asked how many s's are in "possession", the small model spelled it out right,
p-o-s-s-e-s-s-i-o-n, and then said three. A model reads words in pieces, not
letters, so it cannot see them to count.

So when a message asks how many of a letter a word has, or how many letters,
the word is counted here and the count goes into the turn's context as a fact,
the way `dates.span_lines` counts days.
"""

from __future__ import annotations

import re

_WORD = r"[\"'“‘]?([A-Za-z][A-Za-z'-]{0,39}?)[\"'”’]?"
_LETTER = r"(?:the )?(?:letter |character )?[\"'“‘]?([A-Za-z])[\"'”’]?(?:'?s)?"
_IN = rf"\s+(?:are |is |appear |occur )?(?:there )?in (?:the )?(?:word |name )?{_WORD}(?=\W*$|[\s?.!,])"

#: "how many s's are in possession", "how many r in strawberry".
_HOW_MANY = re.compile(rf"\bhow many (?:times (?:does|is) )?{_LETTER}{_IN}", re.IGNORECASE)
#: "how many times does the letter s appear in possession", "count the r's in strawberry".
_TIMES = re.compile(rf"\b(?:how many times does|count(?: up)? (?:the|all the)?)\s*{_LETTER}"
                    rf"(?: appear| occur| come up)?{_IN}", re.IGNORECASE)
#: "how many letters are in possession", "how many letters does possession have".
_LETTERS = re.compile(rf"\bhow many letters (?:are |is )?(?:there )?in (?:the )?(?:word |name )?"
                      rf"{_WORD}(?=\W*$|[\s?.!,])|\bhow many letters (?:does|has) (?:the word )?"
                      rf"{_WORD} (?:have|got)\b", re.IGNORECASE)

#: At most this many words are counted.
MAX_WORDS = 4


def letter_lines(message: str) -> str:
    """The count of each letter asked about in \a message, or ""."""
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for pattern in (_HOW_MANY, _TIMES):
        for found in pattern.finditer(message):
            letter, word = found[1].lower(), found[2]
            if (letter, word.lower()) in seen or len(lines) >= MAX_WORDS:
                continue
            seen.add((letter, word.lower()))
            count = word.lower().count(letter)
            lines.append(f"- “{word}” has {count} of the letter {letter}: {_spelt(word)}.")
    for found in _LETTERS.finditer(message):
        word = found[1] or found[2]
        if ("", word.lower()) in seen or len(lines) >= MAX_WORDS:
            continue
        seen.add(("", word.lower()))
        count = sum(c.isalpha() for c in word)
        lines.append(f"- “{word}” has {count} letters: {_spelt(word)}.")
    if not lines:
        return ""
    return "Letters counted in the message (use these, do not count again):\n" + "\n".join(lines)


def _spelt(word: str) -> str:
    return "-".join(c for c in word if c.isalpha())
