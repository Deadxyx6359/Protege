"""Explicit token budgeting for the prompt sent to MAIN.

Priority order, highest first. Lower items are truncated first:

1. Lock directive + unlocked topic list -- **never truncated**
2. Personality bands (active traits only)
3. `project.md`
4. Retrieved notes (scoped to unlocked topics, relevance-ranked)
5. Live session memory
6. Recent conversation turns

Two things about this ordering are worth stating plainly.

**The directive is allocated before anything else and is never evictable.**
Everything else negotiates over what is left. This is the mechanism behind the
brief's requirement that personality lose to the lock directive under pressure:
if the two competed on equal terms, lock compliance would degrade in proportion
to how much personality the user had configured, and a security control whose
strength depends on an unrelated cosmetic setting is not a control.

**Conversation history is truncated before retrieved notes.** That is the
brief's ordering and it is unusual -- most systems keep recent turns and drop
retrieval. It is defensible here because the *current* user message is
mandatory and is never part of what gets trimmed; only prior turns are. A
teaching assistant grounded in the user's own notes is more useful than one
grounded in what it said four messages ago.

Nothing is dropped silently. Every truncation produces a notice the UI shows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

from ..chat import Conversation
from ..lock.directive import build_directive, build_everyday_preamble
from ..lock.retrieval import RetrievalResult, format_chunks
from ..models import ChatMessage
from ..personality.prompt import build_personality_prompt, truncate_personality
from ..schemas import Manifest, Personality, PersonalityProfile, Settings

TokenCounter = Callable[[str], int]

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Fallback counter used only when no model is loaded.

    The context assembler prefers the loaded model's own tokenizer, because a
    budget measured with the wrong tokenizer is a budget that overflows without
    warning. This exists so the assembler can be exercised -- in tests, and in
    the Settings preview -- before any model is resident.
    """
    return max(0, int(len(text) / CHARS_PER_TOKEN + 0.5))


@dataclass(frozen=True)
class Section:
    """One budgeted piece of the prompt."""

    name: str
    priority: int
    text: str
    tokens: int
    evictable: bool = True
    truncated: bool = False
    dropped_items: int = 0
    note: str = ""

    @property
    def present(self) -> bool:
        return bool(self.text.strip())


@dataclass
class AssembledContext:
    """The finished prompt, plus everything needed to explain it."""

    system_prompt: str
    messages: list[ChatMessage]
    sections: list[Section] = field(default_factory=list)
    used_tokens: int = 0
    budget_tokens: int = 0
    reserve_tokens: int = 0
    notices: list[str] = field(default_factory=list)
    over_budget: bool = False

    @property
    def usage_line(self) -> str:
        """The status-line summary."""
        pct = int(100 * self.used_tokens / self.budget_tokens) if self.budget_tokens else 0
        base = f"context {self.used_tokens}/{self.budget_tokens} tokens ({pct}%)"
        if self.over_budget:
            return base + " OVER BUDGET"
        if self.notices:
            return base + f", {len(self.notices)} truncation(s)"
        return base

    def section(self, name: str) -> Section | None:
        for section in self.sections:
            if section.name == name:
                return section
        return None

    def render_for_viewer(self) -> str:
        """The assembled-prompt panel's contents.

        The brief asks for the fully assembled system prompt to be viewable so
        the user can see exactly what MAIN received. Showing the budget
        breakdown alongside it turns "why did it ignore my note" into a
        question with a visible answer.
        """
        lines = [
            f"BUDGET: {self.used_tokens}/{self.budget_tokens} tokens "
            f"(reserve for response: {self.reserve_tokens})",
            "",
            "SECTIONS (priority order; lower is truncated first):",
        ]
        for section in self.sections:
            flag = ""
            if not section.present:
                flag = "  [empty]"
            elif section.truncated:
                flag = f"  [TRUNCATED, {section.dropped_items} item(s) dropped]"
            elif not section.evictable:
                flag = "  [never truncated]"
            lines.append(f"  {section.priority}. {section.name}: {section.tokens} tokens{flag}")
            if section.note:
                lines.append(f"       {section.note}")
        if self.notices:
            lines.append("")
            lines.append("NOTICES:")
            lines.extend(f"  - {n}" for n in self.notices)
        lines.append("")
        lines.append("=" * 60)
        lines.append("ASSEMBLED SYSTEM PROMPT")
        lines.append("=" * 60)
        lines.append(self.system_prompt)
        lines.append("")
        lines.append("=" * 60)
        lines.append("MESSAGES")
        lines.append("=" * 60)
        for message in self.messages:
            if message.role == "system":
                lines.append("[system] (shown above)")
            else:
                lines.append(f"[{message.role}] {message.content}")
        return "\n".join(lines)


