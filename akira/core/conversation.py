"""Conversations, and running a turn against a model.

Deliberately free of any UI concept. A turn is: build the prompt, stream the
reply, stop when asked. Everything about how that is *displayed* belongs to the
bridge above it.
"""

from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable, Sequence

from akira.models.base import ChatMessage, GenerationResult, ModelBackend
from akira.models.think_filter import ThinkFilter

from .config import AppConfig
from .models import ModelRouter, Route

#: Said to every model Akira runs, its agents included.
#:
#: A web address is the one kind of detail a model invents without feeling
#: unsure: the shape of `youtube.com/watch?v=...` is deeply familiar, while the
#: eleven characters that pick the video carry no meaning to reason from. So it
#: writes something of the right shape, and the link leads nowhere. The same
#: goes for a title, a page number or a part number it "remembers".
NO_INVENTED_ADDRESSES = (
    "Never write a web address unless something in this conversation gave it to "
    "you: a search result, a page that was read, a file. The part of an address "
    "that picks out a video or a page cannot be worked out from what it is "
    "about, so one you write yourself looks right and leads nowhere. Name what "
    "to search for instead, and say plainly that you cannot check it."
)

#: Said in the chat, where a drawing in a reply is shown as a picture
#: (`akira.core.making.svg`).
DRAWING = (
    "When asked to draw something, such as an icon, a logo or a diagram, you "
    "can: write it as one SVG in a ```svg code block, with a viewBox, using "
    "shapes, paths, gradients and text. It is shown as a picture. Scripts, "
    "links and images from elsewhere are removed before it is shown."
)

#: Said in the chat, which has no tools. Without it a model asked to set a
#: reminder answers "Reminder set for 5 PM", and asked to remember something
#: answers "Noted", and neither happened.
CHAT_LIMITS = (
    "In this conversation you can only talk. You cannot set reminders or "
    "alarms, send messages or email, open, read or change files, browse the "
    "web, or remember anything after this conversation ends, unless something "
    "below gives you what you need. Never say or imply that you did any of "
    "these. Say plainly that you cannot, and what the person can use instead: "
    "a job in Schedule for a reminder, or an agent in Agents for a task that "
    "reads their files, mail or the web, or acts."
)

DEFAULT_SYSTEM_PROMPT = (
    "You are Akira, a capable assistant running entirely on the user's own "
    "machine; if asked what you are, say so. Be direct and concrete. Prefer a "
    "short, correct answer to a long, hedged one. When you are unsure, say so "
    "plainly rather than inventing detail. For arithmetic, dates and times, "
    "work it through step by step and check the result. Use Markdown for "
    "structure only when it genuinely helps. "
    + NO_INVENTED_ADDRESSES + " " + CHAT_LIMITS + " " + DRAWING
)

#: Reserved above the reply budget for the system prompt and formatting overhead
#: the tokenizer count does not see.
_CONTEXT_HEADROOM = 256


class Cancelled(Exception):
    """Raised inside the token callback to unwind a generation in progress.

    A Python thread cannot be killed, so cancellation has to be cooperative:
    the callback raises, which unwinds llama.cpp's streaming loop from the
    inside. Anything else leaves a 5 GB model pinned to a turn nobody wants.
    """


@dataclass
class Message:
    role: str
    """``user`` | ``assistant`` | ``system``"""

    text: str = ""

    #: From `secrets`, not `uuid`. verify_offline.py classifies `uuid` as a
    #: networking module — correctly, since `uuid.getnode()` and `uuid1()` read
    #: network interfaces, and a static scan cannot tell which function will be
    #: called. `token_hex` is unique enough for message ids and has no such path.
    id: str = field(default_factory=lambda: secrets.token_hex(8))
    created: float = field(default_factory=time.time)

    #: Set when a turn failed. The interface shows these differently — an error
    #: dressed as an answer is worse than no answer.
    error: bool = False


@dataclass
class Conversation:
    """One thread of messages."""

    id: str = field(default_factory=lambda: secrets.token_hex(8))
    title: str = ""
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    project: str = ""
    """The id of the project it was held in, or "" outside any."""

    def add(self, role: str, text: str = "", *, error: bool = False) -> Message:
        message = Message(role=role, text=text, error=error)
        self.messages.append(message)
        return message

    @property
    def last_user_text(self) -> str:
        for message in reversed(self.messages):
            if message.role == "user":
                return message.text
        return ""

    def derive_title(self, limit: int = 48) -> str:
        """A title from the opening question.

        A model could write a better one, but that costs a second round trip
        before the first answer arrives. The first line of what you asked is
        right often enough to not be worth the latency.
        """
        text = " ".join(self.last_user_text.split())
        if not text:
            return "New chat"
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"


