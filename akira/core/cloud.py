"""Claude, through Anthropic's API, for a chat or a piece of work the person sends to it.

Off until the person chooses it in the chat window. Then:

  * **Their own key**, sealed with DPAPI like every other secret (`model.anthropic`),
    and sent only in the `x-api-key` header of a request to api.anthropic.com. It
    never reaches a model.
  * **One door.** Each request goes through `akira.core.net.client.call`, under
    `model.cloud` for "anthropic", which the person grants by connecting and can
    take back in Permissions. The activity log has every request, without its
    contents.
  * **What leaves the computer** is what the chat would give the local model: the
    conversation, and what Akira found for this turn in the person's files, on the
    web or in a chip's library; for "Do it", the task and whatever the team reads.
    The composer says so while Claude is chosen.

Claude Opus 5.5 (`claude-opus-5-5`): its thinking is always on and cannot be
turned off, so it is steered by effort, high for code and agents, medium for an
everyday answer. A reply Opus declines is passed on server-side to the model
Anthropic routes it to (`fallbacks: "default"`). Akira's door reads a reply
whole, so a reply is not streamed: it appears when it is done.

Akira's API code is raw HTTP, not Anthropic's SDK, on purpose: the SDK opens its
own connections, around the door every other request goes through, and
`verify_offline.py` refuses it by name.
"""

from __future__ import annotations

import json
import re
import threading
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Callable, Iterator, Sequence

from akira.core import files
from akira.core.config import config_dir
from akira.core.models import Route
from akira.core.net import NetError
from akira.core.net.client import call
from akira.core.permissions import AuditLog, Policy, SecretError, SecretStore
from akira.models.base import (ChatMessage, GenerationResult, ModelError, ModelSpec,
                               ModelBackend, ModelUnavailable, Role)

MODEL = "claude-opus-5-5"
LABEL = "Claude Opus 5.5"
HOST = "api.anthropic.com"
MESSAGES_URL = f"https://{HOST}/v1/messages"
MODEL_URL = f"https://{HOST}/v1/models/{MODEL}"
API_VERSION = "2023-06-01"
#: The `fallbacks: "default"` form is gated by this header, and only this one.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SECRET = "model.anthropic"
CAPABILITY = "model.cloud"
SCOPE = "anthropic"

#: A reply's room, thinking included. Not streamed, so kept to what a single
#: request returns well inside its time.
MAX_TOKENS = 16_000
TIMEOUT_S = 600.0
MAX_REPLY_BYTES = 4_000_000
#: The most Akira sends in one request, though the model takes far more: a chat
#: or a run that grew past it has its oldest parts cut, as for the local models.
CONTEXT = 200_000

#: Dollars a million tokens, read and written, for the month's tally.
PRICE_IN = 4.0
PRICE_OUT = 20.0

_KEY = re.compile(r"\Ask-ant-[A-Za-z0-9_\-]{20,}\Z")

_REFUSED = {
    400: "Anthropic could not use the request: {detail}",
    401: "Anthropic refused the API key. Check it, or add it again from the chat's model menu.",
    403: "This API key may not use Claude Opus 5.5.",
    404: "Anthropic does not know Claude Opus 5.5 for this key.",
    413: "That was too much to send to Claude at once.",
    429: "Claude's usage limit for this key was reached. Wait a minute, or check your plan.",
    500: "Anthropic's servers had a problem. Try again in a moment.",
    529: "Anthropic's servers are overloaded. Try again in a moment.",
}


