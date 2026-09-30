"""The permissions most people want first, offered on one screen.

Setting Akira up took some fifteen separate grants, found one at a time on the
permission screen: weather alone needed two. This is the handful that makes the
everyday things work, each in plain words, each chosen by the person, and each
no wider than it says. Nothing here is granted without being picked, a folder
is the one the person chooses, and every grant is recorded as any other is.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Policy


@dataclass(frozen=True)
class Choice:
    id: str
    title: str
    detail: str
    grants: tuple[tuple[str, tuple[str, ...]], ...]
    """What it grants: each capability and its scopes. A folder choice's scopes
    are the folder the person picks."""
    folder: bool = False
    """The person picks a folder, which becomes each grant's scope."""
    on: bool = True
    """Ticked to begin with. A folder choice is not until a folder is picked."""


STARTER: tuple[Choice, ...] = (
    Choice("web", "Look things up on the web",
           "Search with DuckDuckGo and read Wikipedia. Another site is asked about when it "
           "comes up.",
           (("web.search", ()), ("net.http", ("en.wikipedia.org",)))),
    Choice("weather", "The weather where you are",
           "Your town, which you set in Settings, and the forecast from Open-Meteo.",
           (("location.read", ()), ("net.http", ("open-meteo.com",)))),
    Choice("notices", "Notices",
           "For reminders you set in the chat, and for folders or pages you watch.",
           (("notify.send", ()),)),
    Choice("calendar", "Your calendar",
           "Let the chat and agents read the calendar kept in Akira, on this computer, and "
           "ask to add to it. Each change is shown to you first.",
           (("planner.read", ()), ("planner.write", ()))),
    Choice("notes", "Your notes",
           "Read the notes in one folder, such as an Obsidian vault.",
           (("vault.read", ()),), folder=True, on=False),
    Choice("documents", "Your documents",
           "Read files and documents in one folder.",
           (("files.read", ()), ("docs.read", ())), folder=True, on=False),
)

BY_ID = {choice.id: choice for choice in STARTER}


def held(policy: Policy, choice: Choice) -> bool:
    """Whether everything \a choice grants is granted already. Never for a folder
    choice, which can always add another folder.

    Shown ticked whether it was or not, "Look things up on the web" looked on
    with web search granted and Wikipedia not, and the person took it to be.
    """
    if choice.folder:
        return False
    for capability, scopes in choice.grants:
        grant = policy.granted(capability)
        if grant is None or any(scope not in grant.scopes for scope in scopes):
            return False
    return True


def planned(choices: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
    """What \a choices would grant: `{id, folder}` each, as the person picked them.

    Raises `ValueError` for an unknown choice, or a folder choice with no folder.
    """
    out: list[tuple[str, tuple[str, ...]]] = []
    for picked in choices:
        choice = BY_ID.get(str(picked.get("id", "")))
        if choice is None:
            raise ValueError(f"There is no setup choice {picked.get('id')!r}.")
        folder = str(picked.get("folder") or "").strip()
        if choice.folder and not folder:
            raise ValueError(f"Pick a folder for “{choice.title}”.")
        for capability, scopes in choice.grants:
            out.append((capability, (folder,) if choice.folder else scopes))
    return out


def apply(policy: Policy, plan: list[tuple[str, tuple[str, ...]]]) -> list[str]:
    """Grant \a plan in \a policy, adding to what is held already. The capabilities changed."""
    changed: list[str] = []
    for capability, scopes in plan:
        held = policy.granted(capability)
        if held is None:
            policy.grant(capability, scopes)
        else:
            wanted = tuple(s for s in scopes if s not in held.scopes)
            if not wanted:
                continue
            policy.grant(capability, (*held.scopes, *wanted), expires=held.expires,
                         note=held.note, kept=held.kept)
        changed.append(capability)
    return changed
