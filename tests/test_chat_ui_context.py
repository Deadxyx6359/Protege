"""The UI must not show one conversation's retrieval labels under another."""
import pytest
from PySide6.QtCore import QCoreApplication
from akira.core.config import AppConfig
from akira.core.conversation import Conversation
from akira.core.conversations import ConversationStore
from akira.core.models import ModelRouter
from akira.ui.bridge.chat import ChatBridge


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('AKIRA_CONFIG_DIR', str(tmp_path / 'config'))
    app = QCoreApplication.instance() or QCoreApplication([])
    config = AppConfig(models={})
    router = ModelRouter(config)
    store = ConversationStore(tmp_path / 'chats')
    chats = []
    for name in ['a', 'b']:
        chat = Conversation(project=name * 16)
        chat.add('user', 'An existing conversation ' + name)
        store.save(chat)
        chats.append(chat)
    bridge = ChatBridge(router, config, store, project=lambda: 'a' * 16)
    bridge.openConversation(chats[0].id)
    bridge._set_sources([{'source': 'documents', 'cite': 'Private plan'}], 'Retrieved one passage.')
    yield bridge, chats
    bridge.flush()
    router.close()


@pytest.mark.parametrize('operation', ['new', 'open', 'delete'])
def test_navigation_clears_previous_retrieval_labels(context, operation):
    bridge, chats = context
    changes = []
    bridge.sourcesChanged.connect(lambda: changes.append(True))
    assert bridge.conversationProject == 'a' * 16
    if operation == 'new': bridge.newChat()
    elif operation == 'open': bridge.openConversation(chats[1].id)
    else: bridge.deleteConversation(chats[0].id)
    assert bridge.lastSources == [] and bridge.lastContextNote == '' and changes
    assert bridge.conversationProject == ('b' * 16 if operation == 'open' else '')


def test_failed_open_preserves_the_current_conversation_context(context):
    bridge, chats = context
    bridge.openConversation('f' * 32)
    assert bridge.conversationId == chats[0].id
    assert bridge.lastSources and bridge.conversationProject == 'a' * 16


def test_first_message_records_the_project_for_the_interface(context):
    bridge, _ = context
    bridge.newChat()
    assert bridge.conversationProject == ''
    bridge.send('Keep this in the current project.')
    assert not bridge.busy  # No real model is configured or loaded.
    assert bridge.conversationProject == 'a' * 16
