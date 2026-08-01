"""A library of ready-made skills.

Skills the model authors are generated on demand and vary in quality. These are
written, reviewed and shipped with the application: the tools worth having on
day one, that a person should not have to prompt for and cannot reasonably
"teach" a model to produce reliably every time.

Every one obeys the same rules the authoring path enforces -- standard library
only, no network, no writes outside the working directory, results on stdout --
so they run under the identical sandbox with no special casing.

**Installing one still requires approval.** Copying a skill into a project does
not grant it execution; the digest-bound approval in the Skills window does.
Shipping a tool and blessing a tool are deliberately separate, because "it came
with the app" is exactly the reasoning that makes supply-chain trust invisible.

Each skill reads its input from a file path in argv, so they compose with the
vault rather than hard-coding anything.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LibrarySkill:
    name: str
    topic: str
    summary: str
    usage: str
    source: str

    @property
    def filename(self) -> str:
        return f"{self.name}.py"


_CODE_REVIEW = '''\
"""Report structural problems in a Python file.

usage: python code_review.py <file.py>

Static only -- it parses, it never imports or executes the file under review,
so pointing it at unknown code is safe.
"""
import ast
import sys
from pathlib import Path

MAX_LINE = 100
MAX_FUNCTION_LINES = 60
MAX_ARGS = 6


def review(path):
    source = Path(path).read_text(encoding="utf-8")
    findings = []

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"line {exc.lineno}: does not parse -- {exc.msg}"]

    for number, line in enumerate(source.splitlines(), 1):
        if len(line) > MAX_LINE:
            findings.append(f"line {number}: {len(line)} chars, over {MAX_LINE}")
        if line.rstrip() != line:
            findings.append(f"line {number}: trailing whitespace")
        if "\\t" in line:
            findings.append(f"line {number}: tab indentation")

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            length = (node.end_lineno or node.lineno) - node.lineno
            if length > MAX_FUNCTION_LINES:
                findings.append(
                    f"line {node.lineno}: {node.name}() is {length} lines, over {MAX_FUNCTION_LINES}"
                )
            count = len(node.args.args) + len(node.args.kwonlyargs)
            if count > MAX_ARGS:
                findings.append(f"line {node.lineno}: {node.name}() takes {count} arguments")
            if not ast.get_docstring(node) and not node.name.startswith("_"):
                findings.append(f"line {node.lineno}: {node.name}() has no docstring")
            # A mutable default is shared across every call -- a real bug, not style.
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    findings.append(
                        f"line {node.lineno}: {node.name}() has a mutable default argument"
                    )
        elif isinstance(node, ast.ExceptHandler) and node.type is None:
            findings.append(f"line {node.lineno}: bare except swallows KeyboardInterrupt")
        elif isinstance(node, ast.Compare):
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant):
                    if comparator.value is None:
                        findings.append(f"line {node.lineno}: compare to None with 'is', not '=='")

    return findings


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    results = review(sys.argv[1])
    if not results:
        print("No findings.")
    else:
        for item in results:
            print(item)
        print(f"\\n{len(results)} finding(s).")
'''

_DOC_OUTLINE = '''\
"""Build a markdown outline and reading stats for a document.

usage: python doc_outline.py <file.md>

Prints the heading tree, a word count per section, and an estimated reading
time -- the things you want before editing something long.
"""
import re
import sys
from pathlib import Path

WORDS_PER_MINUTE = 220
HEADING = re.compile(r"^(#{1,6})\\s+(.*)$")


def outline(path):
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    sections = []
    current = {"level": 0, "title": "(preamble)", "words": 0, "line": 1}

    in_code = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = HEADING.match(line)
        if match:
            sections.append(current)
            current = {
                "level": len(match.group(1)),
                "title": match.group(2).strip(),
                "words": 0,
                "line": number,
            }
        else:
            current["words"] += len(line.split())
    sections.append(current)
    return [s for s in sections if s["words"] or s["level"]]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)

    sections = outline(sys.argv[1])
    total = sum(s["words"] for s in sections)
    for section in sections:
        indent = "  " * max(0, section["level"] - 1)
        marker = "#" * section["level"] if section["level"] else "-"
        print(f"{indent}{marker} {section['title']}  ({section['words']} words, line {section['line']})")
    print()
    print(f"{total} words across {len(sections)} section(s)")
    print(f"about {max(1, round(total / WORDS_PER_MINUTE))} minute(s) to read")
'''

_TEXT_STATS = '''\
"""Readability and repetition statistics for a text file.