class Spend:
    """What Claude was asked and wrote this month, in `cloud_usage.json`, and what that
    comes to at its list prices."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else config_dir() / "cloud_usage.json"
        self._lock = threading.Lock()

    @staticmethod
    def _month() -> str:
        return date.today().strftime("%Y-%m")

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) and data.get("month") == self._month() else {}

    def add(self, read: int, written: int) -> None:
        with self._lock:
            data = self._load()
            data = {"month": self._month(), "read": int(data.get("read", 0)) + read,
                    "written": int(data.get("written", 0)) + written}
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps(data), encoding="utf-8")
                files.replace(temporary, self.path)
            except OSError:
                pass

    def month(self) -> dict:
        data = self._load()
        read, written = int(data.get("read", 0)), int(data.get("written", 0))
        return {"read": read, "written": written,
                "dollars": round(read / 1e6 * PRICE_IN + written / 1e6 * PRICE_OUT, 2)}


def request(messages: Sequence[ChatMessage], effort: str) -> dict:
    """The Messages API request for Akira's \a messages: its system messages joined
    into `system`, the rest in turns, a turn of one speaker's messages made one."""
    system = "\n\n".join(m.content for m in messages if m.role == "system" and m.content)
    turns: list[dict] = []
    for message in messages:
        if message.role not in ("user", "assistant"):
            continue
        text = message.content if message.content.strip() else "…"
        if turns and turns[-1]["role"] == message.role:
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": message.role, "content": text})
    if not turns or turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": "(The conversation so far follows.)"})
    if turns[-1]["role"] != "user":
        # Opus 5.5 does not continue a reply of its own: it answers a person.
        turns.append({"role": "user", "content": "Go on."})
    payload = {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": turns,
               "output_config": {"effort": effort}, "fallbacks": "default"}
    if system:
        payload["system"] = system
    return payload


def reply_of(data: dict) -> tuple[str, str]:
    """The text of a Messages API reply and why it ended: `stop`, `length` or `refused`."""
    blocks = data.get("content") if isinstance(data.get("content"), list) else []
    text = "".join(str(b.get("text") or "") for b in blocks
                   if isinstance(b, dict) and b.get("type") == "text")
    stop = str(data.get("stop_reason") or "")
    if stop == "refusal":
        details = data.get("stop_details") if isinstance(data.get("stop_details"), dict) else {}
        category = str(details.get("category") or "").replace("_", " ")
        said = "Claude declined to answer this" + (f" ({category})" if category else "") + "."
        return (text.rstrip() + "\n\n" + said) if text.strip() else said, "refused"
    return text, "length" if stop == "max_tokens" else "stop"


