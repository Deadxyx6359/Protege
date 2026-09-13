"""Real document readers, permission boundaries, and late worker results."""
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QUrl

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools.schema import ToolResult
from akira.ui.bridge.documents import DocumentsBridge, local_path


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('AKIRA_CONFIG_DIR', str(tmp_path / 'config'))
    app = QCoreApplication.instance() or QCoreApplication([])
    folder = tmp_path / 'Work'
    folder.mkdir()
    (folder / 'Notes.md').write_text('# Lanterns\nBioluminescent lanternfish live in the abyss.\n<img src="file://elsewhere">', encoding='utf-8')
    (folder / 'Archive').mkdir()
    (folder / 'hidden.exe').write_bytes(b'not a document')
    policy = Policy()
    bridge = DocumentsBridge(policy=lambda: policy, audit=AuditLog(tmp_path / 'audit.jsonl'),
                             secrets=SecretStore(tmp_path / 'secrets'))
    yield app, folder, policy, bridge
    bridge.close()
    bridge._worker.join(timeout=3)


def finish(app, bridge):
    deadline = time.monotonic() + 6
    while bridge.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert not bridge.busy, 'document operation did not complete'


def test_default_denial_and_scoped_folder_metadata(workspace, monkeypatch):
    app, folder, policy, bridge = workspace
    bridge.openFolder(str(folder))
    finish(app, bridge)
    assert 'Not permitted' in bridge.error
    assert bridge.entries == [] and bridge.folder == ''
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    bridge.openFolder(QUrl.fromLocalFile(str(folder)).toString())
    finish(app, bridge)
    assert bridge.error == ''
    assert [r['name'] for r in bridge.entries] == ['Archive', 'Notes.md']
    assert not bridge.canGoUp
    bridge.openFolder(str(folder.parent))
    finish(app, bridge)
    assert 'Not permitted' in bridge.error
    assert bridge.folder == str(folder.resolve())  # Failed navigation keeps the prior location.


def test_plain_text_preview_keeps_markup_literal_and_requires_files_read(workspace):
    app, folder, policy, bridge = workspace
    policy.grant('docs.read', (str(folder),))
    bridge.invalidate()
    bridge.previewFile(str(folder / 'Notes.md'))
    finish(app, bridge)
    assert 'Not permitted' in bridge.error
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    bridge.previewFile(str(folder / 'Notes.md'))
    finish(app, bridge)
    assert bridge.error == ''
    assert '<img src="file://elsewhere">' in bridge.preview
    assert bridge.preview.startswith('# Lanterns\n')
    assert bridge.selected['kind'] == 'Markdown'
    policy.revoke('files.read')
    bridge._check_expiry()
    assert not bridge.preview and not bridge.selected


def test_office_preview_uses_existing_reader_and_its_separate_grant(workspace):
    from akira.core.documents import word
    app, folder, policy, bridge = workspace
    path = folder / 'Brief.docx'
    path.write_bytes(word.create(word.parse_outline('# Abyss expedition\n\nBring a lantern and a notebook.'), title='Brief'))
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    bridge.previewFile(str(path))
    finish(app, bridge)
    assert 'Not permitted' in bridge.error
    policy.grant('docs.read', (str(folder),))
    bridge.invalidate()
    bridge.previewFile(str(path))
    finish(app, bridge)
    assert bridge.error == '' and 'Bring a lantern' in bridge.preview
    assert not bridge.preview.startswith(str(path))
    assert bridge.selected['kind'] == 'Word'


@pytest.mark.parametrize('extension, expected', [('.xlsx', 'Paper'), ('.pptx', 'Roadmap'), ('.pdf', 'Big Heading')])
def test_spreadsheet_slides_and_pdf_previews(workspace, extension, expected):
    from akira.core.documents import sheets
    from test_office_formats import DECK_PARTS, package_bytes, tiny_pdf
    app, folder, policy, bridge = workspace
    raw = {'.xlsx': lambda: sheets.create([('Budget', [['Item', 'Cost'], ['Paper', 12.5]])], title='Budget'),
           '.pptx': lambda: package_bytes(DECK_PARTS), '.pdf': tiny_pdf}[extension]()
    path = folder / ('Example' + extension)
    path.write_bytes(raw)
    policy.grant('docs.read', (str(folder),))
    bridge.invalidate()
    bridge.previewFile(str(path))
    finish(app, bridge)
    assert not bridge.error and expected in bridge.preview


