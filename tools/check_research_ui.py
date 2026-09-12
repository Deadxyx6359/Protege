"""Exercise Research in the real QML shell, with a scripted local backend.

No model is loaded and all conversation writes go to a temporary directory.
Optional screenshots contain only this fixture, never the user's conversations.
Run separately from pytest, whose legacy suite owns a QCoreApplication.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from akira.core.config import AppConfig, ModelConfig
from akira.core.conversations import ConversationStore
from akira.core.models import ModelRouter
from akira.design import ThemeController
from akira.models.base import GenerationResult
from akira.ui.bridge import ChatBridge, SettingsBridge
from akira.ui.engine import build_engine, configure_application, load
from preview_scenes import settle


class ScriptedBackend:
    is_loaded = True
    n_ctx = 2048

    def count_tokens(self, text):
        return max(1, len(text) // 4)

    def generate(self, messages, *, on_token=None, **kwargs):
        parts = ["Start by defining ", "your question. ", "Compare the evidence ",
                 "and record what ", "still needs verification."]
        for part in parts:
            on_token(part)
            threading.Event().wait(0.08)
        return GenerationResult(text="".join(parts))

    def close(self):
        pass


def click(window, item):
    centre = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args()
    app = QGuiApplication(sys.argv[:1])
    configure_application(app)
    with TemporaryDirectory(prefix="akira-research-ui-") as directory:
        temporary = Path(directory)
        placeholder = temporary / "scripted.gguf"
        placeholder.write_bytes(b"fixture-only")
        config = AppConfig(models={"chat": ModelConfig(path=str(placeholder))})
        router = ModelRouter(config)
        backend = ScriptedBackend()

        @contextmanager
        def acquire(route):
            yield backend

        router.acquire = acquire
        store = ConversationStore(temporary / "conversations")
        chat = ChatBridge(router, config, store)
        settings = SettingsBridge(config, router)
        theme = ThemeController(mode="dark", reduce_motion=True)
        engine, theme = build_engine(theme=theme, context={"Chat": chat, "Settings": settings})
        warnings = []
        engine.warnings.connect(lambda errors: warnings.extend(e.toString() for e in errors))
        window = load(engine, REPO / "akira/ui/qml/Main.qml")

        def named(name):
            item = window.findChild(QObject, name)
            # Repeater delegates are visually parented to the layout; Qt's
            # QObject ownership tree does not necessarily contain them.
            pending = [window.contentItem()]
            while item is None and pending:
                candidate = pending.pop()
                if candidate.objectName() == name:
                    item = candidate
                pending.extend(candidate.childItems())
            assert item is not None, name
            return item

        def capture(name):
            if args.out_dir:
                args.out_dir.mkdir(parents=True, exist_ok=True)
                assert window.grabWindow().save(str(args.out_dir / f"{name}.png"))

        sidebar = named("workspaceSidebar")
        tabs = named("workspaceTabs")
        composer = named("workspaceComposer")
        research = named("researchView")
        scene = named("workspaceScene")
        sidebar.navSelected.emit("research")
        settle(window)
        assert research.property("visible")
        assert window.property("currentTab") == "research-1"
        assert scene.property("view") == "research"
        assert composer.property("placeholder") == "What would you like to investigate?"

        for width, height in ((1440, 900), (900, 600)):
            window.setWidth(width)
            window.setHeight(height)
            for mode in ("dark", "light"):
                theme.mode = mode
                settle(window)
                starter = named("researchStarter2")
                top = starter.mapToScene(QPointF(0, 0)).y()
                bottom = starter.mapToScene(QPointF(0, starter.height())).y()
                composer_top = composer.mapToScene(QPointF(0, 0)).y()
                assert 44 < top < bottom < composer_top, "Starter overlaps chrome or input"
                capture(f"research-{width}-{mode}")

        theme.mode = "dark"
        composer.setProperty("text", "Notes to keep.")
        click(window, named("researchStarter0"))
        settle(window, 50)
        draft = composer.property("text")
        assert draft.startswith("Notes to keep.\n\nHelp me explore")
        assert chat.messages.count == 0, "Starter sent a turn without a submit"
        tabs.selected.emit("code-1")
        settle(window, 40)
        assert window.property("currentNav") == "code" and not research.property("visible")
        assert composer.property("text") == draft, "Switching workspace lost the draft"
        tabs.selected.emit("research-1")
        settle(window, 40)
        assert window.property("currentNav") == "research"

        # Native button keyboard activation must prepare a draft too.
        composer.setProperty("text", "")
        named("researchStarter1").forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Space)
        settle(window, 40)
        draft = composer.property("text")
        assert draft.startswith("Compare [idea A]")
        assert chat.messages.count == 0
        # chooseStarter focused the real text input; Enter follows the real
        # Composer -> Chat.send -> worker -> MessageListModel path.
        QTest.keyClick(window, Qt.Key.Key_Return)
        assert chat.busy and chat.messages.count == 2
        assert composer.property("text") == ""
        assert not named("newResearchInquiry").property("enabled")
        for _ in range(50):
            settle(window, 20)
            if not chat.busy:
                break
        assert not chat.busy, "Scripted turn did not finish"
        assert chat.messages.data(chat.messages.index(0, 0), chat.messages.TextRole) == draft
        answer = chat.messages.data(chat.messages.index(1, 0), chat.messages.TextRole)
        assert answer.endswith("still needs verification.")
        assert research.property("count") == 2 and scene.property("quiet")
        settle(window)
        capture("research-conversation")
        old_id = chat.conversationId
        click(window, named("newResearchInquiry"))
        settle(window)
        assert chat.conversationId != old_id and chat.messages.count == 0
        assert store.load(old_id).messages[0].text == draft, "New inquiry lost saved work"
        assert not scene.property("quiet")
        assert window.property("currentNav") == "research"
        assert not warnings, "\n".join(warnings)
        print("PASS Research: sidebar/tabs, editable starters, preserved drafts, keyboard send,")
        print("     streamed local reply, quiet scene, new inquiry saves previous work,")
        print("     dark/light at 1440x900 and 900x600; no QML warnings.")
        window.close()
        router.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
