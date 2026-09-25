"""Drafts a pipeline made, waiting for the person (E3) — the `Drafts` bridge.

A scheduled pipeline drafts, reviews and revises a piece, and leaves it here.
It is never published by the schedule. The person reads it, and the review
that shaped it, and then publishes it, edits it first, or throws it away.

`publish(id, text)` is the person pressing Publish, with the draft and where it
will go in front of them: that press is the confirmation the publishing tool
asks for, and it is recorded as theirs. The tool's permissions still hold: a
new note needs `vault.write` for its place, a new file `files.write`, an email
`mail.send` for the sending address. If one is missing, the draft stays
waiting and `note` says what to allow.

Publishing runs on a worker, since an email goes over the network, and the
result crosses back on a queued signal.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.making import pipeline
from akira.core.making.pipeline import DISCARDED, PUBLISHED, WAITING, DraftStore, PipelineError
from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import ToolContext, ToolRegistry

#: How much of a draft the list shows.
EXCERPT = 240


class DraftsBridge(QObject):
    """The drafts pipelines made, and publishing, editing or discarding one."""

    draftsChanged = Signal()
    stateChanged = Signal()

    #: Private: from any thread to this one.
    _changed = Signal()
    _published = Signal(str, bool, str)

    def __init__(self, store: DraftStore, *, registry: ToolRegistry,
                 policy: Callable[[], Policy], audit: AuditLog, secrets: SecretStore,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._registry = registry
        self._policy = policy
        self._audit = audit
        self._secrets = secrets
        self._publishing = ""
        self._note = ""
        self._worker: threading.Thread | None = None
        self._changed.connect(self.draftsChanged)
        self._published.connect(self._on_published)
        store.on_change(self._changed.emit)

    @property
    def store(self) -> DraftStore:
        return self._store

    # -- what the interface reads ------------------------------------------------------------

    @Property("QVariantList", notify=draftsChanged)
    def drafts(self) -> list:
        """Newest first: `id`, `job`, `title`, `brief`, `status` (`waiting`, `published`,
        `discarded`), `made` (epoch seconds), `target` (where it goes, in words),
        `kind`, `outcome` and `excerpt`."""
        return [{"id": d.id, "job": d.job, "title": d.title, "brief": d.brief,
                 "status": d.status, "made": d.made, "target": d.target.describe(),
                 "kind": d.target.kind, "outcome": d.outcome,
                 "excerpt": " ".join(d.text.split())[:EXCERPT]}
                for d in self._store.all()]

    @Property(int, notify=draftsChanged)
    def waitingCount(self) -> int:
        return self._store.waiting()

    @Property(str, notify=stateChanged)
    def publishing(self) -> str:
        """The id of the draft being published now, or ""."""
        return self._publishing

    @Property(str, notify=stateChanged)
    def note(self) -> str:
        """What the last publish did, or why it did not, or ""."""
        return self._note

    @Slot(str, result=str)
    def text(self, draft_id: str) -> str:
        draft = self._store.get(draft_id)
        return draft.text if draft is not None else ""

    @Slot(str, result=str)
    def review(self, draft_id: str) -> str:
        """What the critic said about the first draft, which the one shown was revised from."""
        draft = self._store.get(draft_id)
        return draft.review if draft is not None else ""

    # -- the person's choices ----------------------------------------------------------------

    @Slot(str, str, result=str)
    def edit(self, draft_id: str, text: str) -> str:
        """Keep the person's changes to a waiting draft: "" or why not."""
        draft = self._waiting(draft_id)
        if isinstance(draft, str):
            return draft
        if not text.strip():
            return "A draft cannot be empty. Discard it instead."
        self._store.update(draft_id, text=text[:pipeline.MAX_TEXT],
                           title=pipeline.title_of(text))
        return ""

    @Slot(str, result=str)
    def discard(self, draft_id: str) -> str:
        draft = self._waiting(draft_id)
        if isinstance(draft, str):
            return draft
        self._store.update(draft_id, status=DISCARDED, settled=time.time(),
                           outcome="Thrown away.")
        return ""

    @Slot(str, str, result=str)
    def publish(self, draft_id: str, text: str) -> str:
        """Publish a waiting draft as \a text, where it says it goes: "" once started, or why not.

        Only ever call this from the person's own press of Publish.
        """
        draft = self._waiting(draft_id)
        if isinstance(draft, str):
            return draft
        if self._publishing:
            return "Another draft is being published. Wait for it to finish."
        try:
            tool, arguments = pipeline.publishing(draft, text)
        except PipelineError as exc:
            return str(exc)
        if text.strip() != draft.text.strip():
            self._store.update(draft_id, text=text[:pipeline.MAX_TEXT],
                               title=pipeline.title_of(text))
            if "subject" in arguments:
                arguments["subject"] = pipeline.title_of(text)
        self._publishing, self._note = draft_id, ""
        self.stateChanged.emit()
        self._worker = threading.Thread(target=self._publish, name="akira-publish", daemon=True,
                                        args=(draft_id, tool, arguments))
        self._worker.start()
        return ""

    def _publish(self, draft_id: str, tool: str, arguments: dict) -> None:
        # The person pressed Publish on this draft, seeing it and where it goes:
        # that is the confirmation the tool asks for.
        context = ToolContext(policy=self._policy(), audit=self._audit, secrets=self._secrets,
                              actor="user", confirm=lambda summary: True)
        try:
            result = self._registry.invoke(tool, arguments, context)
            ok, said = result.ok, result.content
        except Exception as exc:  # noqa: BLE001 - a crashed worker must not be silent
            ok, said = False, f"It could not be published: {exc}"
        finally:
            context.finish()
        self._published.emit(draft_id, ok, said)

    @Slot(str, bool, str)
    def _on_published(self, draft_id: str, ok: bool, said: str) -> None:
        try:
            if ok:
                self._store.update(draft_id, status=PUBLISHED, settled=time.time(), outcome=said)
            else:
                self._store.update(draft_id, outcome=said)
        except PipelineError:
            pass
        self._publishing = ""
        self._note = said if ok else f"Not published: {said}"
        self.stateChanged.emit()

    def _waiting(self, draft_id: str) -> pipeline.Draft | str:
        draft = self._store.get(draft_id)
        if draft is None:
            return "That draft is not here any more."
        if draft.status != WAITING:
            return f"That draft was {draft.status} already."
        return draft

    def close(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.join(10.0)