def build_prompt(
    conversation: Conversation,
    backend: ModelBackend,
    *,
    reply_budget: int,
    extra_system: str = "",
) -> list[ChatMessage]:
    """Assemble the messages to send, newest-first until the context is full.

    Truncation drops the *oldest* turns, never the system prompt and never the
    most recent question. Dropping from the front is what keeps a long
    conversation coherent — the last few exchanges carry almost all the
    relevant context, and the opening small talk carries almost none.

    \a extra_system is context for this turn only — the open project, what was
    retrieved — added after the system prompt and never saved with the
    conversation.
    """
    limit = max(512, backend.n_ctx - reply_budget - _CONTEXT_HEADROOM)

    prompt = conversation.system_prompt
    if extra_system.strip():
        prompt = f"{prompt}\n\n{extra_system.strip()}"
    system = ChatMessage(role="system", content=prompt)
    used = backend.count_tokens(prompt)

    kept: list[ChatMessage] = []
    for message in reversed(conversation.messages):
        if message.role not in ("user", "assistant") or not message.text:
            continue
        cost = backend.count_tokens(message.text) + 4
        if used + cost > limit and kept:
            break
        used += cost
        kept.append(ChatMessage(role=message.role, content=message.text))

    kept.reverse()
    return [system, *kept]


class Responder:
    """Runs one turn against whichever model the router selects."""

    def __init__(self, router: ModelRouter, config: AppConfig) -> None:
        self._router = router
        self._config = config

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def respond(
        self,
        conversation: Conversation,
        *,
        route: Route = Route.CHAT,
        on_token: Callable[[str], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
        extra_system: str = "",
    ) -> GenerationResult:
        """Generate a reply to the conversation as it stands.

        \a on_token receives text already stripped of reasoning blocks, so a
        caller can append it straight to the view. \a is_cancelled is polled on
        every token; returning True raises `Cancelled` out of the generation.
        \a extra_system is this turn's context; see `build_prompt`.
        """
        resolved = self._router.resolve(route)
        model = self._config.models.get(resolved.value)
        reply_budget = model.max_tokens if model else 1024

        # Some models narrate their reasoning between <think> tags. Left in the
        # stream they appear as the answer, which is both wrong and alarming.
        thinking = ThinkFilter()

        def emit(chunk: str) -> None:
            if is_cancelled is not None and is_cancelled():
                raise Cancelled()
            visible = thinking.feed(chunk)
            if visible and on_token is not None:
                on_token(visible)

        with self._router.acquire(resolved) as backend:
            messages = build_prompt(conversation, backend, reply_budget=reply_budget,
                                    extra_system=extra_system)
            result = backend.generate(
                messages,
                max_tokens=reply_budget,
                temperature=model.temperature if model else 0.7,
                top_p=model.top_p if model else 0.95,
                on_token=emit,
            )

        tail = thinking.flush()
        if tail and on_token is not None:
            on_token(tail)

        return result


def route_for(text: str, follows_code: bool = False) -> Route:
    """Guess which route a message wants.

    A keyword heuristic, and honest about it: it exists so that asking about
    code reaches the code model without anyone selecting it, and it is wrong
    often enough that the choice stays visible and overridable in the
    interface. A model-based classifier would be better and costs a round trip
    before every answer, which is the thing this rebuild is trying to avoid.
    """
    if _CODE_SIGNALS.search(text) or "```" in text:
        return Route.CODE
    # A follow-up to an answer that held code ("now make it ignore case") is
    # still about that code, and switching models mid-thread both costs a
    # reload and hands the thread to a model that did not write it.
    if follows_code and len(text) <= _FOLLOW_UP_CHARS:
        return Route.CODE
    return Route.CHAT


#: Words that mean code, as whole words: "capital" is not "api", nor "trust" Rust.
_CODE_SIGNALS = re.compile(
    r"\b(code|coding|def|bug|debug|traceback|stack trace|compile[rsd]?|refactor\w*|"
    r"unit tests?|regex|sql|api|python|javascript|typescript|rust|qml|java|golang|"
    r"html|css|json|yaml|bash|powershell)\b|\bfunctions?\b(?!\s+of\b)|\bc\+\+|"
    r"\bclass\s+\w+\s*[(:]",
    re.IGNORECASE)

#: How long a message may be and still count as a follow-up to code.
_FOLLOW_UP_CHARS = 400
