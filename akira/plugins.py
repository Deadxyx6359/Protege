"""Plugin interface.

Plugins live in `vault/.protege/plugins/` as single Python files. A plugin
declares a `PROTEGE_PLUGIN` object satisfying the `Plugin` protocol, and
receives a `PluginContext` on activation.

**The point of this module is that plugins inherit gating by construction.**
`PluginContext.check` is the same `OutputGate` the chat pipeline and the memory
writer use -- a plugin that wants to show the user model output, or write to the
vault, goes through the identical five layers. There is no separate, weaker path
for extensions, and no way for a plugin to obtain an ungated backend: the
context hands out `generate_checked`, never a raw `ModelBackend`.

**Loading a plugin runs arbitrary code, and this module does not pretend
otherwise.** `verify_offline.py` scans Akira's own import graph; it cannot
vouch for a file dropped into the plugin directory afterwards. So plugins are
discovered but never auto-loaded: each must be listed in `enabled` *and* match
the SHA-256 recorded when it was approved. That is the same digest-binding rule
skills use, for the same reason -- approval means "this exact content", not
"this filename forever".
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

from .lock.pipeline import GateResult, OutputGate
from .models import ChatMessage, ModelManager, Role
from .schemas import Manifest, Settings
from .store import protege_dir

PLUGIN_ATTR = "PROTEGE_PLUGIN"
PLUGIN_DIR_NAME = "plugins"


class PluginError(RuntimeError):
    """A plugin could not be loaded or activated."""


def plugin_dir(vault: Path) -> Path:
    return protege_dir(vault) / PLUGIN_DIR_NAME


@runtime_checkable
class Plugin(Protocol):
    """What a plugin file must expose as `PROTEGE_PLUGIN`."""

    name: str
    version: str
    description: str

    def activate(self, context: "PluginContext") -> None:
        """Called once after loading. Register callbacks here; do not block."""


@dataclass
class PluginContext:
    """The only surface a plugin gets.

    Deliberately does not expose a `ModelBackend`. A plugin that could call
    `generate` directly would be a fifth way to produce model output, and the
    first thing anyone would do with it is skip the gate -- not maliciously, just
    because the ungated call is shorter. `generate_checked` is the shorter call
    here.
    """

    vault: Path
    manifest: Manifest
    settings: Settings
    gate: OutputGate
    _manager: ModelManager
    _menu_items: list[tuple[str, Callable[[], None]]] = field(default_factory=list)

    @property
    def unlocked_topics(self) -> tuple[str, ...]:
        return self.manifest.unlocked_topics

    def check(self, user_prompt: str, text: str) -> GateResult:
        """Run text through Layers 4 and 5. Use before showing or storing anything."""
        return self.gate.check(user_prompt, text, allow_decline_shortcut=False)

    def generate_checked(self, messages: Sequence[ChatMessage], *, max_tokens: int = 512) -> GateResult | str:
        """Generate with MAIN and gate the result.

        Returns the text on success, or the blocking `GateResult` on failure.
        A plugin that ignores the return type and prints it either way shows the
        user a GateResult repr -- ugly, but not a leak, which is the correct
        direction for a mistake to fail in.
        """
        with self._manager.acquire(Role.MAIN) as backend:
            result = backend.generate(
                messages,
                max_tokens=max_tokens,
                temperature=self.settings.models.temperature,
                top_p=self.settings.models.top_p,
            )
        prompt = next((m.content for m in reversed(messages) if m.role == "user"), "")
        verdict = self.check(prompt, result.text)
        return result.text if verdict.allowed else verdict

    def add_menu_item(self, label: str, command: Callable[[], None]) -> None:
        self._menu_items.append((label, command))

    @property
    def menu_items(self) -> tuple[tuple[str, Callable[[], None]], ...]:
        return tuple(self._menu_items)


@dataclass(frozen=True)
class DiscoveredPlugin:
    path: Path
    sha256: str

    @property
    def name(self) -> str:
        return self.path.stem


def digest_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def discover(vault: Path) -> list[DiscoveredPlugin]:
    """List plugin files without importing any of them."""
    directory = plugin_dir(vault)
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            found.append(DiscoveredPlugin(path=path, sha256=digest_of(path)))
        except OSError:
            continue
    return found


def load(
    vault: Path,
    manifest: Manifest,
    settings: Settings,
    gate: OutputGate,
    manager: ModelManager,
    *,
    enabled: dict[str, str],
) -> tuple[list[tuple[Plugin, PluginContext]], list[str]]:
    """Import and activate approved plugins.

    `enabled` maps plugin name to the SHA-256 approved for it. A plugin whose
    file no longer matches is skipped with an error rather than loaded -- see
    the module docstring.

    Returns (loaded, errors). Never raises: a broken plugin must not prevent
    Akira from starting.
    """
    loaded: list[tuple[Plugin, PluginContext]] = []
    errors: list[str] = []

    for candidate in discover(vault):
        approved = enabled.get(candidate.name)
        if approved is None:
            continue
        if approved != candidate.sha256:
            errors.append(
                f"{candidate.name}: file has changed since it was approved "
                f"({approved[:12]}... -> {candidate.sha256[:12]}...); not loaded"
            )
            continue

        try:
            module = _import_file(candidate.path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate.name}: import failed: {type(exc).__name__}: {exc}")
            continue

        plugin: Any = getattr(module, PLUGIN_ATTR, None)
        if plugin is None:
            errors.append(f"{candidate.name}: no {PLUGIN_ATTR} attribute")
            continue
        if not all(hasattr(plugin, attr) for attr in ("name", "version", "activate")):
            errors.append(f"{candidate.name}: {PLUGIN_ATTR} does not satisfy the Plugin protocol")
            continue

        context = PluginContext(
            vault=Path(vault), manifest=manifest, settings=settings, gate=gate, _manager=manager
        )
        try:
            plugin.activate(context)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{candidate.name}: activate() raised {type(exc).__name__}: {exc}")
            continue
        loaded.append((plugin, context))

    return loaded, errors


def _import_file(path: Path):
    module_name = f"protege_plugin_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


EXAMPLE_PLUGIN = '''\
"""Example Akira plugin.

Copy to vault/.protege/plugins/, then approve it in Settings. Approval is bound
to this file's exact contents; editing it revokes approval.
"""

from akira.models import ChatMessage


class WordCount:
    name = "word-count"
    version = "1.0"
    description = "Adds a menu item that counts words in the last response."

    def activate(self, context):
        self.context = context
        context.add_menu_item("Count words", self.run)

    def run(self):
        # Anything shown to the user goes through the gate. `generate_checked`
        # does that for you and returns a GateResult instead of text if a layer
        # objects.
        result = self.context.generate_checked(
            [ChatMessage(role="user", content="Say hello in exactly five words.")],
            max_tokens=32,
        )
        if isinstance(result, str):
            print(len(result.split()))
        else:
            print(f"blocked by the {result.layer} layer: {result.reason}")


PROTEGE_PLUGIN = WordCount()
'''
