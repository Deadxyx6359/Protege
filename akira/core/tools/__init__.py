"""Tools: what an agent can actually do, and the gate it goes through.

A tool declares the capabilities it needs. The registry uses that to decide
whether an agent is even shown the tool, and to check the specific scope before
running it. Nothing is offered that has not been granted.
"""

from .registry import ToolRegistry
from .schema import (
    Asking,
    Parameter,
    Requirement,
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
)


def default_registry() -> ToolRegistry:
    """A registry holding every built-in tool.

    Assembled explicitly rather than by import side effect: a tool that
    registers itself when its module is imported is a tool that appears in
    surprising places, including in tests that meant to exclude it.
    """
    from .builtin import MODULES

    registry = ToolRegistry()
    for module in MODULES:
        for tool in module.ALL:
            registry.register(tool)
    return registry


__all__ = [
    "ToolRegistry", "default_registry",
    "Tool", "Parameter", "Requirement", "ToolContext", "ToolError", "ToolResult", "Asking",
]
