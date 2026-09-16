"""Putting a finished file in place, on Windows as it actually behaves.

Every store in Akira writes a whole file beside its target and moves it into
place with `os.replace`, so a crash never leaves half a file. On Windows that
move fails with "Access is denied" if another program has the target open at
that moment, and one often does: Defender and the search indexer open a file
for a moment just after it is written. So the move is tried again, a few times
over about a second. Anything longer is a real refusal, and is raised.
"""

from __future__ import annotations

import os
import time

#: How many times a move is tried in all.
ATTEMPTS = 6

#: The first pause; each after is one step longer. Six tries wait about a second.
PAUSE_S = 0.05


def replace(source: str | os.PathLike, target: str | os.PathLike) -> None:
    """`os.replace`, tried again briefly while another program has \a target open."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == ATTEMPTS:
                raise
            time.sleep(PAUSE_S * attempt)
