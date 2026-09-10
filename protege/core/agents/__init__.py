"""Agents: a model, a set of tools it is permitted to use, and a loop.

The interesting decisions are not here. What an agent can do is a permission
question answered in `core.permissions`; how well it does it is a hardware
question answered by which model fits the card. This package is the wiring
between them, plus the trace everything downstream reads.
"""

from .loop import Agent, AgentSpec, Outcome
from .protocol import Call, parse_calls, render_tools
from .trace import Event, Kind, Trace

__all__ = [
    "Agent", "AgentSpec", "Outcome",
    "Call", "parse_calls", "render_tools",
    "Event", "Kind", "Trace",
]
