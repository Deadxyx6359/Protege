"""A conversation, handed to the software team to carry out.

The chat answers; it changes nothing. When an answer is something to do (code
to write into a project, a driver to add, a build to fix), "Do it" under it
gives the work to the software team, in a folder, with the conversation as the
task: what the person asked last, the answer to carry out, and what they said
before, briefly. The team asks before each change, as it does from the Agents
page, and what it did comes back into the conversation.
"""

from __future__ import annotations

import re
from typing import Iterable

#: The task the team is given, at most: the Agents page takes 4,000 characters.
MAX_TASK_CHARS = 3_900
#: Of that, the answer to carry out.
MAX_ANSWER_CHARS = 2_600
#: And what the person said before the last message, all told.
MAX_EARLIER_CHARS = 500

#: Notes Akira adds under an answer, which are about the answer and not part of it.
_NOTES = re.compile(r"\n\n(?:Check before using|Checked:|Check the pins:|\*\*Not checked:\*\*|"
                    r"Note: nothing could be looked up)[\s\S]*\Z")


def worth_doing(text: str) -> bool:
    """Whether an answer reads as work to carry out: code in it, or files named."""
    return "```" in text or bool(re.search(
        r"\b[\w-]+\.(?:c|h|cpp|hpp|py|js|ts|qml|cmake|ioc|json|txt)\b|CMakeLists\.txt", text))


def task_from(messages: Iterable, folder: str) -> str:
    """The team's task, from a conversation's messages (each with `role`, `text`,
    `error`): "" when there is no answer to carry out."""
    said = [m for m in messages if m.role in ("user", "assistant") and not m.error
            and m.text.strip()]
    if len(said) < 2 or said[-1].role != "assistant":
        return ""
    answer = _NOTES.sub("", said[-1].text).strip()
    asked = next((m.text.strip() for m in reversed(said[:-1]) if m.role == "user"), "")
    if not answer or not asked:
        return ""
    earlier = [m.text.strip() for m in said[:-2] if m.role == "user"]
    if len(answer) > MAX_ANSWER_CHARS:
        answer = answer[:MAX_ANSWER_CHARS].rsplit("\n", 1)[0] + "\n[… the rest of the answer]"
    parts = [f"Carry out what this chat settled on, in {folder}. Change the files there that "
             "it needs; build or test what you changed when you can; say what you did.",
             f"What the person asked:\n{asked[:600]}",
             f"The answer to carry out:\n{answer}"]
    if earlier:
        brief = " / ".join(earlier)
        if len(brief) > MAX_EARLIER_CHARS:
            brief = brief[:MAX_EARLIER_CHARS].rsplit(" ", 1)[0] + " …"
        parts.append(f"Earlier in the chat they said: {brief}")
    return "\n\n".join(parts)[:MAX_TASK_CHARS]


def result_said(ok: bool, answer: str, stopped: str) -> str:
    """What the chat says when the team is done."""
    answer = answer.strip()
    if stopped == "cancelled":
        return "The software team was stopped." + (f" What it had done so far:\n\n{answer}"
                                                   if answer else "")
    if ok:
        return f"**The software team finished.**\n\n{answer}" if answer else \
            "The software team finished, and said nothing about it."
    return ("**The software team could not finish.**\n\n" + answer) if answer else \
        "The software team could not finish."
