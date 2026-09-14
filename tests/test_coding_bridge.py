"""Repository presentation uses real core tools, live grants and bounded workers."""
import subprocess
import threading
import time

import pytest
from PySide6.QtCore import QCoreApplication, QUrl

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.ui.bridge.coding import CodingBridge


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('AKIRA_CONFIG_DIR', str(tmp_path / 'config'))
    app = QCoreApplication.instance() or QCoreApplication([])
    folder = tmp_path / 'Project with spaces'; folder.mkdir()
    def git(*args):
        return subprocess.run(['git', '-C', str(folder), *args], check=True,
                              capture_output=True, text=True).stdout
    git('init', '--initial-branch=main')
    (folder / 'app.py').write_text('print("before")\n', encoding='utf-8')
    git('add', 'app.py')
    git('-c', 'user.name=UI Test', '-c', 'user.email=ui@example.test',
        '-c', 'commit.gpgSign=false', 'commit', '-m', 'Initial local fixture')
    policy = Policy()
    bridge = CodingBridge(policy=lambda: policy, audit=AuditLog(tmp_path / 'audit.jsonl'),
                          secrets=SecretStore(tmp_path / 'secrets'))
    yield app, folder, policy, bridge, git
    bridge.close()
    bridge._worker.join(timeout=3)


def finish(app, bridge):
    deadline = time.monotonic() + 12
    while bridge.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    assert not bridge.busy, 'repository request did not finish'


def test_reads_real_status_staged_unstaged_and_history_without_writing(workspace):
    app, folder, policy, bridge, git = workspace
    bridge.inspect(str(folder), 'working'); finish(app, bridge)
    assert 'Not permitted' in bridge.error and not bridge.preview
    policy.grant('vcs.read', (str(folder),)); bridge.invalidate()
    (folder / 'app.py').write_text('print("staged")\n', encoding='utf-8')
    git('add', 'app.py')
    (folder / 'app.py').write_text('print("working")\n# <img src="https://example.test">\n', encoding='utf-8')
    (folder / 'new.txt').write_text('untracked', encoding='utf-8')
    index_before = (folder / '.git/index').read_bytes()
    bridge.inspect(QUrl.fromLocalFile(str(folder)).toString(), 'working'); finish(app, bridge)
    assert not bridge.error and bridge.checked and bridge.changes == 2
    assert '+print("working")' in bridge.preview and '<img src=' in bridge.preview
    assert 'new.txt' in bridge.status and 'new.txt' not in bridge.preview
    bridge.inspect(str(folder), 'staged'); finish(app, bridge)
    assert '+print("staged")' in bridge.preview and 'working' not in bridge.preview
    bridge.inspect(str(folder), 'history'); finish(app, bridge)
    assert 'Initial local fixture' in bridge.preview
    assert not policy.granted('vcs.write')
    assert (folder / '.git/index').read_bytes() == index_before
    assert git('diff', '--cached', '--name-only').strip() == 'app.py'
    assert git('diff', '--name-only').strip() == 'app.py'


def test_clean_non_repository_and_nested_scope(workspace):
    app, folder, policy, bridge, git = workspace
    policy.grant('vcs.read', (str(folder.parent),)); bridge.invalidate()
    bridge.inspect(str(folder), 'working'); finish(app, bridge)
    assert not bridge.error and bridge.changes == 0 and bridge.preview == 'No unstaged changes.'
    nested = folder / 'nested'; nested.mkdir()
    bridge.inspect(str(nested), 'working'); finish(app, bridge)
    assert 'top of the repository' in bridge.error and not bridge.preview
    other = folder.parent / 'Bare repository'; other.mkdir()
    subprocess.run(['git', 'init', '--bare', str(other)], check=True, capture_output=True)
    bridge.inspect(str(other), 'working'); finish(app, bridge)
    assert 'not a git repository' in bridge.error


def test_editor_uses_existing_tool_and_requires_file_read(workspace, monkeypatch):
    from akira.core.tools.builtin import coding
    app, folder, policy, bridge, _ = workspace
    launched = []
    monkeypatch.setattr(coding, '_find_vscode', lambda: (folder / 'Code.exe', folder / 'cli.js'))
    monkeypatch.setattr(coding, '_launch', lambda argv, env: launched.append((argv, env)))
    policy.grant('vcs.read', (str(folder),)); bridge.invalidate()
    bridge.openEditor(str(folder)); finish(app, bridge)
    assert 'Not permitted' in bridge.error and not launched
    policy.grant('files.read', (str(folder),)); bridge.invalidate()
    bridge.openEditor(str(folder)); finish(app, bridge)
    assert not bridge.error and 'Opened' in bridge.notice
    assert launched[0][0][-1] == str(folder.resolve())
    assert launched[0][1]['ELECTRON_RUN_AS_NODE'] == '1'
    monkeypatch.setattr(coding, '_find_vscode', lambda: None)
    bridge.openEditor(str(folder)); finish(app, bridge)
    assert 'VS Code was not found' in bridge.error and len(launched) == 1


def test_late_results_revocation_and_project_invalidation(workspace, monkeypatch):
    app, folder, policy, bridge, _ = workspace
    policy.grant('vcs.read', (str(folder),)); bridge.invalidate()
    entered, release = threading.Event(), threading.Event()
    original = bridge._registry.invoke
    def delayed(*args):
        result = original(*args)
        if args[0] == 'git_diff':
            entered.set(); release.wait(5)
        return result
    monkeypatch.setattr(bridge._registry, 'invoke', delayed)
    bridge.inspect(str(folder), 'working')
    assert entered.wait(6)
    policy.revoke('vcs.read')
    release.set(); finish(app, bridge)
    assert not bridge.preview and not bridge.status
    policy.grant('vcs.read', (str(folder),)); bridge.invalidate()
    entered.clear(); release.clear()
    bridge.inspect(str(folder), 'working')
    assert entered.wait(6)
    bridge.invalidate()
    release.set()
    for _ in range(30):
        app.processEvents(); time.sleep(.005)
    assert not bridge.folder and not bridge.preview
    bridge.inspect(str(folder), 'history'); finish(app, bridge)
    assert bridge.preview
    policy.revoke('vcs.read'); bridge._check_expiry()
    assert not bridge.preview


@pytest.mark.parametrize('path', ['file://remote/repo', r'\\remote\share\repo',
                                  'https://example.test/repo', 'relative'])
def test_rejects_remote_or_relative_editor_paths(workspace, path):
    app, _, _, bridge, _ = workspace
    bridge.openEditor(path); finish(app, bridge)
    assert bridge.error and not bridge.notice
