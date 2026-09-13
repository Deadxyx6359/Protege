"""Read-only presentation adapter for the Documents workspace.

Format parsing and content search stay in the existing tools. This adapter
provides structured directory rows, serial background work and Qt notifications.
Choosing a path never grants access. The policy is consulted again on use and
before a result reaches the screen; revoked or superseded work is discarded.
"""
from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import threading
from typing import Callable

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication

from akira.core.permissions import AuditLog, Decision, Policy, SecretStore
from akira.core.tools.builtin.files import read_file
from akira.core.tools.builtin.knowledge import search_documents
from akira.core.tools.builtin.office import read_document
from akira.core.tools.registry import ToolRegistry
from akira.core.tools.schema import ToolContext
from akira.security.paths import real, reject_dangerous

KINDS = {'.docx': 'Word', '.xlsx': 'Excel', '.pptx': 'PowerPoint', '.pdf': 'PDF',
         '.md': 'Markdown', '.txt': 'Text', '.doc': 'Legacy Word',
         '.xls': 'Legacy Excel', '.ppt': 'Legacy PowerPoint'}
TEXT = {'.md', '.txt'}
MAX_ENTRIES = 400
MAX_SCANNED = 4000


def local_path(value: str) -> Path:
    """Decode the picker URL without accepting a remote URL or a UNC path."""
    value = value.strip()
    if value.lower().startswith('file:'):
        url = QUrl(value)
        if not url.isLocalFile() or url.host():
            raise ValueError('Choose a folder or file on this computer.')
        value = url.toLocalFile()
    if not value or value.replace('\\', '/').startswith('//'):
        raise ValueError('Choose a folder or file on this computer.')
    path = Path(value)
    if not path.is_absolute():
        raise ValueError('Choose an absolute local path.')
    reject_dangerous(path)
    # Refuse links before resolving them, including a junction to a network share.
    for part in reversed((path, *path.parents)):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Choose the original location instead of a linked folder or file.')
    resolved = real(path)
    if str(resolved).replace('\\', '/').startswith('//'):
        raise ValueError('Network shares are not supported in this workspace.')
    return resolved


def size_label(size: int) -> str:
    if size < 1024:
        return f'{size} B'
    if size < 1024 * 1024:
        return f'{size / 1024:.0f} KB'
    return f'{size / (1024 * 1024):.1f} MB'


def preview_text(result, path: Path) -> str:
    """Hide the tool's transport heading, already shown by the preview header.

    The readers currently return model-facing prose. Only unwrap the exact
    known envelope; if its format changes, retain the complete tool response.
    Never derive paths or permissions from this display-only transformation.
    """
    if path.suffix.lower() in TEXT:
        count = result.data.get('lines')
        prefix = f'{path} ({count} lines)\n\n'
        if result.content.startswith(prefix):
            lines = result.content[len(prefix):].split('\n') if count else []
            if len(lines) == count and all(line.startswith(f'{i + 1:>5}  ') for i, line in enumerate(lines)):
                return '\n'.join(line[len(f'{i + 1:>5}  '):] for i, line in enumerate(lines)) or '(This file contains no text.)'
    else:
        prefix = f'{path}\n\n'
        if result.content.startswith(prefix):
            return result.content[len(prefix):]
    return result.content


class _LiveReadPolicy(Policy):
    def __init__(self, current: Callable[[], Policy], cancelled: threading.Event):
        super().__init__()
        self._current = current
        self._cancelled = cancelled

    def allows(self, capability_id: str, scope: str | None = None) -> Decision:
        if self._cancelled.is_set():
            return Decision(False, capability_id, scope, 'This request was cancelled.')
        return self._current().allows(capability_id, scope)


