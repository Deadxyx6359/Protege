"""Bounded presentation history for interactive runs, not an agent memory.

Only the task, final answer, progress labels and source references are saved.
Tool arguments, page bodies and intermediate model messages are never archived.
Call writes on a worker; the lock serializes completion and user deletions.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re
import threading
import time

MAX_RUNS = 60
MAX_BYTES = 12_000_000

#: A run's id, as it is accepted from disk: hex from `secrets.token_hex`, or the
#: UUID shape earlier records were written with. Checked because the id names a
#: record. The module that makes UUIDs is not imported anywhere in Akira -- its
#: `getnode()` reads the machine's network interfaces, so `verify_offline.py`
#: counts it as networking -- and this is the same check without it.
_ID = re.compile("(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                 "|[0-9a-f]{16,64})")


def clean_record(value: dict) -> dict:
    """Whitelist the disk format; cached preview content cannot leak into it."""
    if not isinstance(value, dict):
        raise ValueError("Invalid saved investigation")
    ident = str(value["id"])
    if not _ID.fullmatch(ident):
        raise ValueError("Invalid saved investigation")
    result = {"id": ident}
    for key, limit in {"task": 4000, "answer": 60000, "name": 80, "kind": 16,
                       "projectId": 200, "projectName": 200, "folder": 4096,
                       "status": 24, "stopped": 40}.items():
        result[key] = str(value.get(key, ""))[:limit]
    for key in ("started", "ended"):
        stamp = float(value.get(key, 0))
        result[key] = stamp if math.isfinite(stamp) else 0
    result["members"] = [str(m)[:80] for m in value.get("members", [])[:12]]
    result["states"] = {str(k)[:80]: str(v)[:160]
                        for k, v in list(value.get("states", {}).items())[:12]}
    result["models"] = {str(k)[:80]: {"route": str(v.get("route", ""))[:24],
                                    "label": str(v.get("label", ""))[:240]}
                        for k, v in list(value.get("models", {}).items())[:12] if isinstance(v, dict)}
    result["sources"] = [
        {k: str(s.get(k, ""))[:limit] for k, limit in
         {"id": 80, "title": 240, "locator": 2048, "kind": 40, "tool": 80}.items()}
        for s in value.get("sources", [])[:32] if isinstance(s, dict)]
    result["artifacts"] = [
        {k: str(a.get(k, ""))[:limit] for k, limit in
         {"id": 80, "path": 4096, "name": 240, "tool": 80}.items()}
        for a in value.get("artifacts", [])[:24] if isinstance(a, dict)]
    result["events"] = [
        {**{k: str(e.get(k, ""))[:160] for k in ("kind", "agent", "tool", "to")},
         "ok": bool(e.get("ok", True))}
        for e in value.get("events", [])[-80:] if isinstance(e, dict)]
    return result


class RunArchive:
    def __init__(self, path: Path | None = None):
        self.path = path
        self._lock = threading.Lock()
        self._records: dict[str, dict] = {}
        self.error = ""
        self._unreadable = False
        if path is not None and path.exists():
            try:
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError("the saved history is too large")
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("version") != 1 or not isinstance(data.get("runs"), list):
                    raise ValueError("unsupported history format")
                for value in data["runs"][:MAX_RUNS]:
                    row = clean_record(value)
                    if row["status"] == "running":
                        row["status"] = "interrupted"
                        row["stopped"] = "interrupted"
                        row["states"] = {m: ("Interrupted" if state not in ("Done", "Failed", "Waiting") else state)
                                         for m, state in row["states"].items()}
                    self._records[row["id"]] = row
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                self._records = {}
                self._unreadable = True
                self.error = f"Saved investigations could not load: {exc}. The existing file was kept."

    def records(self) -> list[dict]:
        with self._lock:
            return deepcopy(sorted(self._records.values(), key=lambda r: r["started"], reverse=True))

    def _write(self, records: dict[str, dict]) -> None:
        if self._unreadable:
            raise OSError("The existing history file could not be read. It has not been overwritten.")
        if self.path is not None:
            payload = json.dumps({"version": 1, "runs": list(records.values())}, ensure_ascii=False)
            if len(payload.encode("utf-8")) > MAX_BYTES:
                raise OSError("Saved investigations have reached the storage limit.")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(payload, encoding="utf-8")
            # Windows indexers can briefly hold the destination between saves.
            # Retry only this atomic replace, on the worker; never erase the
            # original as a workaround for a sharing violation.
            for attempt in range(4):
                try:
                    temporary.replace(self.path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(.025 * (attempt + 1))
        self._records = records

    def save(self, record: dict) -> None:
        row = clean_record(record)
        with self._lock:
            updated = dict(self._records)
            updated[row["id"]] = row
            ordered = sorted(updated.values(), key=lambda r: r["started"], reverse=True)[:MAX_RUNS]
            self._write({r["id"]: r for r in ordered})

    def delete(self, ident: str) -> None:
        with self._lock:
            self._write({k: v for k, v in self._records.items() if k != ident})
