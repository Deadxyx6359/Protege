""""Do it": an answer in the chat handed to the software team, and what it did
brought back into the conversation."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QCoreApplication  # noqa: E402

from akira.core import handoff  # noqa: E402
from akira.core.config import AppConfig  # noqa: E402
from akira.core.conversation import Message  # noqa: E402
from akira.core.conversations import ConversationStore  # noqa: E402
from akira.core.models import ModelRouter  # noqa: E402
from akira.ui.bridge import ChatBridge  # noqa: E402

ANSWER = ("Add this to Core/Src/sharp_lcd.c:\n```c\nvoid SharpLCD_Refresh(void) {}\n```\n\n"
          "Check before using: 1 of the 3 STM32G474RE library names in this answer are not in "
          "the library's files.")


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def conversation(*pairs):
    return [Message(role, text) for role, text in pairs]


# -- the task --------------------------------------------------------------------------------


def test_the_task_is_the_request_and_the_answer_without_akiras_notes():
    task = handoff.task_from(conversation(
        ("user", "My display is on SPI1."), ("assistant", "Good."),
        ("user", "Write the refresh function."), ("assistant", ANSWER)), r"C:\work\SharpLCD")
    assert task.startswith(r"Carry out what this chat settled on, in C:\work\SharpLCD.")
    assert "What the person asked:\nWrite the refresh function." in task
    assert "void SharpLCD_Refresh(void) {}" in task
    assert "Check before using" not in task, "Akira's note on the answer is not the answer"
    assert "Earlier in the chat they said: My display is on SPI1." in task
    assert len(task) <= 3_900


def test_a_long_answer_is_cut_to_fit_the_agents_page():
    task = handoff.task_from(conversation(("user", "Write it."),
                                          ("assistant", "```c\n" + "int x;\n" * 2000 + "```")),
                             "C:\\w")
    assert len(task) <= 3_900 and "[… the rest of the answer]" in task


def test_there_is_nothing_to_carry_out_without_an_answer():
    assert handoff.task_from(conversation(("user", "Hello")), "C:\\w") == ""
    assert handoff.task_from(conversation(("user", "Hi"), ("assistant", "")), "C:\\w") == ""
    failed = [Message("user", "Write it."), Message("assistant", "boom", error=True)]
    assert handoff.task_from(failed, "C:\\w") == ""


def test_work_is_code_or_files_named():
    assert handoff.worth_doing("```c\nint x;\n```")
    assert handoff.worth_doing("Add Core/Src/sharp_lcd.c to CMakeLists.txt.")
    assert not handoff.worth_doing("Paris is the capital of France.")


def test_what_the_chat_says_when_the_team_is_done():
    assert handoff.result_said(True, "Wrote two files.", "answered").startswith(
        "**The software team finished.**\n\nWrote two files.")
    assert handoff.result_said(False, "The build failed.", "failed").startswith(
        "**The software team could not finish.**")
    assert handoff.result_said(False, "", "cancelled") == "The software team was stopped."


# -- the chat ----------------------------------------------------------------------------------


def bridge(tmp_path, *, folder="C:\\work\\SharpLCD", started=""):
    handed = []

    def hand_off(task, where):
        handed.append((task, where))
        return started

    stopped = []
    chat = ChatBridge(ModelRouter(AppConfig()), AppConfig(), ConversationStore(tmp_path / "chats"),
                      hand_off=hand_off, folder=lambda: folder,
                      stop_hand_off=lambda: stopped.append(True))
    return chat, handed, stopped


def answered(chat, answer=ANSWER):
    chat._conversation.add("user", "Write the refresh function.")
    chat._conversation.add("assistant", answer)
    chat._model.reset(chat._conversation.messages)


def test_do_it_is_offered_under_an_answer_with_work_in_it(app, tmp_path):
    chat, _, _ = bridge(tmp_path)
    assert not chat.canHandOff, "nothing to carry out yet"
    answered(chat, "Paris is the capital of France.")
    assert not chat.canHandOff, "not every answer is work"
    answered(chat)
    assert chat.canHandOff and chat.handOffFolder == "C:\\work\\SharpLCD"


def test_handing_off_starts_the_team_and_its_result_comes_back(app, tmp_path):
    chat, handed, _ = bridge(tmp_path)
    answered(chat)
    told = []
    chat.handOffChanged.connect(lambda: told.append(chat.handingOff))
    assert chat.handOff("") == ""
    ((task, where),) = handed
    assert where == "C:\\work\\SharpLCD" and "SharpLCD_Refresh" in task
    assert chat.handingOff and not chat.canHandOff and told[-1] is True
    chat.hand_off_finished(True, "Wrote Core/Src/sharp_lcd.c and it builds.", "answered")
    last = chat._conversation.messages[-1]
    assert last.role == "assistant" and last.text.startswith("**The software team finished.**")
    assert not chat.handingOff
    assert chat._store.load(chat._conversation.id).messages[-1].text == last.text


def test_a_folder_is_asked_for_when_no_project_has_one(app, tmp_path):
    chat, handed, _ = bridge(tmp_path, folder="")
    answered(chat)
    assert chat.handOff("") == "Choose the folder the work is for first." and handed == []
    assert chat.handOff("D:\\firmware") == "" and handed[0][1] == "D:\\firmware"


def test_why_the_team_did_not_start_is_said(app, tmp_path):
    chat, _, _ = bridge(tmp_path, started="The research team is still working.")
    answered(chat)
    assert chat.handOff("") == "The research team is still working."
    assert not chat.handingOff and chat.canHandOff


def test_the_result_goes_to_the_conversation_it_came_from(app, tmp_path):
    chat, _, stopped = bridge(tmp_path)
    answered(chat)
    source = chat._conversation.id
    chat.handOff("")
    chat.stopHandOff()
    assert stopped == [True]
    chat.newChat()
    chat.hand_off_finished(False, "", "cancelled")
    assert chat._store.load(source).messages[-1].text == "The software team was stopped."
    assert chat._conversation.messages == []
