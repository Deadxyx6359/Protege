"""The knowledge lock system.

Five layers, all active simultaneously, in the order a response passes through
them:

* **Layer 1 -- Manifest** (`..schemas.Manifest`, persisted by `..store`).
  Single source of truth for what is unlocked. Everything else consults it.
* **Layer 2 -- Directive** (`directive`). Instructs MAIN. Weakest layer; leaks.
* **Layer 3 -- Scoped retrieval** (`retrieval`). Locked-topic notes are
  invisible to search, memory notes included.
* **Layer 4 -- Tripwires** (`tripwires`). Deterministic pattern checks over
  MAIN's output. Fast, dumb, false-positive-prone, and the only layer with no
  model in it.
* **Layer 5 -- Auditor** (`auditor`). A second model reads the draft and returns
  a structured verdict.

`pipeline` runs all five and is the only supported entry point. It is exposed as
a library so that new components -- plugins, skills, memory writes -- inherit
gating by construction rather than by remembering to ask.

The governing rule, in every module here: **fail closed.** Any error, timeout,
ambiguity, or component failure blocks the response. There is no path through
this package where an exception results in text reaching the user.
"""

from .directive import DECLINE_PATTERN, DECLINE_TEMPLATE, Directive, build_directive, decline_for
from .pipeline import GateResult, OutputGate, PipelineResponder, is_pure_decline
from .retrieval import RetrievalResult, retrieve
from .tripwires import TripwireSet

__all__ = [
    "DECLINE_PATTERN",
    "DECLINE_TEMPLATE",
    "Directive",
    "GateResult",
    "OutputGate",
    "PipelineResponder",
    "RetrievalResult",
    "TripwireSet",
    "build_directive",
    "decline_for",
    "is_pure_decline",
    "retrieve",
]