class ClaudeBackend(ModelBackend):
    """Claude Opus 5.5 as a model the chat and the agents can use like a local one."""

    def __init__(self, *, policy: Callable[[], Policy], secrets: SecretStore,
                 audit: AuditLog | None = None, effort: str = "high",
                 spend: Spend | None = None, actor: str = "assistant") -> None:
        super().__init__(ModelSpec(path=MODEL, role=Role.MAIN, n_ctx=CONTEXT))
        self._policy = policy
        self._secrets = secrets
        self._audit = audit
        self._effort = effort
        self._spend = spend if spend is not None else Spend()
        self._actor = actor

    @property
    def label(self) -> str:
        return LABEL

    @property
    def is_loaded(self) -> bool:
        return True

    @property
    def n_ctx(self) -> int:
        return CONTEXT

    def count_tokens(self, text: str) -> int:
        # No tokenizer here; three characters a token overestimates, which is the
        # safe side for fitting a request.
        return len(text) // 3 + 1

    def generate(self, messages: Sequence[ChatMessage], *, max_tokens: int = 512,
                 temperature: float = 0.7, top_p: float = 0.95, stop: Sequence[str] = (),
                 deadline: float | None = None,
                 on_token: Callable[[str], None] | None = None) -> GenerationResult:
        started = time.monotonic()
        try:
            response = call("POST", MESSAGES_URL, policy=self._policy(), capability=CAPABILITY,
                            scope=SCOPE, hosts=(HOST,), audit=self._audit, actor=self._actor,
                            key=("x-api-key", lambda: self._secrets.get(SECRET)),
                            headers={"anthropic-version": API_VERSION,
                                     "anthropic-beta": FALLBACK_BETA},
                            payload=request(messages, self._effort),
                            max_bytes=MAX_REPLY_BYTES, timeout_s=TIMEOUT_S)
        except SecretError:
            raise ModelUnavailable("No Claude API key has been added, or it could not be "
                                   "unsealed. Add it from the chat's model menu.") from None
        except NetError as exc:
            raise ModelUnavailable(str(exc)) from None
        try:
            data = json.loads(response.text())
        except ValueError:
            data = {}
        if not response.ok:
            detail = ""
            if isinstance(data.get("error"), dict):
                detail = str(data["error"].get("message") or "")[:300]
            said = _REFUSED.get(response.status) or _REFUSED[500 if response.status >= 500
                                                             else 400]
            raise ModelError(said.format(detail=detail or f"{response.status} "
                                                          f"{response.reason}"))
        text, ended = reply_of(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        read = int(usage.get("input_tokens") or 0)
        written = int(usage.get("output_tokens") or 0)
        self._spend.add(read, written)
        if on_token is not None and text:
            on_token(text)
        return GenerationResult(text=text, prompt_tokens=read, completion_tokens=written,
                                stop_reason=ended, duration_s=time.monotonic() - started)

    def close(self) -> None:
        pass


class CloudRouter:
    """The part of `ModelRouter` the chat's responder and the agents use, handing out
    Claude for every route: medium effort for an everyday answer, high otherwise."""

    def __init__(self, make: Callable[[str], ClaudeBackend], *, effort: str = "") -> None:
        self._make = make
        self._effort = effort

    def resolve(self, route: Route) -> Route:
        return route

    @contextmanager
    def acquire(self, route: Route) -> Iterator[ClaudeBackend]:
        effort = self._effort or ("medium" if route in (Route.CHAT, Route.FAST) else "high")
        yield self._make(effort)


class Claude:
    """Whether Claude can be used, connecting and forgetting its key, and a router to it."""

    def __init__(self, *, policy: Callable[[], Policy], secrets: SecretStore,
                 audit: AuditLog | None = None, spend: Spend | None = None) -> None:
        self._policy = policy
        self._secrets = secrets
        self._audit = audit
        self.spend = spend if spend is not None else Spend()

    def has_key(self) -> bool:
        try:
            return bool(self._secrets.get(SECRET))
        except SecretError:
            return False

    def ready(self) -> str:
        """Why Claude cannot be used now, or ""."""
        if not self.has_key():
            return "Add your Claude API key first."
        decision = self._policy().allows(CAPABILITY, SCOPE)
        if not decision:
            return ("Sending chats to Claude is not allowed now. Allow it again from the "
                    "chat's model menu, or in Settings → Permissions.")
        return ""

    def seal(self, key: str) -> str:
        """Keep \\a key, sealed: "" or why not. It is checked with `check` after."""
        key = key.strip()
        if not _KEY.match(key):
            return "That does not look like an Anthropic API key: they begin sk-ant-."
        try:
            self._secrets.put(SECRET, key)
        except (SecretError, OSError) as exc:
            return f"The key could not be sealed: {exc}"
        return ""

    def check(self) -> str:
        """Ask Anthropic whether the key may use Claude Opus 5.5: "" or why not. Costs
        nothing: it reads the model's description, and writes nothing."""
        try:
            response = call("GET", MODEL_URL, policy=self._policy(), capability=CAPABILITY,
                            scope=SCOPE, hosts=(HOST,), audit=self._audit, actor="person",
                            key=("x-api-key", lambda: self._secrets.get(SECRET)),
                            headers={"anthropic-version": API_VERSION}, timeout_s=30.0)
        except SecretError:
            return "The key could not be unsealed."
        except NetError as exc:
            return str(exc)
        if response.ok:
            return ""
        return _REFUSED.get(response.status, f"Anthropic answered {response.status} "
                                             f"{response.reason}.").format(detail="")

    def forget(self) -> None:
        try:
            self._secrets.delete(SECRET)
        except (SecretError, OSError, KeyError):
            pass

    def backend(self, effort: str = "high", actor: str = "assistant") -> ClaudeBackend:
        return ClaudeBackend(policy=self._policy, secrets=self._secrets, audit=self._audit,
                             effort=effort, spend=self.spend, actor=actor)

    def router(self, *, effort: str = "", actor: str = "assistant") -> CloudRouter:
        return CloudRouter(lambda chosen: self.backend(chosen, actor), effort=effort)
