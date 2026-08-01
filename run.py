#!/usr/bin/env python3
"""Protege entry point.

Order of operations here is deliberate and should not be rearranged:

1. Install the network guard **first**, before anything else is imported. Once
   a module holds a reference to the real `socket.connect`, patching afterwards
   cannot reach it.
2. Resolve and bootstrap the vault.
3. Only then import and start the UI, which is what pulls in the model backend.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Step 1. Nothing above this line imports anything that could capture an
# unpatched socket reference.
from protege.security import netguard

netguard.install()

# Step 1b. Declare DPI awareness before Tk exists. On a scaled display (this
# machine runs 125%) an unaware process is rendered small and bitmap-stretched
# by Windows, which resamples every glyph and makes crisp fonts look soft.
# It must happen before the first Tk call, hence here rather than in the UI.
from protege.ui import theme as _theme  # noqa: E402

_theme.enable_dpi_awareness()

from protege import __version__, store  # noqa: E402  (must follow netguard.install)
from protege.schemas import SchemaError  # noqa: E402
from protege.security.paths import capabilities, real  # noqa: E402

DEFAULT_VAULT_ENV = "PROTEGE_VAULT"


def _default_vault() -> Path | None:
    env = os.environ.get(DEFAULT_VAULT_ENV)
    if env:
        return Path(env)
    return None


def _resolve_vault(explicit: str | None) -> Path:
    candidate = Path(explicit) if explicit else _default_vault()
    if candidate is None:
        raise SystemExit(
            "No vault specified.\n"
            "Pass --vault PATH, or set the PROTEGE_VAULT environment variable to the "
            "directory holding your Obsidian vault."
        )
    return candidate.expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="protege", description=__doc__)
    parser.add_argument("--vault", help="path to the Obsidian vault directory")
    parser.add_argument(
        "--check",
        action="store_true",
        help="bootstrap and validate the vault configuration, then exit without starting the UI",
    )
    parser.add_argument("--version", action="version", version=f"Protege {__version__}")
    args = parser.parse_args(argv)

    vault = _resolve_vault(args.vault)

    try:
        manifest, settings, personality = store.bootstrap_vault(vault)
    except (SchemaError, store.StoreError) as exc:
        print(f"Configuration error:\n\n{exc}", file=sys.stderr)
        return 2

    if args.check:
        tier = capabilities(manifest.trust_tier)
        print(f"vault:            {real(vault)}")
        print(f"unlocked topics:  {len(manifest.unlocked_topics)}")
        print(f"trust tier:       {tier.label}")
        print(f"lock layers:      {'ALL ON' if not settings.lock_layers.any_disabled else 'DISABLED: ' + ', '.join(settings.lock_layers.disabled_names)}")
        print(f"personality:      {len(personality.traits)} traits, profile {personality.active_profile!r}")
        print(f"network guard:    {'installed' if netguard.is_installed() else 'NOT INSTALLED'}")
        return 0

    # Step 3. The UI import lives here, after the guard is installed and the
    # configuration is known good.
    from protege.ui.app import run_app

    return run_app(vault, manifest, settings, personality)


if __name__ == "__main__":
    raise SystemExit(main())
