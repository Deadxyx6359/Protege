"""Local audit log of lock decisions.

Off by default. When enabled, appends one line per gate decision to
`vault/.protege/protege.log`.

**Metadata only, never content.** A log that recorded the blocked draft would be
an unencrypted plaintext copy of exactly the material the lock system exists to
withhold, sitting in the vault where retrieval could later find it. So this
records the shape of the decision -- timestamp, layer, topic, allowed or not,
how long it took -- and nothing that was said. That is enough to answer "why is
it blocking everything" and "is the auditor timing out", which is what a log is
for here.

No network handler, no rotation to a remote sink, no syslog. `logging` from the
stdlib is not used either: it configures global state, and a stray
`basicConfig` elsewhere in a future edit could quietly redirect this somewhere
unintended.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .schemas import utcnow_iso
from .store import protege_dir

LOG_NAME = "protege.log"
MAX_BYTES = 2_000_000


def log_path(vault: Path) -> Path:
    return protege_dir(vault) / LOG_NAME


@dataclass
class AuditLog:
    """Append-only decision log."""

    vault: Path
    enabled: bool = False

    def _write(self, line: str) -> None:
        if not self.enabled:
            return
        path = log_path(self.vault)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Truncate rather than rotate. A rotated log is a second copy to
            # think about, and this file holds nothing worth preserving across
            # two million bytes of history.
            if path.exists() and path.stat().st_size > MAX_BYTES:
                path.write_text(
                    f"{utcnow_iso()} log truncated at {MAX_BYTES} bytes\n", encoding="utf-8"
                )
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError:
            # Logging must never break a turn. A full disk or a locked file is
            # not a reason to withhold a response that already passed the gate.
            pass

    def gate(self, result, *, kind: str = "response") -> None:
        """Record one gate decision. Takes no text from the draft."""
        verdict = "allow" if result.allowed else "BLOCK"
        parts = [
            utcnow_iso(),
            f"gate={kind}",
            verdict,
            f"layer={result.layer or '-'}",
            f"topic={result.topic or '-'}",
            f"ran={'+'.join(result.layers_run) or '-'}",
            f"skipped={'+'.join(result.layers_skipped) or '-'}",
            f"ms={int(result.duration_s * 1000)}",
        ]
        self._write(" ".join(parts))

    def event(self, name: str, **fields: object) -> None:
        """Record a non-gate event: unlocks, tier changes, plugin loads.

        Callers must pass identifiers and counts, not user or model text.
        """
        parts = [utcnow_iso(), f"event={name}"]
        parts.extend(f"{key}={value}" for key, value in sorted(fields.items()))
        self._write(" ".join(parts))
