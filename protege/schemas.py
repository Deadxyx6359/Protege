"""Data schemas for every file Protege persists.

Pure data and validation. No file I/O lives here -- see `store.py` for that --
so these types can be exercised in tests without touching a vault.

Design rule that governs this whole module: **validation failures never
degrade into permissive defaults.** A manifest that will not parse yields zero
unlocked topics and a hard error, not an empty-but-usable manifest. A settings
file that will not parse yields shipped defaults with every lock layer on. The
failure mode of a corrupt config is "Protege refuses to talk", never "Protege
talks about everything".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 1

# Topic ids are used as filesystem names (tripwires/<topic>.json) and matched
# against note frontmatter, so the character set is deliberately narrow.
TOPIC_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
TRAIT_ID_RE = TOPIC_ID_RE
PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}$")

BAND_COUNT = 5
NEUTRAL_BAND = 2  # zero-indexed; band 3 of 5 in the brief's numbering

TRUST_TIERS = (0, 1, 2, 3)


class SchemaError(ValueError):
    """Raised when persisted data does not satisfy its schema.

    Callers must treat this as fail-closed: block, do not fall back to
    something permissive.
    """


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaError(message)


def _as_dict(raw: Any, what: str) -> dict:
    _require(isinstance(raw, dict), f"{what} must be a JSON object, got {type(raw).__name__}")
    return raw


def _as_list(raw: Any, what: str) -> list:
    _require(isinstance(raw, list), f"{what} must be a JSON array, got {type(raw).__name__}")
    return raw


def _as_str(raw: Any, what: str) -> str:
    _require(isinstance(raw, str), f"{what} must be a string, got {type(raw).__name__}")
    return raw


def _as_bool(raw: Any, what: str, default: bool) -> bool:
    if raw is None:
        return default
    _require(isinstance(raw, bool), f"{what} must be true or false")
    return raw


def _as_int(raw: Any, what: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    if raw is None:
        return default
    _require(isinstance(raw, int) and not isinstance(raw, bool), f"{what} must be an integer")
    if lo is not None:
        _require(raw >= lo, f"{what} must be >= {lo}")
    if hi is not None:
        _require(raw <= hi, f"{what} must be <= {hi}")
    return raw


def _as_float(raw: Any, what: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    if raw is None:
        return default
    _require(
        isinstance(raw, (int, float)) and not isinstance(raw, bool),
        f"{what} must be a number",
    )
    val = float(raw)
    if lo is not None:
        _require(val >= lo, f"{what} must be >= {lo}")
    if hi is not None:
        _require(val <= hi, f"{what} must be <= {hi}")
    return val


def normalize_topic(raw: Any) -> str:
    """Validate and canonicalize a topic id.

    Accepts only the narrow id form. This is intentionally strict: a topic id
    that differs from its note-frontmatter spelling by case or a hyphen is a
    silent lock bypass, because retrieval would fail to match the topic and the
    note would look untagged.
    """
    topic = _as_str(raw, "topic").strip().lower()
    _require(
        bool(TOPIC_ID_RE.match(topic)),
        f"invalid topic id {topic!r}: must match [a-z][a-z0-9_]* and be <= 64 chars",
    )
    return topic


def normalize_topics(raw: Any, what: str = "topics") -> tuple[str, ...]:
    items = _as_list(raw, what)
    seen: list[str] = []
    for item in items:
        topic = normalize_topic(item)
        if topic not in seen:
            seen.append(topic)
    return tuple(sorted(seen))


# ---------------------------------------------------------------------------
# Manifest -- Layer 1 of the lock system, the single source of truth
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UnlockEvent:
    """One entry in the manifest's provenance log.

    Append-only in practice: re-locking adds a 'relock' event rather than
    erasing the original unlock, so the history remains an audit trail of what
    the model was permitted to know and when.
    """

    topic: str
    action: str  # "unlock" | "relock" | "review"
    at: str
    source_notes: tuple[str, ...] = ()
    note: str = ""

    # "review" is a re-demonstration of a topic that is already unlocked.
    # It changes nothing about access; it resets the retention clock, which
    # is read from this history rather than from a separate file.
    VALID_ACTIONS = ("unlock", "relock", "review")

    @staticmethod
    def from_json(raw: Any) -> "UnlockEvent":
        data = _as_dict(raw, "history entry")
        action = _as_str(data.get("action", "unlock"), "history.action")
        _require(
            action in UnlockEvent.VALID_ACTIONS,
            f"history.action must be one of {UnlockEvent.VALID_ACTIONS}, got {action!r}",
        )
        sources = tuple(
            _as_str(s, "history.source_notes[]") for s in _as_list(data.get("source_notes", []), "history.source_notes")
        )
        return UnlockEvent(
            topic=normalize_topic(data.get("topic")),
            action=action,
            at=_as_str(data.get("at", ""), "history.at"),
            source_notes=sources,
            note=_as_str(data.get("note", ""), "history.note"),
        )

    def to_json(self) -> dict:
        return {
            "topic": self.topic,
            "action": self.action,
            "at": self.at,
            "source_notes": list(self.source_notes),
            "note": self.note,
        }


@dataclass(frozen=True)
class ApprovedSkill:
    """A skill the user has explicitly authorized to execute.

    The digest matters more than the path. Approval is granted to *this exact
    content*; if the model rewrites the file afterwards the digest no longer
    matches and approval is void. Without that, "approve once" would become
    "approve arbitrary future code".
    """

    path: str
    sha256: str
    approved_at: str
    topic: str = ""

    @staticmethod
    def from_json(key: str, raw: Any) -> "ApprovedSkill":
        data = _as_dict(raw, "approved_skills entry")
        digest = _as_str(data.get("sha256", ""), "approved_skills.sha256").lower()
        _require(
            bool(re.fullmatch(r"[0-9a-f]{64}", digest)),
            "approved_skills.sha256 must be a 64-character hex digest",
        )
        topic_raw = data.get("topic", "")
        return ApprovedSkill(
            path=key,
            sha256=digest,
            approved_at=_as_str(data.get("approved_at", ""), "approved_skills.approved_at"),
            topic=normalize_topic(topic_raw) if topic_raw else "",
        )

    def to_json(self) -> dict:
        return {"sha256": self.sha256, "approved_at": self.approved_at, "topic": self.topic}


@dataclass(frozen=True)
class PinRecord:
    """Salted argon2id hash of the launch PIN.

    The salt is embedded in the argon2 encoded string; we never store or
    generate one separately. An empty `hash` means "no PIN configured yet",
    which the UI treats as first-run setup, not as "no PIN required".
    """

    algorithm: str = "argon2id"
    hash: str = ""

    @property
    def is_set(self) -> bool:
        return bool(self.hash)

    @staticmethod
    def from_json(raw: Any) -> "PinRecord":
        if raw is None:
            return PinRecord()
        data = _as_dict(raw, "pin")
        algorithm = _as_str(data.get("algorithm", "argon2id"), "pin.algorithm")
        _require(algorithm == "argon2id", f"unsupported pin algorithm {algorithm!r}")
        encoded = _as_str(data.get("hash", ""), "pin.hash")
        _require(
            not encoded or encoded.startswith("$argon2id$"),
            "pin.hash must be an argon2id encoded hash",
        )
        return PinRecord(algorithm=algorithm, hash=encoded)

    def to_json(self) -> dict:
        return {"algorithm": self.algorithm, "hash": self.hash}


@dataclass(frozen=True)
class Manifest:
    """`vault/.protege/manifest.json` -- the single source of truth for what is
    unlocked.

    Topics are added one at a time, each with provenance. Nothing here writes
    an "unlock all" to the file, and `unrestricted` is not one -- see below.
    """

    unlocked_topics: tuple[str, ...] = ()
    trust_tier: int = 0
    history: tuple[UnlockEvent, ...] = ()
    approved_skills: tuple[ApprovedSkill, ...] = ()
    pin: PinRecord = field(default_factory=PinRecord)
    external_roots: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    # Everyday mode: every topic answers as unlocked. Runtime only. It appears
    # in neither `to_json` nor `from_json`, so it cannot be set by editing the
    # manifest, cannot survive a save and reload, and is reachable only through
    # an explicit `unrestricted_view()`. The stored record of what has actually
    # been taught is never touched by it, which is what makes switching back to
    # Protege mode exact rather than a restore from memory.
    unrestricted: bool = False

    # -- queries ------------------------------------------------------------

    def is_unlocked(self, topic: str) -> bool:
        """True only for an exactly-matching, already-normalized topic id.

        Note the asymmetry: an unparseable topic id raises rather than
        returning False, because a caller passing garbage here has a bug, and a
        silent False would look like correct locking while masking it. The
        normalisation therefore runs before the everyday-mode short circuit: a
        malformed id is still a bug in everyday mode.
        """
        normalized = normalize_topic(topic)
        return True if self.unrestricted else normalized in self.unlocked_topics

    def all_locked(self, topics: Iterable[str]) -> tuple[str, ...]:
        """Subset of `topics` that is NOT unlocked. The core gating query."""
        locked = tuple(
            t for t in (normalize_topic(x) for x in topics) if t not in self.unlocked_topics
        )
        return () if self.unrestricted else locked

    def unrestricted_view(self) -> "Manifest":
        """This manifest as everyday mode sees it: everything answers unlocked.

        A *view*, deliberately. The responder is handed one; nothing writes it
        back. `unlocked_topics` still holds only what was genuinely taught, so
        the knowledge web and the topic manager go on telling the truth while
        the mode is on.
        """
        return replace(self, unrestricted=True)

    def skill_approval(self, path: str) -> ApprovedSkill | None:
        for skill in self.approved_skills:
            if skill.path == path:
                return skill
        return None

    # -- mutations (all return new instances; Manifest is frozen) ------------

    def with_unlocked(self, topic: str, source_notes: Sequence[str] = (), note: str = "") -> "Manifest":
        topic = normalize_topic(topic)
        if topic in self.unlocked_topics:
            return self
        event = UnlockEvent(
            topic=topic,
            action="unlock",
            at=utcnow_iso(),
            source_notes=tuple(source_notes),
            note=note,
        )
        return replace(
            self,
            unlocked_topics=tuple(sorted(self.unlocked_topics + (topic,))),
            history=self.history + (event,),
        )

    def with_reviewed(self, topic: str, source_notes: Sequence[str] = (),
                      note: str = "") -> "Manifest":
        """Record that an already-unlocked topic was demonstrated again.

        Access is unchanged -- only the history grows. Reviewing a topic that
        is not unlocked is a caller bug and raises, because the sensible
        response to "review something locked" is to unlock it properly.
        """
        topic = normalize_topic(topic)
        _require(topic in self.unlocked_topics,
                 f"cannot review {topic!r}: it is not unlocked")
        event = UnlockEvent(
            topic=topic,
            action="review",
            at=utcnow_iso(),
            source_notes=tuple(source_notes),
            note=note,
        )
        return replace(self, history=self.history + (event,))

    def with_relocked(self, topic: str, note: str = "") -> "Manifest":
        topic = normalize_topic(topic)
        if topic not in self.unlocked_topics:
            return self
        event = UnlockEvent(topic=topic, action="relock", at=utcnow_iso(), note=note)
        return replace(
            self,
            unlocked_topics=tuple(t for t in self.unlocked_topics if t != topic),
            history=self.history + (event,),
        )

    def with_trust_tier(self, tier: int) -> "Manifest":
        _require(tier in TRUST_TIERS, f"trust_tier must be one of {TRUST_TIERS}, got {tier!r}")
        return replace(self, trust_tier=tier)

    def with_pin(self, encoded_hash: str) -> "Manifest":
        return replace(self, pin=PinRecord(algorithm="argon2id", hash=encoded_hash))

    def with_skill_approved(self, skill: ApprovedSkill) -> "Manifest":
        others = tuple(s for s in self.approved_skills if s.path != skill.path)
        return replace(self, approved_skills=tuple(sorted(others + (skill,), key=lambda s: s.path)))

    def with_skill_revoked(self, path: str) -> "Manifest":
        return replace(self, approved_skills=tuple(s for s in self.approved_skills if s.path != path))

    def with_external_roots(self, roots: Sequence[str]) -> "Manifest":
        return replace(self, external_roots=tuple(roots))

    # -- serialization ------------------------------------------------------

    @staticmethod
    def from_json(raw: Any) -> "Manifest":
        data = _as_dict(raw, "manifest")
        version = _as_int(data.get("schema_version", SCHEMA_VERSION), "manifest.schema_version", SCHEMA_VERSION, lo=1)
        _require(
            version <= SCHEMA_VERSION,
            f"manifest.schema_version {version} is newer than this build supports ({SCHEMA_VERSION}); "
            "refusing to load rather than guess at its meaning",
        )
        history = tuple(UnlockEvent.from_json(h) for h in _as_list(data.get("history", []), "manifest.history"))
        raw_skills = _as_dict(data.get("approved_skills", {}), "manifest.approved_skills")
        skills = tuple(sorted((ApprovedSkill.from_json(k, v) for k, v in raw_skills.items()), key=lambda s: s.path))
        roots = tuple(_as_str(r, "manifest.external_roots[]") for r in _as_list(data.get("external_roots", []), "manifest.external_roots"))
        return Manifest(
            unlocked_topics=normalize_topics(data.get("unlocked_topics", []), "manifest.unlocked_topics"),
            trust_tier=_as_int(data.get("trust_tier", 0), "manifest.trust_tier", 0, lo=0, hi=3),
            history=history,
            approved_skills=skills,
            pin=PinRecord.from_json(data.get("pin")),
            external_roots=roots,
            schema_version=version,
        )

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "unlocked_topics": list(self.unlocked_topics),
            "trust_tier": self.trust_tier,
            "history": [h.to_json() for h in self.history],
            "approved_skills": {s.path: s.to_json() for s in self.approved_skills},
            "pin": self.pin.to_json(),
            "external_roots": list(self.external_roots),
        }

    @staticmethod
    def initial() -> "Manifest":
        """First-launch state.

        Empty. Per the brief's scope note, ethics, morality and literature are
        locked here exactly like geography and mathematics -- there is no
        seeded topic list, because seeding one would be the application
        deciding what the user does not have to teach.
        """
        return Manifest()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ModelSettings:
    main_path: str = ""
    auditor_path: str = ""
    main_ctx: int = 8192
    auditor_ctx: int = 4096
    temperature: float = 0.7
    top_p: float = 0.95
    max_tokens: int = 1024
    n_gpu_layers: int = -1  # -1 = offload everything the GPU will take
    seed: int = -1
    # "sequential" unloads MAIN before loading AUDITOR and vice versa. Slower
    # per turn, but the brief's target box has 12GB system RAM, and that -- not
    # VRAM -- is the binding constraint when both models are resident.
    loading: str = "sequential"
    n_threads: int = 0  # 0 = let llama.cpp choose

    VALID_LOADING = ("sequential", "concurrent")

    @staticmethod
    def from_json(raw: Any) -> "ModelSettings":
        data = _as_dict(raw or {}, "settings.models")
        loading = _as_str(data.get("loading", "sequential"), "settings.models.loading")
        _require(
            loading in ModelSettings.VALID_LOADING,
            f"settings.models.loading must be one of {ModelSettings.VALID_LOADING}",
        )
        return ModelSettings(
            main_path=_as_str(data.get("main_path", ""), "settings.models.main_path"),
            auditor_path=_as_str(data.get("auditor_path", ""), "settings.models.auditor_path"),
            main_ctx=_as_int(data.get("main_ctx"), "settings.models.main_ctx", 8192, lo=512, hi=1_048_576),
            auditor_ctx=_as_int(data.get("auditor_ctx"), "settings.models.auditor_ctx", 4096, lo=512, hi=1_048_576),
            temperature=_as_float(data.get("temperature"), "settings.models.temperature", 0.7, lo=0.0, hi=2.0),
            top_p=_as_float(data.get("top_p"), "settings.models.top_p", 0.95, lo=0.0, hi=1.0),
            max_tokens=_as_int(data.get("max_tokens"), "settings.models.max_tokens", 1024, lo=16, hi=32768),
            n_gpu_layers=_as_int(data.get("n_gpu_layers"), "settings.models.n_gpu_layers", -1, lo=-1, hi=1024),
            seed=_as_int(data.get("seed"), "settings.models.seed", -1, lo=-1),
            loading=loading,
            n_threads=_as_int(data.get("n_threads"), "settings.models.n_threads", 0, lo=0, hi=256),
        )

    def to_json(self) -> dict:
        return {
            "main_path": self.main_path,
            "auditor_path": self.auditor_path,
            "main_ctx": self.main_ctx,
            "auditor_ctx": self.auditor_ctx,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "n_gpu_layers": self.n_gpu_layers,
            "seed": self.seed,
            "loading": self.loading,
            "n_threads": self.n_threads,
        }


@dataclass(frozen=True)
class LockLayerToggles:
    """Per-layer kill switches.

    Every layer defaults on. The UI warns loudly whenever any is off, and
    `any_disabled` drives that warning. These exist for debugging and for
    inspecting which layer caught a given leak -- not as a convenience.
    """

    directive: bool = True
    retrieval: bool = True
    tripwires: bool = True
    auditor: bool = True

    @property
    def any_disabled(self) -> bool:
        return not (self.directive and self.retrieval and self.tripwires and self.auditor)

    @property
    def disabled_names(self) -> tuple[str, ...]:
        off = []
        if not self.directive:
            off.append("directive")
        if not self.retrieval:
            off.append("retrieval")
        if not self.tripwires:
            off.append("tripwires")
        if not self.auditor:
            off.append("auditor")
        return tuple(off)

    @staticmethod
    def from_json(raw: Any) -> "LockLayerToggles":
        data = _as_dict(raw or {}, "settings.lock_layers")
        return LockLayerToggles(
            directive=_as_bool(data.get("directive"), "settings.lock_layers.directive", True),
            retrieval=_as_bool(data.get("retrieval"), "settings.lock_layers.retrieval", True),
            tripwires=_as_bool(data.get("tripwires"), "settings.lock_layers.tripwires", True),
            auditor=_as_bool(data.get("auditor"), "settings.lock_layers.auditor", True),
        )

    def to_json(self) -> dict:
        return {
            "directive": self.directive,
            "retrieval": self.retrieval,
            "tripwires": self.tripwires,
            "auditor": self.auditor,
        }


@dataclass(frozen=True)
class AuditorSettings:
    # "lenient" still blocks on parse failure and timeout -- it only widens what
    # counts as a clean PASS. There is no setting that makes the auditor
    # fail open.
    strictness: str = "normal"
    # 300s, not the 45s this started at. 45 suited an 8B running at 20+ tok/s.
    # On a 24B at ~2 tok/s the auditor could not finish reading an unlock
    # demonstration (~1500 characters of summary and Q&A, far longer than a
    # chat reply) before the deadline, so legitimate unlocks failed with
    # "auditor did not return a verdict". Fail-closed was working exactly as
    # designed; the deadline was simply wrong for the model.
    #
    # A generous default is the safe direction: too long merely makes a stuck
    # audit take longer to give up, while too short silently converts slow
    # into blocked, which reads as the lock system being broken.
    timeout_s: float = 300.0
    max_draft_chars: int = 12000

    VALID_STRICTNESS = ("lenient", "normal", "strict")

    @staticmethod
    def from_json(raw: Any) -> "AuditorSettings":
        data = _as_dict(raw or {}, "settings.auditor")
        strictness = _as_str(data.get("strictness", "normal"), "settings.auditor.strictness")
        _require(
            strictness in AuditorSettings.VALID_STRICTNESS,
            f"settings.auditor.strictness must be one of {AuditorSettings.VALID_STRICTNESS}",
        )
        return AuditorSettings(
            strictness=strictness,
            timeout_s=_as_float(data.get("timeout_s"), "settings.auditor.timeout_s", 45.0, lo=1.0, hi=600.0),
            max_draft_chars=_as_int(data.get("max_draft_chars"), "settings.auditor.max_draft_chars", 12000, lo=500, hi=200_000),
        )

    def to_json(self) -> dict:
        return {
            "strictness": self.strictness,
            "timeout_s": self.timeout_s,
            "max_draft_chars": self.max_draft_chars,
        }


@dataclass(frozen=True)
class RetentionSettings:
    """Spaced review of what has already been taught.

    `auto_relock` defaults off, and deliberately. Silently withdrawing access
    to something the user did learn is worse than letting a stale unlock stand,
    and a study aid that punishes a fortnight away from the desk gets turned
    off rather than obeyed.
    """

    enabled: bool = True
    review_after_days: int = 30
    # Extra days past the review date before `auto_relock` acts, so falling due
    # and being cut off never happen on the same morning.
    grace_days: int = 14
    auto_relock: bool = False

    @staticmethod
    def from_json(raw: Any) -> "RetentionSettings":
        data = _as_dict(raw or {}, "settings.retention")
        return RetentionSettings(
            enabled=_as_bool(data.get("enabled"), "settings.retention.enabled", True),
            review_after_days=_as_int(
                data.get("review_after_days"), "settings.retention.review_after_days",
                30, lo=0, hi=3650,
            ),
            grace_days=_as_int(
                data.get("grace_days"), "settings.retention.grace_days", 14, lo=0, hi=3650
            ),
            auto_relock=_as_bool(
                data.get("auto_relock"), "settings.retention.auto_relock", False
            ),
        )

    def to_json(self) -> dict:
        return {
            "enabled": self.enabled,
            "review_after_days": self.review_after_days,
            "grace_days": self.grace_days,
            "auto_relock": self.auto_relock,
        }


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool = True
    holding_days: int = 7
    auto_confirm: bool = False
    consolidate_on_session_end: bool = True
    delete_transcript_immediately: bool = False
    # Keep transcripts permanently in memory/archive instead of deleting
    # them once consolidation is confirmed. Off by default: the safe
    # default for a local assistant is not to accumulate a searchable
    # record of everything ever said. `delete_transcript_immediately`
    # still wins if both are set -- between two contradictory settings,
    # the more private one governs.
    keep_transcripts: bool = False

    @staticmethod
    def from_json(raw: Any) -> "MemorySettings":
        data = _as_dict(raw or {}, "settings.memory")
        return MemorySettings(
            enabled=_as_bool(data.get("enabled"), "settings.memory.enabled", True),
            holding_days=_as_int(data.get("holding_days"), "settings.memory.holding_days", 7, lo=0, hi=3650),
            auto_confirm=_as_bool(data.get("auto_confirm"), "settings.memory.auto_confirm", False),
            consolidate_on_session_end=_as_bool(
                data.get("consolidate_on_session_end"), "settings.memory.consolidate_on_session_end", True
            ),
            delete_transcript_immediately=_as_bool(
                data.get("delete_transcript_immediately"), "settings.memory.delete_transcript_immediately", False
            ),
            keep_transcripts=_as_bool(
                data.get("keep_transcripts"), "settings.memory.keep_transcripts", False
            ),
        )

    def to_json(self) -> dict:
        return {
            "enabled": self.enabled,
            "holding_days": self.holding_days,
            "auto_confirm": self.auto_confirm,
            "consolidate_on_session_end": self.consolidate_on_session_end,
            "delete_transcript_immediately": self.delete_transcript_immediately,
            "keep_transcripts": self.keep_transcripts,
        }


@dataclass(frozen=True)
class ContextSettings:
    """Token budget for the assembled prompt.

    `total_budget_tokens` covers everything sent to MAIN. `reserve_for_response`
    is held back so a long prompt cannot squeeze the reply to nothing.
    """

    total_budget_tokens: int = 6144
    reserve_for_response: int = 1024
    max_retrieved_chunks: int = 8
    chunk_tokens: int = 320
    chunk_overlap_tokens: int = 48

    @staticmethod
    def from_json(raw: Any) -> "ContextSettings":
        data = _as_dict(raw or {}, "settings.context")
        ctx = ContextSettings(
            total_budget_tokens=_as_int(data.get("total_budget_tokens"), "settings.context.total_budget_tokens", 6144, lo=512),
            reserve_for_response=_as_int(data.get("reserve_for_response"), "settings.context.reserve_for_response", 1024, lo=64),
            max_retrieved_chunks=_as_int(data.get("max_retrieved_chunks"), "settings.context.max_retrieved_chunks", 8, lo=0, hi=64),
            chunk_tokens=_as_int(data.get("chunk_tokens"), "settings.context.chunk_tokens", 320, lo=64, hi=4096),
            chunk_overlap_tokens=_as_int(data.get("chunk_overlap_tokens"), "settings.context.chunk_overlap_tokens", 48, lo=0, hi=1024),
        )
        _require(
            ctx.reserve_for_response < ctx.total_budget_tokens,
            "settings.context.reserve_for_response must be less than total_budget_tokens",
        )
        _require(
            ctx.chunk_overlap_tokens < ctx.chunk_tokens,
            "settings.context.chunk_overlap_tokens must be less than chunk_tokens",
        )
        return ctx

    def to_json(self) -> dict:
        return {
            "total_budget_tokens": self.total_budget_tokens,
            "reserve_for_response": self.reserve_for_response,
            "max_retrieved_chunks": self.max_retrieved_chunks,
            "chunk_tokens": self.chunk_tokens,
            "chunk_overlap_tokens": self.chunk_overlap_tokens,
        }


def _plugin_map(raw: Any) -> dict[str, str]:
    """Validate the plugin approval map.

    Values must be full hex digests. A malformed entry raises rather than being
    skipped: silently dropping a bad digest would turn a corrupted approval into
    "plugin not enabled", which is safe, but a caller reading the file would
    have no idea an approval had vanished.
    """
    if raw is None:
        return {}
    data = _as_dict(raw, "settings.enabled_plugins")
    out: dict[str, str] = {}
    for name, digest in data.items():
        key = _as_str(name, "settings.enabled_plugins key").strip()
        value = _as_str(digest, f"settings.enabled_plugins.{key}").strip().lower()
        _require(bool(key), "settings.enabled_plugins keys must not be empty")
        _require(
            bool(re.fullmatch(r"[0-9a-f]{64}", value)),
            f"settings.enabled_plugins.{key} must be a 64-character hex digest",
        )
        out[key] = value
    return out


@dataclass(frozen=True)
class Settings:
    """`vault/.protege/settings.json`.

    `system_prompt` is user-authored and starts empty. Protege never injects a
    vendor safety preamble, persona, or behavioral boilerplate. The only text
    added programmatically is the lock directive, the unlocked-topic list, and
    the active personality bands -- see `context/assembly.py`.
    """

    models: ModelSettings = field(default_factory=ModelSettings)
    lock_layers: LockLayerToggles = field(default_factory=LockLayerToggles)
    auditor: AuditorSettings = field(default_factory=AuditorSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    retention: RetentionSettings = field(default_factory=RetentionSettings)
    context: ContextSettings = field(default_factory=ContextSettings)
    system_prompt: str = ""
    skill_language: str = "python"
    vault_path: str = ""
    current_project: str = "default"
    # Local-file audit log of lock decisions. Off by default. Records which
    # layer fired on which topic and never the text involved -- see `audit.py`.
    logging_enabled: bool = False
    # Everyday mode. When on, the responder is given an unrestricted view of
    # the manifest and the lock layers stand down: it is an ordinary local
    # assistant. Persisted, because a mode you have to re-enable every launch
    # is not a mode. What keeps it from being a silent bypass is that it is
    # stated in the status bar and behind a banner across the top of the
    # window for as long as it is on.
    everyday_mode: bool = False
    # Plugin name -> the SHA-256 approved for it. A plugin absent from this map
    # is never loaded, and one whose file no longer matches is refused. There is
    # deliberately no "enable all".
    enabled_plugins: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    # NOTE: there is no `netguard_enabled`. The network guard installs
    # unconditionally in `run.py` before anything else is imported, and a
    # setting implying it could be switched off would have been a lie -- the
    # toggle existed briefly and did nothing, which is worse than no toggle.

    @staticmethod
    def from_json(raw: Any) -> "Settings":
        data = _as_dict(raw, "settings")
        version = _as_int(data.get("schema_version", SCHEMA_VERSION), "settings.schema_version", SCHEMA_VERSION, lo=1)
        _require(
            version <= SCHEMA_VERSION,
            f"settings.schema_version {version} is newer than this build supports ({SCHEMA_VERSION})",
        )
        project = _as_str(data.get("current_project", "default"), "settings.current_project")
        _require(bool(PROJECT_NAME_RE.match(project)), f"invalid project name {project!r}")
        return Settings(
            models=ModelSettings.from_json(data.get("models")),
            lock_layers=LockLayerToggles.from_json(data.get("lock_layers")),
            auditor=AuditorSettings.from_json(data.get("auditor")),
            memory=MemorySettings.from_json(data.get("memory")),
            retention=RetentionSettings.from_json(data.get("retention")),
            context=ContextSettings.from_json(data.get("context")),
            system_prompt=_as_str(data.get("system_prompt", ""), "settings.system_prompt"),
            skill_language=_as_str(data.get("skill_language", "python"), "settings.skill_language"),
            vault_path=_as_str(data.get("vault_path", ""), "settings.vault_path"),
            current_project=project,
            logging_enabled=_as_bool(data.get("logging_enabled"), "settings.logging_enabled", False),
            everyday_mode=_as_bool(data.get("everyday_mode"), "settings.everyday_mode", False),
            enabled_plugins=_plugin_map(data.get("enabled_plugins")),
            schema_version=version,
        )

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "models": self.models.to_json(),
            "lock_layers": self.lock_layers.to_json(),
            "auditor": self.auditor.to_json(),
            "memory": self.memory.to_json(),
            "retention": self.retention.to_json(),
            "context": self.context.to_json(),
            "system_prompt": self.system_prompt,
            "skill_language": self.skill_language,
            "vault_path": self.vault_path,
            "current_project": self.current_project,
            "logging_enabled": self.logging_enabled,
            "everyday_mode": self.everyday_mode,
            "enabled_plugins": dict(sorted(self.enabled_plugins.items())),
        }


# ---------------------------------------------------------------------------
# Personality
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Trait:
    """A personality dimension with five descriptive bands.

    The slider value never reaches the model. An 8B model does not reliably
    distinguish "formality: 60" from "formality: 70" -- numbers in a prompt are
    weakly grounded -- so the value only selects which band's *prose* is
    injected. See `band_for_value`.

    `builtin` marks traits Protege ships. It affects nothing about behavior:
    shipped band text is fully editable, exactly like a custom trait's.
    """

    id: str
    label: str
    bands: tuple[str, str, str, str, str]
    default_value: int = 50
    builtin: bool = False

    @staticmethod
    def from_json(raw: Any) -> "Trait":
        data = _as_dict(raw, "trait")
        bands_raw = _as_list(data.get("bands", []), "trait.bands")
        _require(
            len(bands_raw) == BAND_COUNT,
            f"trait.bands must have exactly {BAND_COUNT} entries, got {len(bands_raw)}",
        )
        bands = []
        for i, band in enumerate(bands_raw):
            text = _as_str(band, f"trait.bands[{i}]").strip()
            _require(bool(text), f"trait.bands[{i}] must not be empty")
            bands.append(text)
        trait_id = _as_str(data.get("id", ""), "trait.id").strip().lower()
        _require(bool(TRAIT_ID_RE.match(trait_id)), f"invalid trait id {trait_id!r}")
        label = _as_str(data.get("label", ""), "trait.label").strip()
        _require(bool(label), "trait.label must not be empty")
        return Trait(
            id=trait_id,
            label=label,
            bands=tuple(bands),  # type: ignore[arg-type]
            default_value=_as_int(data.get("default_value"), "trait.default_value", 50, lo=0, hi=100),
            builtin=_as_bool(data.get("builtin"), "trait.builtin", False),
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "bands": list(self.bands),
            "default_value": self.default_value,
            "builtin": self.builtin,
        }


def band_for_value(value: int) -> int:
    """Map a 0-100 slider position to a zero-indexed band.

    Bands cover 0-20, 21-40, 41-60, 61-80, 81-100 as specified. Band 2 (the
    41-60 band) is neutral; traits sitting there are omitted from the prompt
    entirely rather than injected as "balanced" filler.
    """
    _require(isinstance(value, int) and not isinstance(value, bool), "trait value must be an integer")
    _require(0 <= value <= 100, f"trait value must be 0-100, got {value}")
    if value <= 20:
        return 0
    if value <= 40:
        return 1
    if value <= 60:
        return 2
    if value <= 80:
        return 3
    return 4


@dataclass(frozen=True)
class PersonalityProfile:
    name: str
    values: dict[str, int] = field(default_factory=dict)

    @staticmethod
    def from_json(name: str, raw: Any) -> "PersonalityProfile":
        data = _as_dict(raw, f"profile {name!r}")
        values_raw = _as_dict(data.get("values", {}), f"profile {name!r}.values")
        values: dict[str, int] = {}
        for key, val in values_raw.items():
            trait_id = _as_str(key, "profile trait id").strip().lower()
            _require(bool(TRAIT_ID_RE.match(trait_id)), f"invalid trait id {trait_id!r} in profile {name!r}")
            values[trait_id] = _as_int(val, f"profile {name!r}.values.{trait_id}", 50, lo=0, hi=100)
        return PersonalityProfile(name=name, values=values)

    def to_json(self) -> dict:
        return {"values": dict(sorted(self.values.items()))}


@dataclass(frozen=True)
class Personality:
    """`vault/.protege/personality.json`.

    Trait *definitions* (id, label, band prose) are stored once and shared;
    profiles hold only id -> slider value. The brief's example inlined `value`
    into the trait definition, which cannot express two profiles over the same
    trait set -- this split is the same data, factored so profiles work.
    """

    traits: tuple[Trait, ...] = ()
    profiles: tuple[PersonalityProfile, ...] = ()
    active_profile: str = "default"
    max_active_traits: int = 8
    schema_version: int = SCHEMA_VERSION

    def trait(self, trait_id: str) -> Trait | None:
        for t in self.traits:
            if t.id == trait_id:
                return t
        return None

    def profile(self, name: str) -> PersonalityProfile | None:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def active(self) -> PersonalityProfile:
        found = self.profile(self.active_profile)
        if found is not None:
            return found
        # Fail-soft is correct here and only here: personality is cosmetic, and
        # a missing profile must not block a response. The lock system has no
        # equivalent fallback.
        return PersonalityProfile(name=self.active_profile, values={})

    @staticmethod
    def from_json(raw: Any) -> "Personality":
        data = _as_dict(raw, "personality")
        version = _as_int(data.get("schema_version", SCHEMA_VERSION), "personality.schema_version", SCHEMA_VERSION, lo=1)
        _require(
            version <= SCHEMA_VERSION,
            f"personality.schema_version {version} is newer than this build supports ({SCHEMA_VERSION})",
        )
        traits = tuple(Trait.from_json(t) for t in _as_list(data.get("traits", []), "personality.traits"))
        seen_ids = [t.id for t in traits]
        _require(len(seen_ids) == len(set(seen_ids)), "personality.traits contains duplicate trait ids")
        raw_profiles = _as_dict(data.get("profiles", {}), "personality.profiles")
        profiles = tuple(
            PersonalityProfile.from_json(name, body) for name, body in sorted(raw_profiles.items())
        )
        return Personality(
            traits=traits,
            profiles=profiles,
            active_profile=_as_str(data.get("active_profile", "default"), "personality.active_profile"),
            max_active_traits=_as_int(data.get("max_active_traits"), "personality.max_active_traits", 8, lo=1, hi=64),
            schema_version=version,
        )

    def to_json(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "traits": [t.to_json() for t in self.traits],
            "profiles": {p.name: p.to_json() for p in self.profiles},
            "active_profile": self.active_profile,
            "max_active_traits": self.max_active_traits,
        }