class DocumentsBridge(QObject):
    changed = Signal()
    _done = Signal(int, object)

    def __init__(self, *, policy: Callable[[], Policy], audit: AuditLog,
                 secrets: SecretStore, parent: QObject | None = None):
        super().__init__(parent)
        self._policy, self._audit, self._secrets = policy, audit, secrets
        self._registry = ToolRegistry()
        for tool in (read_file, read_document, search_documents):
            self._registry.register(tool)
        self._condition = threading.Condition()
        self._pending = None
        self._cancelled = threading.Event()
        self._serial = 0
        self._closed = False
        self._folder = ''
        self._entries: list[dict] = []
        self._selected: dict = {}
        self._preview = ''
        self._passages: list[dict] = []
        self._query = ''
        self._busy = False
        self._operation = ''
        self._error = ''
        self._limited = False
        self._can_up = False
        self._fingerprint = self._grants_key()
        self._done.connect(self._receive)
        # Expiry has no bridge signal. Recheck displayed data even without a click.
        self._expiry = QTimer(self)
        self._expiry.setInterval(1000)
        self._expiry.timeout.connect(self._check_expiry)
        self._expiry.start()
        # One daemon worker with a single replaceable pending request. Parsers
        # already in progress can finish, but cannot hold app shutdown open.
        self._worker = threading.Thread(target=self._drain, name='documents-view', daemon=True)
        self._worker.start()

    @Property(str, notify=changed)
    def folder(self): return self._folder

    @Property('QVariantList', notify=changed)
    def entries(self): return self._entries

    @Property('QVariantMap', notify=changed)
    def selected(self): return self._selected

    @Property(str, notify=changed)
    def preview(self): return self._preview

    @Property('QVariantList', notify=changed)
    def passages(self): return self._passages

    @Property(str, notify=changed)
    def query(self): return self._query

    @Property(bool, notify=changed)
    def busy(self): return self._busy

    @Property(str, notify=changed)
    def operation(self): return self._operation

    @Property(str, notify=changed)
    def error(self): return self._error

    @Property(bool, notify=changed)
    def limited(self): return self._limited

    @Property(bool, notify=changed)
    def canGoUp(self): return self._can_up

    @Property('QVariantList', notify=changed)
    def roots(self):
        grant = self._policy().granted('files.read')
        return [{'path': p, 'name': Path(p).name or p} for p in grant.scopes] if grant else []

    def _grants_key(self):
        return tuple((g.capability, g.scopes, g.expires, g.granted)
                     for g in self._policy().active() if g.capability in {'files.read', 'docs.read'})

    def _check_expiry(self):
        if self._fingerprint != self._grants_key():
            self.invalidate()

    @Slot()
    def invalidate(self):
        self._cancel()
        self._folder, self._preview, self._query, self._error = '', '', '', ''
        self._entries, self._passages, self._selected = [], [], {}
        self._can_up = self._limited = False
        self._fingerprint = self._grants_key()
        self.changed.emit()

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
    def clearPreview(self):
        if self._operation == 'preview':
            self._cancel()
        self._selected, self._preview = {}, ''
        self.changed.emit()

    @Slot(str)
    def openFolder(self, value): self._start('folder', value)

    @Slot(str)
    def previewFile(self, value): self._start('preview', value)

    @Slot(str)
    def search(self, query):
        if not query.strip():
            self._cancel()
            self._query, self._passages, self._error = '', [], ''
            self.changed.emit()
        elif self._folder:
            self._start('search', self._folder, query.strip())

    @Slot()
    def refresh(self):
        if self._folder: self.openFolder(self._folder)
        elif self._selected: self.previewFile(self._selected['path'])

    @Slot()
    def goUp(self):
        if self._folder and self._can_up:
            self.openFolder(str(Path(self._folder).parent))

    @Slot(result=str)
    def copyPath(self):
        path = self._selected.get('path') or self._folder
        cap = self._selected.get('capability', 'files.read')
        if not path or not self._policy().allows(cap, path):
            return 'This path is no longer available under the current permissions.'
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return 'The clipboard is unavailable.'
        clipboard.setText(path)
        return ''

    def _start(self, operation, value, query=''):
        if self._closed: return
        self._cancel()
        self._cancelled = threading.Event()
        self._busy, self._operation, self._error = True, operation, ''
        if operation == 'folder':
            self._selected, self._preview, self._query, self._passages = {}, '', '', []
        elif operation == 'preview':
            self._selected, self._preview = {}, ''
        else:
            self._query, self._passages = query, []
        self.changed.emit()
        with self._condition:
            self._pending = (self._serial, self._cancelled, operation, value, query)
            self._condition.notify()

    def _drain(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed: return
                request, self._pending = self._pending, None
            self._work(*request)

    def _work(self, serial, cancelled, operation, value, query):
        live = _LiveReadPolicy(self._policy, cancelled)
        context = ToolContext(policy=live, audit=self._audit, secrets=self._secrets, actor='person')
        payload = {'operation': operation}
        try:
            path = local_path(value)
            cap = 'docs.read' if operation == 'search' or (operation == 'preview' and path.suffix.lower() not in TEXT) else 'files.read'
            decision = live.allows(cap, str(path))
            if not decision:
                raise PermissionError(f'Not permitted: {decision.reason}. Review permissions to allow this folder or file.')
            payload.update(path=str(path), capability=cap)
            if operation == 'folder':
                payload.update(self._list(path, live))
                self._audit.tool_call('person', 'browse_documents', {'folder': str(path)},
                                      allowed=True, capability=cap, scope=str(path))
            elif operation == 'preview':
                if path.suffix.lower() not in KINDS:
                    raise ValueError('Text previews support Word, Excel, PowerPoint, PDF, Markdown and text files.')
                if not path.is_file():
                    raise ValueError('This file no longer exists. Refresh the folder and try again.')
                if path.suffix.lower() in TEXT and path.stat().st_size > 200_000:
                    raise ValueError('This text file is too large for a preview (200 KB maximum).')
                result = self._registry.invoke('read_file' if cap == 'files.read' else 'read_document',
                                               {'path': str(path)}, context)
                if not result.ok: raise ValueError(result.content)
                payload.update(preview=preview_text(result, path), selected=self._row(path, False, cap))
            else:
                result = self._registry.invoke('search_documents', {'folder': str(path), 'query': query}, context)
                if not result.ok: raise ValueError(result.content)
                passages = []
                for passage in result.data.get('passages', []):
                    target = local_path(str(path / passage['rel']))
                    need = 'files.read' if target.suffix.lower() in TEXT else 'docs.read'
                    if target.is_relative_to(path) and live.allows(need, str(target)):
                        passages.append({**passage, 'path': str(target), 'name': target.name})
                payload['passages'] = passages
        except Exception as exc:  # Worker failure must always release the loading state.
            payload['error'] = str(exc) or 'This document could not be opened.'
            try:
                self._audit.tool_call('person', 'documents_' + operation, {'path': value},
                                      allowed=False, error=payload['error'])
            except OSError:
                # A full/locked log must not kill the worker or strand loading.
                payload['error'] += ' The activity log could not be written.'
        if not cancelled.is_set():
            self._done.emit(serial, payload)

    @staticmethod
    def _row(path, folder, capability='files.read'):
        info = path.stat(follow_symlinks=False)
        return {'path': str(path), 'name': path.name, 'folder': folder,
                'kind': 'Folder' if folder else KINDS.get(path.suffix.lower(), 'File'),
                'size': '' if folder else size_label(info.st_size),
                'modified': datetime.fromtimestamp(info.st_mtime).strftime('%b %d, %Y'),
                'capability': capability}

    def _list(self, path, policy):
        if not path.is_dir(): raise ValueError('Choose a folder that exists on this computer.')
        rows, limited = [], False
        with os.scandir(path) as contents:
            for index, entry in enumerate(contents):
                if index >= MAX_SCANNED or len(rows) >= MAX_ENTRIES:
                    limited = True
                    break
                child = Path(entry.path)
                # Never follow a link to gather metadata outside the chosen folder.
                if entry.is_symlink() or child.is_junction(): continue
                is_folder = entry.is_dir(follow_symlinks=False)
                if entry.name.startswith(('.', '~$')): continue
                if not is_folder and child.suffix.lower() not in KINDS: continue
                if not policy.allows('files.read', str(child)): continue
                try:
                    rows.append(self._row(child, is_folder))
                except OSError:
                    continue  # A file can disappear while its folder is being listed.
        rows.sort(key=lambda row: (not row['folder'], row['name'].casefold()))
        return {'entries': rows, 'limited': limited,
                'canUp': path.parent != path and bool(policy.allows('files.read', str(path.parent)))}

    @Slot(int, object)
    def _receive(self, serial, payload):
        if self._closed or serial != self._serial: return
        self._busy, self._operation = False, ''
        if payload.get('error'):
            self._error = payload['error']
        elif not self._policy().allows(payload['capability'], payload['path']):
            self.invalidate()
            return
        elif payload['operation'] == 'folder':
            self._folder, self._entries = payload['path'], payload['entries']
            self._limited, self._can_up = payload['limited'], payload['canUp']
        elif payload['operation'] == 'preview':
            self._selected, self._preview = payload['selected'], payload['preview']
        else:
            current = self._policy()
            self._passages = [p for p in payload['passages']
                              if current.allows('files.read' if Path(p['path']).suffix.lower() in TEXT
                                                else 'docs.read', p['path'])]
        self.changed.emit()

    def close(self):
        self._closed = True
        self._expiry.stop()
        self._cancel()
        with self._condition:
            self._condition.notify()