TRUNCATION_MARKER = "\n[... truncated to fit the context budget ...]"


def truncate_to_tokens(text: str, limit: int, count: TokenCounter) -> tuple[str, bool]:
    """Cut `text` down to at most `limit` tokens, marker included.

    Binary search over character length rather than a fixed chars-per-token
    ratio, so this stays correct with any tokenizer -- including one whose
    ratio differs sharply from English prose, such as a note full of code or
    CJK text.

    The marker counts against the limit. It is real text that goes to the model,
    so excluding it would make every truncated section overshoot its allocation
    by a handful of tokens -- and those overshoots accumulate across five
    sections into a budget that is quietly wrong.
    """
    if limit <= 0:
        return "", bool(text)
    if count(text) <= limit:
        return text, False

    marker_tokens = count(TRUNCATION_MARKER)
    body_limit = limit - marker_tokens
    if body_limit <= 0:
        # Not even room to say that something was cut. Dropping the section
        # entirely is still announced, via the caller's notice.
        return "", True

    low, high = 0, len(text)
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid]
        if count(candidate) <= body_limit:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return best.rstrip() + TRUNCATION_MARKER, True


class ContextAssembler:
    """Builds the prompt for one turn, within an explicit token budget."""

    def __init__(self, settings: Settings, count_tokens: TokenCounter | None = None) -> None:
        self._settings = settings
        self._count = count_tokens or estimate_tokens

    def assemble(
        self,
        *,
        manifest: Manifest,
        personality: Personality,
        profile: PersonalityProfile | None = None,
        project_doc: str = "",
        retrieval: RetrievalResult | None = None,
        live_memory: str = "",
        conversation: Conversation | None = None,
        user_text: str,
        memory_tool: bool = False,
        attached_files: Sequence[tuple[str, str]] = (),
    ) -> AssembledContext:
        count = self._count
        ctx = self._settings.context
        budget = ctx.total_budget_tokens
        reserve = ctx.reserve_for_response
        available = budget - reserve

        conversation = conversation or Conversation()
        retrieval = retrieval or RetrievalResult()
        notices: list[str] = []
        sections: list[Section] = []

        # -- mandatory: the directive and the user's current message ---------
        has_notes = bool(retrieval.chunks or project_doc.strip() or live_memory.strip())
        # Everyday mode swaps the constraint for a plain preamble. The slot is
        # the same one either way -- assembled first, never evicted -- so the
        # budgeting below does not have to care which mode is running.
        directive = (
            build_everyday_preamble(has_context_notes=has_notes)
            if manifest.unrestricted
            else build_directive(manifest.unlocked_topics, has_context_notes=has_notes)
        )
        directive_tokens = count(directive.text)
        user_tokens = count(user_text)

        authored = self._settings.system_prompt.strip()
        authored_tokens = count(authored) if authored else 0

        # The user's own system prompt is treated as mandatory alongside the
        # directive. It is entirely user-authored, and silently trimming what
        # someone deliberately wrote would be a worse surprise than running
        # over budget -- which is reported rather than hidden.
        fixed = directive_tokens + user_tokens + authored_tokens
        remaining = available - fixed
        if remaining < 0:
            notices.append(
                f"the lock directive, your system prompt and this message alone need {fixed} tokens, "
                f"over the {available}-token working budget; nothing else could be included"
            )
            remaining = 0

        sections.append(
            Section(
                name="system prompt (yours)",
                priority=0,
                text=authored,
                tokens=authored_tokens,
                evictable=False,
            )
        )

        # -- priority 2 (a): the remember() tool -----------------------------
        # All-or-nothing. A half-truncated tool description produces malformed
        # REMEMBER lines that the parser drops, so the model would appear to be
        # recording things while nothing reached disk -- worse than not offering
        # the tool at all. Included whole or omitted whole, and omission is
        # announced.
        tool_text = ""
        tool_tokens = 0
        if memory_tool:
            from ..memory.live import remember_tool_description

            candidate = remember_tool_description(manifest.unlocked_topics)
            candidate_tokens = count(candidate)
            if candidate_tokens <= remaining:
                tool_text = candidate
                tool_tokens = candidate_tokens
                remaining -= tool_tokens
            else:
                notices.append(
                    "the remember() tool description did not fit the context budget, so the model "
                    "cannot propose memory writes this turn"
                )
        sections.append(
            Section(
                name="remember() tool",
                priority=2,
                text=tool_text,
                tokens=tool_tokens,
                truncated=bool(memory_tool and not tool_text),
                note="offered" if tool_text else ("dropped for budget" if memory_tool else "not available at this tier"),
            )
        )

        # -- priority 2: personality ----------------------------------------
        personality_prompt = build_personality_prompt(personality, profile)
        personality_text = personality_prompt.text
        personality_tokens = count(personality_text) if personality_text else 0
        personality_truncated = False
        if personality_text and personality_tokens > remaining:
            # Shed trait lines until it fits. The directive is not in the
            # running -- it was allocated before this loop began.
            line_count = len(personality_text.splitlines()) - 1
            while line_count > 0:
                line_count -= 1
                candidate = truncate_personality(personality_text, line_count)
                if count(candidate) <= remaining:
                    personality_text = candidate
                    personality_truncated = True
                    break
            else:
                personality_text = ""
                personality_truncated = True
            personality_tokens = count(personality_text) if personality_text else 0
            notices.append("personality was truncated to keep the lock directive intact")
        remaining -= personality_tokens

        if personality_prompt.over_cap:
            notices.append(
                f"{len(personality_prompt.dropped)} trait(s) beyond the "
                f"{personality.max_active_traits}-trait cap were not injected: "
                + ", ".join(personality_prompt.dropped)
            )

        sections.append(
            Section(
                name="personality bands",
                priority=2,
                text=personality_text,
                tokens=personality_tokens,
                truncated=personality_truncated,
                note=(f"{len(personality_prompt.used)} active trait(s)" if personality_prompt.used else "all neutral"),
            )
        )

        # -- priority 3: project.md -----------------------------------------
        doc_text, doc_truncated = truncate_to_tokens(project_doc.strip(), remaining, count)
        doc_tokens = count(doc_text) if doc_text else 0
        remaining -= doc_tokens
        if doc_truncated:
            notices.append("project.md was truncated to fit the context budget")
        sections.append(
            Section(
                name="project.md",
                priority=3,
                text=doc_text,
                tokens=doc_tokens,
                truncated=doc_truncated,
            )
        )

        # -- priority 3.5: files the user attached this session --------------
        # Above retrieved notes: an explicit attachment is a stronger signal of
        # relevance than a BM25 match, and the user chose it by hand this very
        # session. Attachment content is user-supplied, so it is not gated on
        # the way in -- the directive's "notes provided in context" clause
        # covers it, and MAIN's *output* about it still passes Layers 4-5.
        attach_parts: list[str] = []
        attach_tokens = 0
        dropped_attachments = 0
        any_attachment_cut = False
        for name, content in attached_files:
            piece = f"[attached file: {name}]\n{content.strip()}"
            piece, piece_cut = truncate_to_tokens(piece, remaining - attach_tokens, count)
            if not piece:
                dropped_attachments += 1
                continue
            attach_parts.append(piece)
            attach_tokens += count(piece)
            if piece_cut:
                any_attachment_cut = True
                notices.append(f"attached file {name!r} was truncated to fit the context budget")
        attach_text = "\n\n".join(attach_parts)
        remaining -= attach_tokens
        if dropped_attachments:
            notices.append(
                f"{dropped_attachments} attached file(s) did not fit the context budget at all"
            )
        sections.append(
            Section(
                name="attached files",
                priority=4,
                text=attach_text,
                tokens=attach_tokens,
                truncated=any_attachment_cut or bool(dropped_attachments),
                dropped_items=dropped_attachments,
                note=f"{len(attached_files)} attached" if attached_files else "",
            )
        )

        # -- priority 4: retrieved notes ------------------------------------
        kept_chunks = []
        dropped_chunks = 0
        notes_tokens = 0
        for scored in retrieval.chunks:
            piece = format_chunks([scored])
            piece_tokens = count(piece)
            if notes_tokens + piece_tokens > remaining:
                dropped_chunks += 1
                continue
            kept_chunks.append(scored)
            notes_tokens += piece_tokens
        notes_text = format_chunks(kept_chunks)
        remaining -= notes_tokens
        if dropped_chunks:
            # Said out loud rather than dropped quietly: an answer built on half
            # the notes, presented as though built on all of them, is worse than
            # a short answer that admits it was short.
            notices.append(
                f"{dropped_chunks} retrieved note chunk(s) did not fit the context budget and "
                "were not shown to the model"
            )
        sections.append(
            Section(
                name="retrieved notes",
                priority=4,
                text=notes_text,
                tokens=notes_tokens,
                truncated=bool(dropped_chunks),
                dropped_items=dropped_chunks,
                note=retrieval.note(),
            )
        )

        # -- priority 5: live session memory --------------------------------
        memory_text, memory_truncated = truncate_to_tokens(live_memory.strip(), remaining, count)
        memory_tokens = count(memory_text) if memory_text else 0
        remaining -= memory_tokens
        if memory_truncated:
            notices.append("live session memory was truncated to fit the context budget")
        sections.append(
            Section(
                name="live session memory",
                priority=5,
                text=memory_text,
                tokens=memory_tokens,
                truncated=memory_truncated,
            )
        )

        # -- priority 6: recent conversation turns --------------------------
        history: list[ChatMessage] = []
        history_tokens = 0
        dropped_turns = 0
        for message in reversed(conversation.messages):
            message_tokens = count(message.content)
            if history_tokens + message_tokens > remaining:
                dropped_turns += 1
                continue
            history.insert(0, message)
            history_tokens += message_tokens
        remaining -= history_tokens
        if dropped_turns:
            notices.append(f"{dropped_turns} earlier conversation turn(s) dropped to fit the budget")
        sections.append(
            Section(
                name="conversation history",
                priority=6,
                text=f"{len(history)} message(s)",
                tokens=history_tokens,
                truncated=bool(dropped_turns),
                dropped_items=dropped_turns,
            )
        )

        # -- compose ---------------------------------------------------------
        parts: list[str] = []
        if authored:
            parts.append(authored)
        if tool_text:
            parts.append(tool_text)
        if personality_text:
            parts.append(personality_text)
        if doc_text:
            parts.append("PROJECT CONTEXT:\n" + doc_text)
        if attach_text:
            parts.append("FILES THE USER ATTACHED:\n" + attach_text)
        if notes_text:
            parts.append("NOTES FROM YOUR VAULT:\n" + notes_text)
        if memory_text:
            parts.append("THIS SESSION'S MEMORY:\n" + memory_text)
        # Last. Always. See the module docstring.
        parts.append(directive.text)

        system_prompt = "\n\n".join(parts)

        sections.append(
            Section(
                name="lock directive",
                priority=1,
                text=directive.text,
                tokens=directive_tokens,
                evictable=False,
                note=f"{len(manifest.unlocked_topics)} unlocked topic(s)",
            )
        )
        sections.sort(key=lambda s: s.priority)

        messages = [ChatMessage(role="system", content=system_prompt)]
        messages.extend(history)
        messages.append(ChatMessage(role="user", content=user_text))

        used = count(system_prompt) + history_tokens + user_tokens
        return AssembledContext(
            system_prompt=system_prompt,
            messages=messages,
            sections=sections,
            used_tokens=used,
            budget_tokens=budget,
            reserve_tokens=reserve,
            notices=notices,
            over_budget=used > available,
        )
