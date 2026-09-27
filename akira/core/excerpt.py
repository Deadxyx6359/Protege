"""The part of a long text that bears on a question, instead of its first few thousand characters.

A web page read as text starts with its menus: Wikipedia's article on Hubble
spends its first 3,500 characters on navigation and a table of contents, and
the launch date is at 5,427. Cut from the top, what an agent or an answer saw
of it was the menu. This keeps the opening lines, for what the page is, then
the paragraphs that share the most words with the question, in the page's own
order. It is word overlap, nothing cleverer, and it never makes text up: every
line kept is a line of the page.
"""

from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?", re.IGNORECASE)

#: Words too common to say what a question is about.
_COMMON = frozenset("""
a an and are as at be been but by can could did do does for from had has have how i if in
into is it its of on or our so than that the their them then there these they this to
was were what when where which who whom why will with would you your about after before
check find tell me please much many also only just than then over under more most
""".split())

#: What is kept from the start, whatever it says: a title and where it came from.
HEAD_CHARS = 400

#: Blocks this short are menu items and headings; they are only kept beside a match.
_SHORT = 40


def terms(question: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(question)
            if len(word) > 2 and word.lower() not in _COMMON}


def excerpt(text: str, question: str, limit: int) -> str:
    """\a text cut to \a limit characters, keeping what bears on \a question."""
    if len(text) <= limit:
        return text
    wanted = terms(question)
    blocks = [block for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not wanted or len(blocks) < 3:
        return text[:limit]
    head = text[:HEAD_CHARS]
    scored = []
    for index, block in enumerate(blocks):
        words = {word.lower() for word in _WORD.findall(block)}
        score = len(wanted & words)
        if score and len(block.strip()) >= _SHORT:
            scored.append((score, index))
    if not scored:
        return text[:limit]
    budget = limit - len(head) - 40
    chosen: list[int] = []
    for score, index in sorted(scored, key=lambda item: (-item[0], item[1])):
        size = len(blocks[index]) + 6
        if size > budget:
            if not chosen:
                chosen.append(index)  # the best match, cut, rather than nothing
                budget = 0
            continue
        chosen.append(index)
        budget -= size
        if budget <= 0:
            break
    kept = [blocks[index] for index in sorted(chosen)]
    body = "\n\n…\n\n".join(kept)
    return f"{head}\n\n[… only the parts that bear on the question …]\n\n{body}"[:limit]