@pytest.mark.parametrize('path', ['file://remote/private.txt', r'\\remote\share\private.txt',
                                  'https://example.test/file.txt', 'relative.txt'])
def test_picker_only_accepts_absolute_local_paths(path):
    with pytest.raises(ValueError):
        local_path(path)


def test_content_search_returns_real_passages_and_needs_both_text_grants(workspace):
    app, folder, policy, bridge = workspace
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    bridge.openFolder(str(folder))
    finish(app, bridge)
    bridge.search('lanternfish')
    finish(app, bridge)
    assert 'Not permitted' in bridge.error
    policy.grant('docs.read', (str(folder),))
    bridge.invalidate()
    bridge.openFolder(str(folder))
    finish(app, bridge)
    bridge.search('lanternfish')
    finish(app, bridge)
    assert bridge.error == '' and bridge.passages
    assert bridge.passages[0]['path'] == str((folder / 'Notes.md').resolve())
    assert 'lanternfish' in bridge.passages[0]['text']


def test_replaced_request_and_project_invalidation_discard_late_text(workspace, monkeypatch):
    app, folder, policy, bridge = workspace
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    entered, release = threading.Event(), threading.Event()
    original = bridge._registry.invoke
    def delayed(*args):
        entered.set()
        release.wait(3)
        return original(*args)
    monkeypatch.setattr(bridge._registry, 'invoke', delayed)
    bridge.previewFile(str(folder / 'Notes.md'))
    assert entered.wait(2)
    bridge.openFolder(str(folder))  # supersedes the blocked preview
    release.set()
    finish(app, bridge)
    assert bridge.entries and not bridge.preview
    entered.clear(); release.clear()
    bridge.previewFile(str(folder / 'Notes.md'))
    assert entered.wait(2)
    bridge.invalidate()  # same hook used by project switches
    release.set()
    bridge._worker.join(timeout=.05)
    for _ in range(30):
        app.processEvents()
        time.sleep(.005)
    assert not bridge.preview and not bridge.entries and not bridge.folder


def test_expired_text_permission_is_rechecked_when_search_reaches_screen(workspace):
    app, folder, policy, bridge = workspace
    policy.grant('docs.read', (str(folder),))
    bridge.invalidate()
    bridge._receive(bridge._serial, {
        'operation': 'search', 'capability': 'docs.read', 'path': str(folder),
        'passages': [{'path': str(folder / 'Notes.md'), 'text': 'No longer permitted'}]})
    assert bridge.passages == []


def test_search_does_not_publish_passages_outside_the_chosen_folder(workspace, monkeypatch):
    app, folder, policy, bridge = workspace
    policy.grant('files.read', (str(folder.parent),))
    policy.grant('docs.read', (str(folder.parent),))
    bridge.invalidate()
    bridge.openFolder(str(folder))
    finish(app, bridge)
    monkeypatch.setattr(bridge._registry, 'invoke', lambda *args: ToolResult.success('', data={
        'passages': [{'rel': '../outside.md', 'text': 'outside'}, {'rel': 'Notes.md', 'text': 'inside'}]}))
    bridge.search('inside')
    finish(app, bridge)
    assert [p['text'] for p in bridge.passages] == ['inside']


def test_large_text_and_missing_files_fail_without_stuck_loading(workspace):
    app, folder, policy, bridge = workspace
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    (folder / 'Large.txt').write_bytes(b'x' * 200_001)
    bridge.previewFile(str(folder / 'Large.txt'))
    finish(app, bridge)
    assert 'too large' in bridge.error and not bridge.preview
    bridge.previewFile(str(folder / 'Missing.txt'))
    finish(app, bridge)
    assert 'no longer exists' in bridge.error and not bridge.preview


def test_unwritable_audit_log_releases_loading_and_keeps_worker_alive(workspace, monkeypatch):
    app, folder, policy, bridge = workspace
    policy.grant('files.read', (str(folder),))
    bridge.invalidate()
    def failed_log(*args, **kwargs):
        raise OSError('The disk is full')
    monkeypatch.setattr(bridge._audit, 'tool_call', failed_log)
    bridge.openFolder(str(folder))
    finish(app, bridge)
    assert 'activity log could not be written' in bridge.error
    assert not bridge.entries and bridge._worker.is_alive()
