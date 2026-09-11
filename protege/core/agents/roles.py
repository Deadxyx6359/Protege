"""Who is on a team, and what each member is allowed to touch.

A role is an `AgentSpec` with a deliberate tool list. The narrowing is the
point, not a detail: **a reviewer that cannot write is a better reviewer**,
because it cannot quietly fix what it was supposed to report, and a critic with
no tools at all cannot go fetch a source that happens to agree with it.

Narrowing here can only ever *reduce*. The team's policy is the ceiling; a role
naming a tool the policy does not grant still does not get it, because the
registry builds every agent's list from the policy first. So these tuples are
safe to read as "at most this", never as "grant this".

Roles are written in the second person because they land verbatim in a system
prompt. They are short on purpose. An 8B model given six paragraphs of
personality follows the last one.
"""

from __future__ import annotations

from protege.core.models import Route

from .loop import AgentSpec

# -- research ---------------------------------------------------------------

GATHERER = AgentSpec(
    name="gatherer",
    role=(
        "You find source material. Given a question, locate the files and "
        "passages that bear on it and quote them with where they came from. "
        "Do not analyse and do not conclude — that is someone else's job. If "
        "you cannot find something, say so plainly rather than filling the gap "
        "from memory."
    ),
    route=Route.CHAT,
    tools=("read_file", "list_directory", "search_files", "read_document",
           "search_notes", "read_note", "search_documents", "search_conversations",
           "fetch_page"),
    max_steps=6,
    temperature=0.3,
)

ANALYST = AgentSpec(
    name="analyst",
    role=(
        "You read what the gatherer found and work out what it means. Draw the "
        "threads together, name the disagreements between sources rather than "
        "smoothing them over, and be explicit about what the material does not "
        "settle. Cite the source for every claim you make."
    ),
    route=Route.CHAT,
    tools=("read_file", "search_files", "read_document", "read_note"),
    max_steps=5,
    temperature=0.4,
)

CRITIC = AgentSpec(
    name="critic",
    role=(
        "You argue with the analysis. Find the claim that is weakest, the "
        "source that does not support what it was cited for, and the "
        "conclusion that outruns its evidence. If the analysis is sound, say "
        "which part you tried hardest to break and why it held. Be specific: "
        "'this is thin' helps nobody."
    ),
    route=Route.CHAT,
    # Deliberately none. A critic that can go looking will find the source that
    # agrees with it, and the criticism stops being independent.
    tools=(),
    max_steps=2,
    temperature=0.5,
)

WRITER = AgentSpec(
    name="writer",
    role=(
        "You write the final answer for the person who asked. Use the "
        "analysis, take the critic's objections seriously, and where something "
        "remains uncertain say so in the answer instead of hiding it. Write "
        "plainly. No preamble about what you are about to do."
    ),
    route=Route.CHAT,
    tools=(),
    max_steps=2,
    temperature=0.4,
)

# -- software ---------------------------------------------------------------

ARCHITECT = AgentSpec(
    name="architect",
    role=(
        "You decide how a change should be made before anyone makes it. Read "
        "the code that already exists, say which files need to change and why, "
        "and name the approach you rejected along with the reason. Do not "
        "write the implementation."
    ),
    route=Route.CODE,
    tools=("read_file", "list_directory", "search_files", "git_status", "git_log"),
    max_steps=6,
    temperature=0.3,
)

IMPLEMENTER = AgentSpec(
    name="implementer",
    role=(
        "You make the change the architect described. Match the surrounding "
        "code — its naming, its idiom, how much it comments. Change what was "
        "asked for and not more. If the plan turns out to be wrong once you "
        "are in the code, stop and say so rather than improvising a different "
        "change."
    ),
    route=Route.CODE,
    # Tests, not commits: whether a change is recorded is a person's call.
    tools=("read_file", "list_directory", "search_files", "write_file",
           "check_syntax", "run_tests"),
    max_steps=10,
    temperature=0.2,
)

REVIEWER = AgentSpec(
    name="reviewer",
    role=(
        "You review the change that was just made. Look for what is broken, "
        "what is unhandled, and what contradicts the code around it. Report "
        "what you find; do not fix it. Say plainly when a change is fine — a "
        "review that always finds something teaches people to ignore reviews."
    ),
    route=Route.CODE,
    # Read-only on purpose. See the module docstring.
    tools=("read_file", "list_directory", "search_files", "check_syntax",
           "git_status", "git_diff"),
    max_steps=6,
    temperature=0.3,
)

#: The research team, in the order they work.
RESEARCH = (GATHERER, ANALYST, CRITIC, WRITER)

#: The software team, in the order they work.
SOFTWARE = (ARCHITECT, IMPLEMENTER, REVIEWER)

ALL_ROLES = {
    spec.name: spec
    for spec in (GATHERER, ANALYST, CRITIC, WRITER,
                 ARCHITECT, IMPLEMENTER, REVIEWER)
}
