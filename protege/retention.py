"""When a topic was last demonstrated, and whether that was too long ago.

The application's premise is that access is earned by demonstrating knowledge.
Until now that was a one-off: a topic unlocked in March was still unlocked in
December, and nothing ever asked whether the material had held. For something
whose whole purpose is pedagogical, "earned once, kept forever" is the wrong
shape -- it is the shape of a permission system, not of learning.

So topics age. The clock is the manifest's own history: the most recent unlock
or review event for a topic is when it was last demonstrated, which means no
new tracking file, no new state to corrupt, and a record that already exists
for every topic ever unlocked.

Two deliberate omissions.

**Usage is not tracked.** "Last time a note on this topic was retrieved" sounds
like a better signal and is a worse one: a topic can be central to a
conversation without any note being retrieved, so absence of retrieval means
nothing. Time since demonstration is crude but it is honest, and it is what
spaced repetition uses.

**Nothing here relocks anything.** This module reports; the caller decides.
Automatic relocking is available in settings and is off by default, because a
program that silently withdraws access to something you did learn is worse than
one that lets a stale unlock stand.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .schemas import Manifest

# Actions that count as "the user showed this again".
DEMONSTRATION_ACTIONS = ("unlock", "review")


@dataclass(frozen=True)
class TopicAge:
    topic: str
    last_demonstrated: datetime | None
    days: int | None
    due_in_days: int | None

    @property
    def is_due(self) -> bool:
        return self.due_in_days is not None and self.due_in_days <= 0

    def describe(self) -> str:
        if self.days is None:
            return f"{self.topic}: no demonstration on record"
        when = "today" if self.days == 0 else f"{self.days} day(s) ago"
        if self.due_in_days is None:
            return f"{self.topic}: last shown {when}"
        if self.is_due:
            return f"{self.topic}: last shown {when} -- review due"
        return f"{self.topic}: last shown {when}, due in {self.due_in_days}"


def _parse(stamp: str) -> datetime | None:
    """Read an ISO timestamp from the manifest, tolerating an absent zone.

    History written by older builds, or hand-edited, may lack an offset. A
    naive value is read as UTC rather than discarded: treating it as "no
    demonstration on record" would make an old topic look brand new, which is
    the one direction this must not fail in.
    """
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def last_demonstrated(manifest: Manifest, topic: str) -> datetime | None:
    """When `topic` was last unlocked or reviewed."""
    stamps = [
        _parse(event.at)
        for event in manifest.history
        if event.topic == topic and event.action in DEMONSTRATION_ACTIONS
    ]
    real = [s for s in stamps if s is not None]
    return max(real) if real else None


def age_of(manifest: Manifest, topic: str, *, review_after_days: int = 0,
           now: datetime | None = None) -> TopicAge:
    now = now or datetime.now(timezone.utc)
    when = last_demonstrated(manifest, topic)
    if when is None:
        return TopicAge(topic, None, None, None)
    days = max(0, (now - when).days)
    due = None if review_after_days <= 0 else review_after_days - days
    return TopicAge(topic, when, days, due)


def review_queue(manifest: Manifest, *, review_after_days: int,
                 now: datetime | None = None) -> list[TopicAge]:
    """Unlocked topics due for review, oldest first.

    Only unlocked topics: a relocked one is already back behind the gate and
    has nothing to lose. A topic with no timestamp in its history sorts as due,
    because unknown age is not the same as recent and should not be treated as
    such.
    """
    if review_after_days <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    ages = [
        age_of(manifest, topic, review_after_days=review_after_days, now=now)
        for topic in manifest.unlocked_topics
    ]
    due = [a for a in ages if a.is_due or a.days is None]
    return sorted(due, key=lambda a: (-1 if a.days is None else -a.days))


def overdue_for_relock(manifest: Manifest, *, review_after_days: int,
                       grace_days: int, now: datetime | None = None) -> list[TopicAge]:
    """Topics past review *and* past the grace period after it.

    Two thresholds rather than one so that automatic relocking, when it is
    switched on at all, never fires the same day a review falls due. Being
    nagged and being cut off on the same morning would make the feature feel
    like a punishment for going on holiday.
    """
    if review_after_days <= 0:
        return []
    now = now or datetime.now(timezone.utc)
    limit = review_after_days + max(0, grace_days)
    out = []
    for topic in manifest.unlocked_topics:
        age = age_of(manifest, topic, review_after_days=review_after_days, now=now)
        if age.days is not None and age.days >= limit:
            out.append(age)
    return sorted(out, key=lambda a: -(a.days or 0))


def next_due(manifest: Manifest, *, review_after_days: int,
             now: datetime | None = None) -> TopicAge | None:
    """The topic that will fall due soonest, for a one-line nudge."""
    if review_after_days <= 0 or not manifest.unlocked_topics:
        return None
    now = now or datetime.now(timezone.utc)
    ages = [
        age_of(manifest, t, review_after_days=review_after_days, now=now)
        for t in manifest.unlocked_topics
    ]
    ages = [a for a in ages if a.due_in_days is not None]
    return min(ages, key=lambda a: a.due_in_days) if ages else None


def summarize(queue: list[TopicAge], *, review_after_days: int) -> str:
    if not queue:
        return f"Nothing due. Topics come up for review after {review_after_days} days."
    names = ", ".join(a.topic for a in queue[:4])
    more = f" and {len(queue) - 4} more" if len(queue) > 4 else ""
    return f"{len(queue)} topic(s) due for review: {names}{more}."


def days_between(earlier: datetime, later: datetime) -> int:
    return max(0, (later - earlier) // timedelta(days=1))
