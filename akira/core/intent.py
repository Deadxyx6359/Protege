"""What a message is asking for: talk, code, or research — and so which model answers.

One chat takes everything. Each message is sorted before it is answered:

  * **everyday** — conversation, advice, writing, sums: the chat model.
  * **code** — reading, writing or fixing code: the coding model.
  * **research** — something to be looked up, in the person's files and notes or
    on the sites they allow: a gatherer reads first, and the answer is written
    from what it read, on the strongest model there is (`Route.DEEP`, which is
    the chat model unless a larger or cloud one is set up).

The sorting is a scored heuristic, not a model call: a classifier would cost a
round trip, and often a model swap, before every answer. It is wrong sometimes,
so what it chose is shown, and the person can pin a kind for the chat.
A short follow-up keeps the kind of the turn before it: "and in Rust?" after
code is still code, "what about Webb?" after research is still research.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from akira.core.conversation import _CODE_SIGNALS
from akira.core.models import Route


class Intent(str, Enum):
    EVERYDAY = "everyday"
    CODE = "code"
    RESEARCH = "research"


#: What the person may pin a chat to. `auto` sorts each message.
MODES = ("auto", "everyday", "code", "research")

LABELS = {Intent.EVERYDAY: "Everyday", Intent.CODE: "Code", Intent.RESEARCH: "Research"}

#: The model each kind is answered on.
ROUTES = {Intent.EVERYDAY: Route.CHAT, Intent.CODE: Route.CODE, Intent.RESEARCH: Route.DEEP}

#: How long a message may be and still count as a follow-up to the last one.
FOLLOW_UP_CHARS = 160


@dataclass(frozen=True)
class Choice:
    intent: Intent
    route: Route
    why: str
    """A few words on why, for the interface and the tests."""

    @property
    def label(self) -> str:
        return LABELS[self.intent]


#: Code that is not named: a fenced block, a file, an error trace.
_CODE_SHAPES = re.compile(
    r"```|\b[\w-]+\.(?:py|js|ts|tsx|jsx|qml|java|cs|cpp|c|h|go|rs|rb|php|sh|ps1|sql|"
    r"html|css|json|ya?ml|toml|ipynb)\b|Traceback \(most recent call last\)|"
    r"\b\w+(?:Error|Exception):|\bnpm\b|\bpip install\b|\bgit\s+(?:commit|push|pull|merge|"
    r"rebase|checkout|diff|log)\b", re.IGNORECASE)

#: Asking for something to be looked up, or for what is true now.
_LOOK_UP = re.compile(
    r"\b(?:research|look\s+(?:it|this|that|them)?\s*up|find\s+out|search\s+(?:the\s+web|"
    r"online|for)|google\s+it|on\s+(?:the\s+)?(?:web|internet|wikipedia)|online|"
    r"check\s+(?:online|the\s+web|wikipedia|the\s+news)|fact[- ]?check|investigate|"
    r"latest|news)\b",
    re.IGNORECASE)

#: Words about now, which ask for the world as it is today unless the question
#: is about the person's own things: "what's on my screen right now?" is not a
#: search.
_NOW = re.compile(
    r"\b(?:currently|nowadays|these\s+days|recent(?:ly)?|this\s+(?:week|month|year)|"
    r"today'?s|up[- ]to[- ]date|as\s+of\s+(?:now|today)|right\s+now)\b", re.IGNORECASE)
_MINE = re.compile(r"\b(?:my|mine|me|I)\b")

#: Working with dates, not asking about them: "how many days between March 3
#: and April 17, 2026?" names this year and needs no search.
_DATE_SUM = re.compile(
    r"\bhow\s+many\s+(?:days|weeks|months|years|hours|minutes)\b|"
    r"\b(?:days?|weeks?)\s+(?:between|until|till|since|from)\b|"
    r"\bwhat\s+day\s+of\s+the\s+week\b|\b(?:add|plus|minus)\s+\d+\s+days\b",
    re.IGNORECASE)

#: An amount given in the question: a word problem, not a price to look up.
_GIVEN_AMOUNT = re.compile(r"[£$€]\s?\d|\b\d+(?:\.\d+)?\s?(?:dollars|pounds|euros|cents|"
                           r"pence)\b", re.IGNORECASE)

#: Facts that change or that a local model will not have: what something costs,
#: when a place is open, the weather somewhere, who holds a post now, what came out.
_CURRENT_FACTS = re.compile(
    r"\b(?:price\s+of|how\s+much\s+(?:does|do|is|are)\s+\w[\w\s]{0,40}\s+cost|"
    r"opening\s+(?:hours|times)|open\s+(?:now|today|on\s+sundays?)|"
    r"weather\s+(?:in|at|for)\s+\w+|forecast\s+(?:in|for)|"
    r"who\s+is\s+the\s+(?:current|new)|who\s+(?:won|is\s+winning)|"
    r"release\s+date|when\s+(?:does|did|will)\s+[\w\s]{1,40}\s+(?:come\s+out|release|launch)|"
    r"exchange\s+rate|stock\s+price|population\s+of)\b", re.IGNORECASE)

#: Asking for what sources say, or for them.
_SOURCES = re.compile(
    r"\b(?:sources?|citations?|cite|references?|according\s+to|evidence|studies|"
    r"what\s+(?:do|does)\s+(?:the|my)\s+(?:paper|papers|article|articles|study|report|"
    r"documents?|files?|notes?|spreadsheet|minutes)\s+say)\b", re.IGNORECASE)

#: The person's own material, beyond what chat looks through on its own.
_THEIR_FILES = re.compile(
    r"\b(?:in|from|across|through)\s+(?:my|our|the)\s+(?:files?|documents?|folders?|"
    r"spreadsheets?|pdfs?|reports?|project)\b|\.(?:docx|xlsx|pptx|pdf|csv)\b",
    re.IGNORECASE)

#: Weighing things against each other, which wants more than one source.
_COMPARE = re.compile(r"\b(?:compare|comparison|versus|vs\.?|pros\s+and\s+cons)\b",
                      re.IGNORECASE)

#: A year after what a local model can know.
_RECENT_YEAR = re.compile(r"\b20(?:2[5-9]|[3-9]\d)\b")

#: A question, rather than a statement or a thank-you.
_QUESTION = re.compile(r"\?|^\s*(?:and\s+|also\s+|so\s+)?(?:what|who|when|where|why|how|which|"
                       r"is|are|was|were|does|do|did|can|could|should|will|would)\b",
                       re.IGNORECASE)

#: A message that points back at the last answer: "and in Rust?", "now make it
#: ignore case", "what about Webb?". "What should I cook tonight?" after code
#: does not, and is not code.
_REFERS_BACK = re.compile(
    r"^\s*(?:and|also|now|then|so|but|or|instead|what\s+about|how\s+about|make|change|add|"
    r"remove|use|try|again|same|why|explain)\b|\b(?:it|its|that|this|these|those|them|"
    r"instead|again|above|previous|last\s+one)\b", re.IGNORECASE)

#: Thanks and yeses: never a new search.
_ACKNOWLEDGED = re.compile(r"^\s*(?:thanks?|thank\s+you|ta|ok(?:ay)?|great|cool|nice|perfect|"
                           r"got\s+it|cheers|brilliant|lovely|yes|no|sure)\b[\s!.]*$",
                           re.IGNORECASE)


def choose(text: str, *, previous: Intent | None = None, mode: str = "auto") -> Choice:
    """The kind of \a text, and the route its answer is written on.

    \a previous is the kind of the turn before, for follow-ups. \a mode, when
    not `auto`, is the person's choice and is taken as it is.
    """
    if mode in MODES and mode != "auto":
        intent = Intent(mode)
        return Choice(intent, ROUTES[intent], "chosen")

    if _ACKNOWLEDGED.match(text):
        return _choice(Intent.EVERYDAY, "conversation")
    question = bool(_QUESTION.search(text))
    sums = bool(_DATE_SUM.search(text))
    # "Who won the 2026 World Cup?" is past what a local model knows; days
    # counted between two dates in 2026 are not.
    recent = bool(_RECENT_YEAR.search(text) and not sums) * (2 if question else 1)
    code = bool(_CODE_SIGNALS.search(text) or _CODE_SHAPES.search(text))
    # "The price of items" in a request for code is about the code, and "how
    # much does the ball cost?" after "a bat and a ball cost $1.10" is a puzzle.
    looks_up = (bool(_LOOK_UP.search(text))
                or (bool(_NOW.search(text)) and not _MINE.search(text) and not sums)
                or (bool(_CURRENT_FACTS.search(text)) and not code
                    and not _GIVEN_AMOUNT.search(text)))
    research = (2 * looks_up + 2 * bool(_SOURCES.search(text))
                + 2 * bool(_THEIR_FILES.search(text)) + bool(_COMPARE.search(text)) + recent)

    # "Look up the latest version of Python": what is true now outweighs the
    # word that names code; "compare lists and tuples in Python" does not.
    if looks_up and research >= 2:
        return _choice(Intent.RESEARCH, "asks for something to be looked up")
    if code:
        return _choice(Intent.CODE, "about code")
    if research >= 2:
        return _choice(Intent.RESEARCH, "asks about something recent" if research == recent
                       else "asks what sources say")
    if (previous is not None and len(text.strip()) <= FOLLOW_UP_CHARS
            and _REFERS_BACK.search(text)
            and (previous is not Intent.RESEARCH or question)):
        return _choice(previous, "follows the last answer")
    return _choice(Intent.EVERYDAY, "conversation")


def _choice(intent: Intent, why: str) -> Choice:
    return Choice(intent, ROUTES[intent], why)
