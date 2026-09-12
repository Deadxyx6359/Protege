"""Markdown notes as Obsidian writes them: frontmatter, tags, links, sections.

Pure text in, text out — no file access — so every rule here is testable on a
string. `vault` does the reading and writing.

Two rules are easy to get wrong and matter:

  * **Code is not prose.** `#include` in a code block is not a tag, and
    `[[x]]` inside backticks is not a link. Fenced blocks and inline code are
    blanked before tags and links are looked for.
  * **Appending must not disturb what is already there.** Adding a line under
    a heading inserts it at the end of that section and changes nothing else:
    not the frontmatter, not the line endings, not the other sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml

FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.DOTALL)

_FENCE = re.compile(r"^(```|~~~)[^\n]*\n.*?^\1[^\n]*$", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]*`")

#: A tag starts at a line start or after whitespace, and needs one character
#: that is not a digit: `#2026` is a number, `#y2026` is a tag.
_TAG = re.compile(r"(?:(?<=\s)|^)#((?:[\w\-/])*[^\W\d](?:[\w\-/])*)", re.MULTILINE)

_WIKILINK = re.compile(
    r"(!?)\[\[([^\[\]|#^\n]+?)(?:#([^\[\]|^\n]*))?(?:\^([^\[\]|\n]*))?(?:\|([^\[\]\n]*))?\]\]")
_MARKDOWN_LINK = re.compile(r"(!?)\[([^\]\n]*)\]\(([^)\s]+?\.md)(?:#([^)\s]*))?\)", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_PERCENT = re.compile(r"(?:%[0-9A-Fa-f]{2})+")


@dataclass(frozen=True, slots=True)
class Link:
    target: str
    heading: str = ""
    alias: str = ""
    embed: bool = False


def split(text: str) -> tuple[dict, str, str]:
    """(frontmatter, body, error). On an error the frontmatter comes back empty."""
    match = FRONTMATTER.match(text)
    if not match:
        return {}, text, ""
    body = text[match.end():]
    raw = match.group(1) or ""
    try:
        # safe_load only: frontmatter is data, and full YAML can build objects.
        loaded = yaml.safe_load(raw) if raw.strip() else None
    except yaml.YAMLError as exc:
        return {}, body, "the frontmatter is not valid YAML: " + str(exc).replace("\n", " ")[:200]
    if loaded is None:
        return {}, body, ""
    if not isinstance(loaded, dict):
        return {}, body, f"the frontmatter must be a set of named values, not a {type(loaded).__name__}"
    return loaded, body, ""


def frontmatter_block(text: str) -> tuple[str, str]:
    """(the frontmatter block exactly as written, the rest). For edits that
    must leave the frontmatter byte-for-byte alone."""
    match = FRONTMATTER.match(text)
    return (text[:match.end()], text[match.end():]) if match else ("", text)


def compose(frontmatter: dict, body: str) -> str:
    """A note from frontmatter and body. No block at all when there is nothing in it."""
    if not frontmatter:
        return body
    dumped = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True,
                            default_flow_style=False).rstrip("\n")
    return f"---\n{dumped}\n---\n{body}"


def _prose(body: str) -> str:
    return _INLINE_CODE.sub(" ", _FENCE.sub("", body))


def tags(frontmatter: dict, body: str) -> tuple[str, ...]:
    """Tags from the frontmatter and from the text, first spelling kept."""
    found: list[str] = []
    for key in ("tags", "tag"):
        value = frontmatter.get(key)
        if value is None:
            continue
        items = value if isinstance(value, (list, tuple)) else re.split(r"[,\s]+", str(value))
        found.extend(str(item).strip().lstrip("#") for item in items if str(item).strip())
    found.extend(match.group(1) for match in _TAG.finditer(_prose(body)))
    seen: set[str] = set()
    ordered = []
    for tag in found:
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            ordered.append(tag)
    return tuple(ordered)


def _unquote(text: str) -> str:
    return _PERCENT.sub(
        lambda m: bytes.fromhex(m.group(0).replace("%", "")).decode("utf-8", "replace"), text)


def links(body: str) -> tuple[Link, ...]:
    """Every link to another note: `[[wikilinks]]` in all their forms, and
    Markdown links to `.md` files."""
    prose = _prose(body)
    found = [Link(m.group(2).strip(), (m.group(3) or "").strip(), (m.group(5) or "").strip(),
                  bool(m.group(1)))
             for m in _WIKILINK.finditer(prose)]
    for match in _MARKDOWN_LINK.finditer(prose):
        target = _unquote(match.group(3))
        if re.match(r"[a-z][a-z0-9+.\-]*://", target, re.IGNORECASE):
            continue
        found.append(Link(target, _unquote(match.group(4) or ""), match.group(2), bool(match.group(1))))
    return tuple(found)


def append_under(body: str, text: str, heading: str | None = None) -> str:
    """\a body with \a text added — at the end, or at the end of a section.

    A heading that does not exist yet is added at the end as `##`. The body's
    own line endings are kept, and nothing outside the insertion changes.
    """
    newline = "\r\n" if "\r\n" in body else "\n"
    addition = text.strip("\r\n").replace("\r\n", "\n").replace("\n", newline)
    if not heading or not heading.strip().lstrip("#").strip():
        if body and not body.endswith(newline):
            body += newline
        return body + addition + newline

    title = heading.strip().lstrip("#").strip()
    wanted = title.lower()
    lines = body.split(newline)
    start = end = None
    level = 0
    fenced = False
    for index, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING.match(line)
        if not match:
            continue
        depth = len(match.group(1))
        if start is None:
            if match.group(2).strip().lower() == wanted:
                start, level = index, depth
        elif depth <= level:
            end = index
            break

    if start is None:
        base = body if not body or body.endswith(newline) else body + newline
        spacer = newline if base.strip() else ""
        return f"{base}{spacer}## {title}{newline}{addition}{newline}"

    end = len(lines) if end is None else end
    insert = end
    while insert - 1 > start and not lines[insert - 1].strip():
        insert -= 1
    return newline.join(lines[:insert] + addition.split(newline) + lines[insert:])
