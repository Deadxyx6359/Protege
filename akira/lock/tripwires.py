"""Layer 4 -- deterministic tripwires.

Keyword and regex checks over MAIN's output, keyed to locked topics. Fast,
dumb, and the only layer with no model in it -- which is exactly its value.
Layers 2 and 5 are both probabilistic; when they fail they fail in correlated
ways, because they are both language models being asked to be careful. This
layer fails differently, so it catches a different set of leaks.

It produces false positives. That is accepted rather than tolerated: a keyword
list tuned tightly enough to never misfire would be tuned loosely enough to
miss the paraphrase. The block inspector shows exactly which rule fired on which
span so a false positive is a thirty-second fix in the pattern editor rather
than a mystery.

Patterns live per topic in `vault/.protege/tripwires/<topic>.json` and are
authored by the user. Akira ships none. A shipped keyword list would be the
application deciding what "chemistry" means, and the whole premise is that the
user defines their own topics by teaching them.

**ReDoS.** Patterns are user-authored regexes and Python's `re` has no
execution timeout, so a pathological pattern against a long draft can hang the
scan. Two mitigations: `validate_pattern` rejects obviously catastrophic
constructs when a pattern is saved, and `MAX_SCAN_CHARS` caps how much text is
ever fed to one. The cap is not a silent truncation -- text beyond it is
reported as unscanned, and the pipeline treats unscanned output as a block,
because a draft this layer could not finish checking has not been cleared.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

from ..schemas import SchemaError, normalize_topic
from ..store import StoreError, read_json, tripwire_dir, write_json
from .directive import DECLINE_PATTERN

# Beyond this, a single regex can take unbounded time on a crafted pattern.
# 200k characters is far more than any sane max_tokens produces.
MAX_SCAN_CHARS = 200_000

# Constructs that make catastrophic backtracking easy: nested quantifiers.
_REDOS_RE = re.compile(r"\([^)]*[+*]\)[+*{]|\[[^\]]*\][+*]\s*[+*]|\)\s*[+*]\s*[+*]")


class TripwireError(RuntimeError):
    """A tripwire definition could not be loaded or compiled."""


@dataclass(frozen=True)
class TripwireHit:
    """One rule firing on one span of text."""

    topic: str
    kind: str  # "keyword" | "pattern"
    rule: str
    matched: str
    start: int
    end: int

    def describe(self) -> str:
        return f"{self.kind} {self.rule!r} for locked topic {self.topic!r} matched {self.matched!r}"


@dataclass(frozen=True)
class TopicTripwires:
    """The rule set for one topic."""

    topic: str
    keywords: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    enabled: bool = True
    note: str = ""

    @staticmethod
    def from_json(raw: object, *, source: str = "") -> "TopicTripwires":
        if not isinstance(raw, dict):
            raise TripwireError(f"{source or 'tripwire file'} must contain a JSON object")
        try:
            topic = normalize_topic(raw.get("topic"))
        except SchemaError as exc:
            raise TripwireError(f"{source or 'tripwire file'}: {exc}") from exc

        def _strings(key: str) -> tuple[str, ...]:
            value = raw.get(key, [])
            if not isinstance(value, list):
                raise TripwireError(f"{source}: {key} must be a list of strings")
            out = []
            for item in value:
                if not isinstance(item, str):
                    raise TripwireError(f"{source}: {key} entries must be strings")
                stripped = item.strip()
                if stripped:
                    out.append(stripped)
            return tuple(out)

        patterns = _strings("patterns")
        for pattern in patterns:
            # Compile eagerly. A broken regex discovered mid-scan would raise
            # inside the gate, and while the pipeline turns that into a block,
            # a permanently-blocking topic with no explanation is worse than
            # refusing to load the file.
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise TripwireError(f"{source}: invalid regex {pattern!r}: {exc}") from exc

        return TopicTripwires(
            topic=topic,
            keywords=_strings("keywords"),
            patterns=patterns,
            enabled=bool(raw.get("enabled", True)),
            note=str(raw.get("note", "")),
        )

    def to_json(self) -> dict:
        return {
            "topic": self.topic,
            "enabled": self.enabled,
            "keywords": list(self.keywords),
            "patterns": list(self.patterns),
            "note": self.note,
        }

    @property
    def rule_count(self) -> int:
        return len(self.keywords) + len(self.patterns)


def validate_pattern(pattern: str) -> str:
    """Return an error string for a user-supplied regex, or "" if acceptable.

    Two checks: it must compile, and it must not contain a nested quantifier of
    the `(a+)+` family. The second is a heuristic, not a proof -- deciding
    whether an arbitrary regex backtracks catastrophically is not something a
    linter can settle -- but it catches the constructions people actually write
    by accident.
    """
    if not pattern.strip():
        return "pattern is empty"
    try:
        re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        return f"invalid regex: {exc}"
    if _REDOS_RE.search(pattern):
        return (
            "pattern contains a nested quantifier (e.g. '(a+)+'), which can take "
            "exponential time on some inputs and would hang the lock check"
        )
    return ""


@dataclass
class TripwireSet:
    """All topic rule sets loaded from the vault."""

    by_topic: dict[str, TopicTripwires] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    # -- loading ------------------------------------------------------------

    @staticmethod
    def load(vault: Path) -> "TripwireSet":
        """Read every `<topic>.json` from the tripwire directory.

        A file that fails to load is recorded in `load_errors` and its topic
        gets no coverage. The pipeline surfaces that in the UI; it does not
        silently proceed, because "this topic has tripwires" and "this topic's
        tripwires are broken" must not look the same.
        """
        result = TripwireSet()
        directory = tripwire_dir(vault)
        if not directory.is_dir():
            return result
        for path in sorted(directory.glob("*.json")):
            try:
                raw = read_json(path)
            except StoreError as exc:
                result.load_errors.append(str(exc))
                continue
            if raw is None:
                continue
            try:
                rules = TopicTripwires.from_json(raw, source=path.name)
            except TripwireError as exc:
                result.load_errors.append(str(exc))
                continue
            if rules.topic != path.stem:
                result.load_errors.append(
                    f"{path.name}: declares topic {rules.topic!r} but the filename says "
                    f"{path.stem!r}; refusing to guess which is correct"
                )
                continue
            result.by_topic[rules.topic] = rules
        return result

    @staticmethod
    def save_topic(vault: Path, rules: TopicTripwires) -> None:
        write_json(tripwire_dir(vault) / f"{rules.topic}.json", rules.to_json())

    @staticmethod
    def delete_topic(vault: Path, topic: str) -> None:
        path = tripwire_dir(vault) / f"{normalize_topic(topic)}.json"
        if path.exists():
            path.unlink()

    # -- scanning -----------------------------------------------------------

    def topics_without_rules(self, locked_topics: Iterable[str]) -> tuple[str, ...]:
        """Locked topics that have no tripwire coverage.

        Reported in Settings. A user who believes Layer 4 is protecting a topic
        it has never heard of is worse off than one who knows it is not.
        """
        missing = []
        for topic in locked_topics:
            rules = self.by_topic.get(topic)
            if rules is None or not rules.enabled or rules.rule_count == 0:
                missing.append(topic)
        return tuple(sorted(missing))

    def scan(
        self,
        text: str,
        locked_topics: Sequence[str],
        *,
        strip_declines: bool = True,
    ) -> "TripwireScan":
        """Check `text` against the rules for every locked topic.

        Only locked topics are scanned. An unlocked topic's rules are inert --
        the user taught it, so mentioning it is the point.
        """
        started = time.monotonic()
        scan = TripwireScan(scanned_chars=len(text))

        if len(text) > MAX_SCAN_CHARS:
            # Not a silent truncation. The pipeline treats `incomplete` as a
            # block: output this layer could not finish checking is not cleared.
            scan.incomplete = True
            scan.scanned_chars = MAX_SCAN_CHARS
            text = text[:MAX_SCAN_CHARS]

        haystack = _blank_declines(text) if strip_declines else text

        for topic in locked_topics:
            rules = self.by_topic.get(topic)
            if rules is None or not rules.enabled:
                continue
            for keyword in rules.keywords:
                for match in re.finditer(rf"\b{re.escape(keyword)}\b", haystack, re.IGNORECASE):
                    scan.hits.append(
                        TripwireHit(topic, "keyword", keyword, match.group(0), match.start(), match.end())
                    )
            for pattern in rules.patterns:
                try:
                    compiled = re.compile(pattern, re.IGNORECASE)
                except re.error as exc:
                    scan.errors.append(f"{topic}: invalid regex {pattern!r}: {exc}")
                    continue
                for match in compiled.finditer(haystack):
                    scan.hits.append(
                        TripwireHit(topic, "pattern", pattern, match.group(0), match.start(), match.end())
                    )

        scan.duration_s = time.monotonic() - started
        return scan


def _blank_declines(text: str) -> str:
    """Replace `[LOCKED: topic]` markers with spaces before scanning.

    Without this, a perfectly compliant refusal trips its own topic's keyword
    list -- `[LOCKED: chemistry]` contains "chemistry" -- and Layer 4 would
    block the very behavior Layer 2 asked for. Spaces rather than deletion so
    that reported match offsets still line up with the original text.
    """
    return re.sub(DECLINE_PATTERN, lambda m: " " * len(m.group(0)), text)


@dataclass
class TripwireScan:
    """Result of one scan."""

    hits: list[TripwireHit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    incomplete: bool = False
    scanned_chars: int = 0
    duration_s: float = 0.0

    @property
    def triggered(self) -> bool:
        """Whether this layer blocks.

        True on a hit, on a rule error, and on an incomplete scan. The last two
        are the fail-closed cases: a rule that could not run and text that was
        not reached have both failed to clear the draft, and "did not clear" is
        not the same as "passed".
        """
        return bool(self.hits) or bool(self.errors) or self.incomplete

    @property
    def topics(self) -> tuple[str, ...]:
        return tuple(sorted({h.topic for h in self.hits}))

    @property
    def first_topic(self) -> str:
        return self.hits[0].topic if self.hits else ""

    def reason(self) -> str:
        if self.incomplete:
            return (
                f"output exceeded the {MAX_SCAN_CHARS} character scan limit, so it could not be "
                "fully checked"
            )
        if self.errors:
            return "; ".join(self.errors)
        if self.hits:
            return self.hits[0].describe()
        return ""

    def evidence(self) -> str:
        """Every firing rule, for the block inspector."""
        lines = [h.describe() for h in self.hits]
        lines.extend(self.errors)
        if self.incomplete:
            lines.append(f"scan truncated at {self.scanned_chars} characters")
        return "\n".join(lines)


def seed_topic(vault: Path, topic: str, keywords: Sequence[str] = (), patterns: Sequence[str] = ()) -> TopicTripwires:
    """Create an empty (or pre-filled) rule file for a topic.

    Called when a topic is first relocked, so the user has somewhere obvious to
    write rules. Created disabled-empty rather than guessing at keywords.
    """
    rules = TopicTripwires(
        topic=normalize_topic(topic),
        keywords=tuple(keywords),
        patterns=tuple(patterns),
        enabled=True,
    )
    TripwireSet.save_topic(vault, rules)
    return rules
