"""Code workspace presentation, using the existing guarded coding tools.

Git prose is only displayed, never interpreted as a file action. This adapter
does not stage, write, execute project code, commit, or push. The explicit editor
button invokes open_in_editor with the project's folder and its existing grant.
"""
from __future__ import annotations

from datetime import datetime
import threading
from typing import Callable

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from akira.core.permissions import AuditLog, Decision, Policy, SecretStore
from akira.core.tools.builtin.coding import git_diff, git_log, git_status, open_in_editor
from akira.core.tools.registry import ToolRegistry
from akira.core.tools.schema import ToolContext
from .documents import local_path


class _CurrentPolicy(Policy):
    def __init__(self, current, cancelled):
        super().__init__()
        self.current, self.cancelled = current, cancelled

    def allows(self, capability_id, scope=None):
        if self.cancelled.is_set():
            return Decision(False, capability_id, scope, 'This request was cancelled.')
        return self.current().allows(capability_id, scope)


class CodingBridge(QObject):
    changed = Signal()
    _done = Signal(int, object)

    def __init__(self, *, policy: Callable[[], Policy], audit: AuditLog,
                 secrets: SecretStore, parent=None):
        super().__init__(parent)
        self._policy, self._audit, self._secrets = policy, audit, secrets
        self._registry = ToolRegistry()
        for tool in (git_status, git_diff, git_log, open_in_editor):
            self._registry.register(tool)
        self._condition = threading.Condition()
        self._pending = None
        self._cancelled = threading.Event()
        self._serial = 0
        self._closed = False
        self._busy = False
        self._operation = ''
        self._folder = self._status = self._preview = self._checked = ''
        self._error = self._notice = ''
        self._changes = 0
        self._mode = 'working'
        self._fingerprint = self._grants_key()
        self._done.connect(self._receive)
        self._expiry = QTimer(self)
        self._expiry.setInterval(1000)
        self._expiry.timeout.connect(self._check_expiry)
        self._expiry.start()
        self._worker = threading.Thread(target=self._drain, name='code-review', daemon=True)
        self._worker.start()

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(str, notify=changed)
    def operation(self): return self._operation

    @Property(str, notify=changed)
    def folder(self): return self._folder

    @Property(str, notify=changed)
    def status(self): return self._status

    @Property(str, notify=changed)
    def preview(self): return self._preview

    @Property(str, notify=changed)
    def mode(self): return self._mode

    @Property(int, notify=changed)
    def changes(self): return self._changes

    @Property(str, notify=changed)
    def checked(self): return self._checked

    @Property(str, notify=changed)
    def error(self): return self._error

    @Property(str, notify=changed)
    def notice(self): return self._notice

    def _grants_key(self):
        return tuple((g.capability, g.scopes, g.expires, g.granted)
                     for g in self._policy().active() if g.capability in {'vcs.read', 'files.read'})

    def _check_expiry(self):
        if self._fingerprint != self._grants_key():
            self.invalidate()

    def _cancel(self):
        self._serial += 1
        self._cancelled.set()
        with self._condition:
            self._pending = None
        self._busy = False
        self._operation = ''

    @Slot()
    def cancel(self):
        self._cancel()
        self.changed.emit()

    @Slot()
    def invalidate(self):
        self._cancel()
        self._folder = self._status = self._preview = self._checked = ''
        self._error = self._notice = ''
        self._changes = 0
        self._fingerprint = self._grants_key()
        self.changed.emit()

    @Slot(str, str)
    def inspect(self, folder, mode):
        if mode not in {'working', 'staged', 'history'}:
            self._cancel()
            self._error = 'Choose working changes, staged changes or recent history.'
            self.changed.emit()
            return
        self._start('review', folder, mode)

    @Slot(str)
    def openEditor(self, folder):
        self._start('editor', folder, self._mode)

    def _start(self, operation, folder, mode):
        if self._closed: return
        self._cancel()
        self._cancelled = threading.Event()
        self._operation, self._busy = operation, True
        self._error = self._notice = ''
        if operation == 'review':
            self._folder = self._status = self._preview = self._checked = ''
            self._changes, self._mode = 0, mode
        self.changed.emit()
        with self._condition:
            self._pending = (self._serial, self._cancelled, operation, folder, mode)
            self._condition.notify()

    def _drain(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed: return
                request, self._pending = self._pending, None
            self._work(*request)

    def _work(self, serial, cancelled, operation, folder, mode):
        live = _CurrentPolicy(self._policy, cancelled)
        context = ToolContext(policy=live, audit=self._audit, secrets=self._secrets, actor='person')
        payload = {'operation': operation}
        try:
            path = local_path(folder)
            if not path.is_dir():
                raise ValueError('Set an existing project folder before opening the coding workspace.')
            payload.update(path=str(path), capability='files.read' if operation == 'editor' else 'vcs.read')
            if operation == 'editor':
                result = self._registry.invoke('open_in_editor', {'path': str(path)}, context)
                if not result.ok: raise ValueError(result.content)
                payload['notice'] = result.content
            else:
                status = self._registry.invoke('git_status', {'path': str(path)}, context)
                if not status.ok: raise ValueError(status.content)
                name = 'git_log' if mode == 'history' else 'git_diff'
                arguments = {'path': str(path), 'limit': 12} if mode == 'history' else {
                    'path': str(path), 'staged': mode == 'staged'}
                result = self._registry.invoke(name, arguments, context)
                if not result.ok: raise ValueError(result.content)
                payload.update(status=status.content, changes=status.data.get('changes', 0),
                               preview=result.content, mode=mode,
                               checked=datetime.now().strftime('%b %d, %H:%M:%S'))
        except Exception as exc:
            payload['error'] = str(exc) or 'The coding workspace could not finish this request.'
        if not cancelled.is_set():
            self._done.emit(serial, payload)

    @Slot(int, object)
    def _receive(self, serial, payload):
        if self._closed or serial != self._serial: return
        self._busy, self._operation = False, ''
        if payload.get('error'):
            self._error = payload['error']
        elif not self._policy().allows(payload['capability'], payload['path']):
            self.invalidate()
            return
        elif payload['operation'] == 'editor':
            self._notice = payload['notice']
        else:
            self._folder, self._mode = payload['path'], payload['mode']
            self._status, self._preview = payload['status'], payload['preview']
            self._changes, self._checked = payload['changes'], payload['checked']
        self.changed.emit()

    def close(self):
        self._closed = True
        self._expiry.stop()
        self._cancel()
        with self._condition:
            self._condition.notify()