usage: python text_stats.py <file>

Flags the two things that make prose hard to read: sentences that run long,
and words you have leaned on too often.
"""
import re
import sys
from collections import Counter
from pathlib import Path

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "is", "it", "that",
    "this", "for", "on", "with", "as", "was", "are", "be", "by", "at", "from",
    "you", "your", "not", "have", "has", "had", "they", "their", "we", "our",
    "i", "if", "so", "can", "will", "would", "which", "there", "been", "its",
}
LONG_SENTENCE = 30


def analyse(text):
    sentences = [s.strip() for s in re.split(r"[.!?]+(?:\\s|$)", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) > 3)
    long_ones = [(i + 1, len(s.split())) for i, s in enumerate(sentences)
                 if len(s.split()) > LONG_SENTENCE]
    return sentences, words, counts, long_ones


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)

    text = Path(sys.argv[1]).read_text(encoding="utf-8")
    sentences, words, counts, long_ones = analyse(text)
    if not sentences:
        print("No sentences found.")
        raise SystemExit(0)

    average = len(words) / len(sentences)
    print(f"{len(words)} words, {len(sentences)} sentences")
    print(f"average sentence: {average:.1f} words")
    print()
    print("most repeated:")
    for word, count in counts.most_common(8):
        print(f"  {count:3d}  {word}")
    if long_ones:
        print()
        print(f"{len(long_ones)} sentence(s) over {LONG_SENTENCE} words:")
        for index, length in long_ones[:10]:
            print(f"  sentence {index}: {length} words")
'''

_DATA_TABLE = '''\
"""Convert a CSV or JSON file into a markdown table.

usage: python data_table.py <file.csv|file.json> [max_rows]

Handles the boring part of pasting data into a document: column alignment,
header separators, and truncating a long file sensibly.
"""
import csv
import json
import sys
from pathlib import Path


def load(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    if path.lower().endswith(".json"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not data:
            return [], []
        headers = list(data[0].keys())
        return headers, [[str(row.get(h, "")) for h in headers] for row in data]
    rows = list(csv.reader(text.splitlines()))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def render(headers, rows):
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row[:len(widths)]):
            widths[i] = max(widths[i], len(cell))
    out = ["| " + " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers)) + " |"]
    out.append("|" + "|".join("-" * (w + 2) for w in widths) + "|")
    for row in rows:
        padded = list(row) + [""] * (len(headers) - len(row))
        out.append("| " + " | ".join(padded[i].ljust(widths[i])
                                     for i in range(len(headers))) + " |")
    return "\\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50

    headers, rows = load(sys.argv[1])
    if not headers:
        print("No data found.")
        raise SystemExit(0)
    shown = rows[:limit]
    print(render(headers, shown))
    if len(rows) > limit:
        print(f"\\n({len(rows) - limit} more row(s) not shown)")
'''

_PROJECT_SUMMARY = '''\
"""Summarise a source tree: sizes, languages, and leftover markers.

usage: python project_summary.py <directory>

Answers "what is actually in here and what did I leave unfinished" without
opening anything.
"""
import sys
from collections import Counter
from pathlib import Path

SKIP = {".git", "__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
MARKERS = ("TODO", "FIXME", "HACK", "XXX")
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".cfg",
                 ".js", ".ts", ".html", ".css", ".sql", ".sh", ".bat"}


def walk(root):
    for path in sorted(Path(root).rglob("*")):
        if any(part in SKIP or part.startswith(".") for part in path.parts):
            continue
        if path.is_file():
            yield path


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)

    root = Path(sys.argv[1])
    if not root.is_dir():
        print(f"not a directory: {root}")
        raise SystemExit(2)

    by_suffix = Counter()
    lines_by_suffix = Counter()
    total_bytes = 0
    found = []

    for path in walk(root):
        suffix = path.suffix.lower() or "(none)"
        by_suffix[suffix] += 1
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        if suffix not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines_by_suffix[suffix] += len(text.splitlines())
        for number, line in enumerate(text.splitlines(), 1):
            for marker in MARKERS:
                if marker in line:
                    rel = path.relative_to(root).as_posix()
                    found.append(f"{rel}:{number}: {line.strip()[:80]}")
                    break

    print(f"{sum(by_suffix.values())} files, {total_bytes / 1_000_000:.1f} MB")
    print()
    print("by type:")
    for suffix, count in by_suffix.most_common(12):
        lines = lines_by_suffix.get(suffix)
        detail = f", {lines:,} lines" if lines else ""
        print(f"  {suffix:8s} {count:5d} file(s){detail}")
    if found:
        print()
        print(f"{len(found)} unfinished marker(s):")
        for item in found[:25]:
            print(f"  {item}")
        if len(found) > 25:
            print(f"  ... and {len(found) - 25} more")
'''

_JSON_TOOL = '''\
"""Validate, reformat and describe a JSON file.

