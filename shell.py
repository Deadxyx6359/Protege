#!/usr/bin/env python3
"""Launch the new Qt interface.

    python shell.py

Sits beside `run.py`, which still launches the Tkinter application. Two entry
points is the deliberate state of the rebuild: the old one keeps working until
the new one can replace it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from protege.ui.shell import run_shell  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(run_shell())
