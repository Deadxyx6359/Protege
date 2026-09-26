"""Teaching a model from the person's own conversations (E4) — the `Training` bridge.

The person picks conversations, names the adapter, and starts it. Training runs
in the training environment, often for an hour or more, with the graphics card
lent to it: meanwhile anything wanting a model is told so at once. `progress`
says how far it has got, and `stop()` ends it between steps, keeping nothing.

An adapter, once trained, is listed in `adapters` with the model it goes with.
Switching one on for a route is `Settings.useAdapter(route, model, adapter)`,
and off is `Settings.clearAdapter(route)`: the person's choice, in Settings.

The chosen conversations are written for the trainer and deleted when it ends;
see `akira.core.making.training`.
"""

from __future__ import annotations

import shutil
from typing import Callable

from PySide6.QtCore import Property, QObject, Signal, Slot

from akira.core.conversations import ConversationError, ConversationStore
from akira.core.making import training
from akira.core.making.training import Trainer, TrainingError, examples_from


class TrainingBridge(QObject):
    """Adapters: training one, watching it, and the ones already trained."""

    stateChanged = Signal()
    adaptersChanged = Signal()

    #: Private: from the training's thread to this one.
    _progressed = Signal(object)
    _finished = Signal(str, str)

    def __init__(self, conversations: ConversationStore, trainer: Trainer | None = None, *,
                 in_use: Callable[[], list[str]] = list, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._conversations = conversations
        self._trainer = trainer if trainer is not None else Trainer()
        self._in_use = in_use
        self._progress: dict = {}
        self._note = ""
        self._running = False
        self._progressed.connect(self._on_progress)
        self._finished.connect(self._on_finished)

    # -- what the interface reads ------------------------------------------------------------

    @Property(bool, notify=stateChanged)
    def available(self) -> bool:
        return not training.unavailable()

    @Property(str, notify=stateChanged)
    def unavailableReason(self) -> str:
        return training.unavailable()

    @Property(bool, notify=stateChanged)
    def running(self) -> bool:
        return self._running

    @Property("QVariantMap", notify=stateChanged)
    def progress(self) -> dict:
        """While running: `stage` (`loading`, `training`, `saving`), and in training
        `step`, `steps`, `epoch`, `loss` and `seconds`."""
        return dict(self._progress)

    @Property(str, notify=stateChanged)
    def note(self) -> str:
        return self._note

    @Property("QVariantList", notify=adaptersChanged)
    def adapters(self) -> list:
        """Newest first: `name`, `made`, `examples`, `steps`, `loss`, `seconds`,
        `model` and `adapter` (the paths `Settings.useAdapter` takes)."""
        return [{"name": a.name, "made": a.made, "examples": a.examples, "steps": a.steps,
                 "loss": a.loss, "seconds": a.seconds, "model": a.model, "adapter": a.gguf}
                for a in training.adapters()]

    @Property("QVariantList", constant=False, notify=stateChanged)
    def conversations(self) -> list:
        """Saved conversations to choose from, newest first: `id`, `title`, `turns`, `updated`."""
        return [{"id": s.id, "title": s.title, "turns": s.turns, "updated": s.updated}
                for s in self._conversations.list(limit=500) if s.turns >= 2]

    # -- the person's choices ----------------------------------------------------------------

    @Slot(str, "QVariantList", int, int, result=str)
    def start(self, name: str, ids: list, epochs: int, rank: int) -> str:
        """Train an adapter on the chosen conversations: "" once started, or why not."""
        chosen = []
        for conversation_id in ids:
            try:
                conversation = self._conversations.load(str(conversation_id))
            except ConversationError:
                continue
            chosen.append([(m.role, m.text) for m in conversation.messages if not m.error])
        try:
            self._trainer.start(name, examples_from(chosen), epochs=int(epochs or 2),
                                rank=int(rank or 16), on_progress=self._progressed.emit,
                                on_done=lambda why, made: self._finished.emit(why, name))
        except TrainingError as exc:
            return str(exc)
        self._running, self._progress = True, {"stage": "starting"}
        self._note = "Training has started. Answers wait until it finishes or is stopped."
        self.stateChanged.emit()
        return ""

    @Slot()
    def stop(self) -> None:
        if self._running:
            self._trainer.stop()
            self._note = "Stopping at the end of this step."
            self.stateChanged.emit()

    @Slot(str, result=str)
    def remove(self, name: str) -> str:
        """Delete a trained adapter: "" or why not. Refused while a route uses it."""
        for adapter in training.adapters():
            if adapter.name == name:
                if adapter.gguf in self._in_use():
                    return "That adapter is switched on in Settings; switch it off first."
                shutil.rmtree(adapter.folder, ignore_errors=True)
                self.adaptersChanged.emit()
                return ""
        return "There is no adapter by that name."

    # -- from the training --------------------------------------------------------------------

    @Slot(object)
    def _on_progress(self, update: dict) -> None:
        if isinstance(update, dict) and ("stage" in update or "step" in update):
            self._progress = update
            self.stateChanged.emit()

    @Slot(str, str)
    def _on_finished(self, why: str, name: str) -> None:
        self._running, self._progress = False, {}
        self._note = why or f"“{name}” is trained. Switch it on in Settings to use it."
        self.stateChanged.emit()
        self.adaptersChanged.emit()

    def close(self) -> None:
        if self._running:
            self._trainer.stop()