usage: python json_tool.py <file.json> [--compact]

On a parse failure it reports the exact line and column, which is the part
that actually costs time.
"""
import json
import sys
from pathlib import Path


def describe(value, depth=0, key="root"):
    pad = "  " * depth
    if isinstance(value, dict):
        print(f"{pad}{key}: object ({len(value)} keys)")
        for name, child in list(value.items())[:12]:
            describe(child, depth + 1, name)
        if len(value) > 12:
            print(f"{pad}  ... {len(value) - 12} more keys")
    elif isinstance(value, list):
        print(f"{pad}{key}: array ({len(value)} items)")
        if value:
            describe(value[0], depth + 1, "[0]")
    else:
        shown = repr(value)
        print(f"{pad}{key}: {type(value).__name__} = {shown[:60]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)

    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"INVALID at line {exc.lineno}, column {exc.colno}: {exc.msg}")
        line = text.splitlines()[exc.lineno - 1] if exc.lineno <= len(text.splitlines()) else ""
        print(f"  {line.strip()[:100]}")
        raise SystemExit(1)

    print(f"valid JSON, {len(text)} bytes")
    print()
    describe(data)
    print()
    if "--compact" in sys.argv:
        print(json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
'''

_DIFF_FILES = '''\
"""Show a unified diff between two text files.

usage: python diff_files.py <old> <new>
"""
import difflib
import sys
from pathlib import Path

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)

    old_path, new_path = Path(sys.argv[1]), Path(sys.argv[2])
    old = old_path.read_text(encoding="utf-8", errors="replace").splitlines()
    new = new_path.read_text(encoding="utf-8", errors="replace").splitlines()

    diff = list(difflib.unified_diff(
        old, new, fromfile=old_path.name, tofile=new_path.name, lineterm=""
    ))
    if not diff:
        print("Files are identical.")
        raise SystemExit(0)
    for line in diff:
        print(line)

    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    print()
    print(f"{added} line(s) added, {removed} removed")
'''

LIBRARY: tuple[LibrarySkill, ...] = (
    LibrarySkill(
        name="code_review",
        topic="python_basics",
        summary="Static review of a Python file",
        usage="code_review.py <file.py>",
        source=_CODE_REVIEW,
    ),
    LibrarySkill(
        name="doc_outline",
        topic="python_stdlib",
        summary="Heading tree, word counts and reading time for a document",
        usage="doc_outline.py <file.md>",
        source=_DOC_OUTLINE,
    ),
    LibrarySkill(
        name="text_stats",
        topic="python_stdlib",
        summary="Readability stats and overused words",
        usage="text_stats.py <file>",
        source=_TEXT_STATS,
    ),
    LibrarySkill(
        name="data_table",
        topic="python_data",
        summary="Turn a CSV or JSON file into a markdown table",
        usage="data_table.py <file> [max_rows]",
        source=_DATA_TABLE,
    ),
    LibrarySkill(
        name="project_summary",
        topic="python_stdlib",
        summary="File counts, line counts and unfinished markers in a tree",
        usage="project_summary.py <directory>",
        source=_PROJECT_SUMMARY,
    ),
    LibrarySkill(
        name="json_tool",
        topic="python_data",
        summary="Validate, describe and reformat JSON",
        usage="json_tool.py <file.json> [--compact]",
        source=_JSON_TOOL,
    ),
    LibrarySkill(
        name="diff_files",
        topic="python_stdlib",
        summary="Unified diff between two text files",
        usage="diff_files.py <old> <new>",
        source=_DIFF_FILES,
    ),
)


def by_name(name: str) -> LibrarySkill | None:
    for skill in LIBRARY:
        if skill.name == name:
            return skill
    return None
