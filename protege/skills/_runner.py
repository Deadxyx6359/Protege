"""Subprocess entry point for skill execution.

Run as `python -I _runner.py <skill.py> [args...]`. Installs the network guard
before the skill's code is compiled or executed, so a skill cannot capture an
unpatched socket reference the way it could if the guard went up afterwards.

Kept as a separate file rather than a `-c` string so that the bootstrap is
readable, reviewable, and covered by `verify_offline.py` like everything else.

Arguments after the skill path are handed to the skill as its own `sys.argv`.
Without that, every skill in the shipped library -- all of which are documented
as `something.py <file>` -- could only ever be run against itself, which made
the entire feature ornamental: a code reviewer that reviews the code reviewer.
"""

from __future__ import annotations

import os
import runpy
import sys


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _runner.py <skill.py> [args...]", file=sys.stderr)
        return 2

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from protege.security import netguard

    netguard.install()

    skill_path = argv[1]
    if not os.path.isfile(skill_path):
        print(f"skill file not found: {skill_path}", file=sys.stderr)
        return 2

    # The skill sees itself as argv[0], as it would if run directly. Set before
    # `run_path` so that a skill parsing arguments at import time also sees them.
    sys.argv = [skill_path, *argv[2:]]

    # `run_name="__main__"` so a skill's `if __name__ == "__main__":` block runs,
    # which is how skills are expected to be written.
    try:
        runpy.run_path(skill_path, run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    except BaseException as exc:  # noqa: BLE001 - report, never propagate a traceback object
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
