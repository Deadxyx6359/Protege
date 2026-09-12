"""Subprocess entry point for running project code and tests.

Run as `python -I _guarded.py --script <file.py> [args...]` or
`python -I _guarded.py --module <name> [args...]`. Installs the network guard
before any project code is compiled or executed — the same order the skill
runner uses — so code under test cannot capture an unpatched socket reference
the way it could if the guard went up afterwards.

Kept as a file rather than a `-c` string so the bootstrap is readable,
reviewable, and covered by `verify_offline.py` like everything else.
"""

from __future__ import annotations

import os
import runpy
import sys

_USAGE = "usage: _guarded.py --script <file.py> [args...] | --module <name> [args...]"


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in ("--script", "--module"):
        print(_USAGE, file=sys.stderr)
        return 2

    # akira/core/tools/builtin/_guarded.py -> the repository root, five up.
    root = os.path.abspath(__file__)
    for _ in range(5):
        root = os.path.dirname(root)
    if root not in sys.path:
        sys.path.insert(0, root)

    from akira.security import netguard

    netguard.install()

    # Isolated mode leaves the project's own folder off the path; without it
    # the project could not import its own modules.
    workdir = os.getcwd()
    if workdir not in sys.path:
        sys.path.insert(0, workdir)

    mode, target, rest = argv[1], argv[2], argv[3:]
    try:
        if mode == "--script":
            folder = os.path.dirname(os.path.abspath(target))
            if folder not in sys.path:
                sys.path.insert(0, folder)
            sys.argv = [target, *rest]
            runpy.run_path(target, run_name="__main__")
        else:
            sys.argv = [target, *rest]
            runpy.run_module(target, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    except BaseException as exc:  # noqa: BLE001 - report, never propagate a traceback object
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
