"""Changing part of a file, and building a C project: the tools an agent needs to
add a driver to an STM32CubeMX project without writing its main.c out again."""

from __future__ import annotations

import json
import shutil
import sys

import pytest

from akira.core.permissions import AuditLog, Policy, SecretStore
from akira.core.tools import default_registry
from akira.core.tools.builtin import coding
from akira.core.tools.schema import ToolContext

MAIN = """int main(void)
{
  MX_GPIO_Init();
  MX_SPI1_Init();
  /* USER CODE BEGIN 2 */

  /* USER CODE END 2 */

  while (1)
  {
  }
}
"""


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AKIRA_CONFIG_DIR", str(tmp_path / "cfg"))


class Confirm:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def __call__(self, summary):
        self.asked.append(str(summary))
        return self.answer


def context_for(tmp_path, confirm, *capabilities):
    policy = Policy()
    for capability in capabilities:
        policy.grant(capability, (str(tmp_path),))
    return ToolContext(policy=policy, audit=AuditLog(tmp_path / "audit.jsonl"),
                       secrets=SecretStore(tmp_path / "secrets"), confirm=confirm,
                       attended=True)


def edit(tmp_path, confirm, find, replace, name="main.c"):
    return default_registry().invoke(
        "edit_file", {"path": str(tmp_path / name), "find": find, "replace": replace},
        context_for(tmp_path, confirm, "files.write"))


def test_part_of_a_file_is_changed_after_the_person_sees_it(tmp_path):
    (tmp_path / "main.c").write_text(MAIN, encoding="utf-8")
    confirm = Confirm()
    result = edit(tmp_path, confirm, "  /* USER CODE BEGIN 2 */\n\n  /* USER CODE END 2 */",
                  "  /* USER CODE BEGIN 2 */\n  SharpLCD_Init(&hspi1);\n  /* USER CODE END 2 */")
    assert result.ok, result.content
    assert "SharpLCD_Init(&hspi1);\n  /* USER CODE END 2 */" in (tmp_path / "main.c").read_text()
    (asked,) = confirm.asked
    assert "These lines:" in asked and "become:" in asked and "SharpLCD_Init" in asked


def test_a_no_changes_nothing(tmp_path):
    (tmp_path / "main.c").write_text(MAIN, encoding="utf-8")
    result = edit(tmp_path, Confirm(answer=False), "while (1)", "for (;;)")
    assert not result.ok and (tmp_path / "main.c").read_text() == MAIN


def test_text_found_twice_or_not_at_all_is_refused_with_what_to_do(tmp_path):
    (tmp_path / "main.c").write_text(MAIN, encoding="utf-8")
    twice = edit(tmp_path, Confirm(), "USER CODE", "x")
    assert not twice.ok and "2 times" in twice.content and "around it" in twice.content
    missing = edit(tmp_path, Confirm(), "MX_SPI2_Init();", "x")
    assert not missing.ok and "Read the file again" in missing.content
    assert (tmp_path / "main.c").read_text() == MAIN


def test_lines_with_other_indentation_are_found_and_the_files_endings_kept(tmp_path):
    (tmp_path / "main.c").write_bytes(MAIN.replace("\n", "\r\n").encode())
    result = edit(tmp_path, Confirm(), "/* USER CODE BEGIN 2 */\n\n/* USER CODE END 2 */",
                  "  /* USER CODE BEGIN 2 */\n  Go();\n  /* USER CODE END 2 */")
    assert result.ok, result.content
    text = (tmp_path / "main.c").read_bytes().decode()
    assert "  /* USER CODE BEGIN 2 */\r\n  Go();\r\n  /* USER CODE END 2 */\r\n" in text
    assert "\n" not in text.replace("\r\n", "")


def test_read_files_line_numbers_are_not_taken_for_text(tmp_path):
    (tmp_path / "main.c").write_text(MAIN, encoding="utf-8")
    result = edit(tmp_path, Confirm(), "    3  MX_GPIO_Init();\n    4  MX_SPI1_Init();",
                  "    3  MX_GPIO_Init();\n    4  MX_SPI1_Init();\n    5  MX_DMA_Init();")
    assert result.ok, result.content
    assert "MX_SPI1_Init();\nMX_DMA_Init();" in (tmp_path / "main.c").read_text()


def test_a_new_file_is_for_write_file(tmp_path):
    result = edit(tmp_path, Confirm(), "x", "y", name="new.c")
    assert not result.ok and "use write_file" in result.content


def test_editing_needs_the_folder_allowed(tmp_path):
    (tmp_path / "main.c").write_text(MAIN, encoding="utf-8")
    result = default_registry().invoke(
        "edit_file", {"path": str(tmp_path / "main.c"), "find": "while (1)", "replace": "x"},
        context_for(tmp_path, Confirm()))
    assert not result.ok and (tmp_path / "main.c").read_text() == MAIN


# -- building --------------------------------------------------------------------------------


def test_the_debug_preset_is_built_when_there_is_one(tmp_path):
    (tmp_path / "CMakePresets.json").write_text(json.dumps({"configurePresets": [
        {"name": "default", "hidden": True}, {"name": "Release"}, {"name": "Debug"}]}))
    assert coding._preset(tmp_path) == "Debug"
    (tmp_path / "CMakePresets.json").write_text(json.dumps({"configurePresets": [
        {"name": "default", "hidden": True}, {"name": "Release"}]}))
    assert coding._preset(tmp_path) == "Release"
    (tmp_path / "CMakePresets.json").unlink()
    assert coding._preset(tmp_path) == ""


def test_only_a_cmake_project_is_built(tmp_path):
    result = default_registry().invoke("build_project", {"path": str(tmp_path)},
                                       context_for(tmp_path, Confirm(), "shell.run"))
    assert not result.ok and "no CMakeLists.txt" in result.content


def test_building_needs_its_folder_allowed_and_asks(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("project(x C)\n")
    refused = default_registry().invoke("build_project", {"path": str(tmp_path)},
                                        context_for(tmp_path, Confirm()))
    assert not refused.ok
    confirm = Confirm(answer=False)
    declined = default_registry().invoke("build_project", {"path": str(tmp_path)},
                                         context_for(tmp_path, confirm, "shell.run"))
    assert not declined.ok and len(confirm.asked) == 1


@pytest.mark.skipif(coding._cmake() is None or shutil.which("gcc") is None
                    and shutil.which("cc") is None, reason="needs CMake and a C compiler")
def test_a_failed_build_reports_its_errors_first(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.20)\nproject(x C)\nadd_executable(x main.c)\n")
    (tmp_path / "main.c").write_text("int main(void) { return missing_name; }\n")
    result = default_registry().invoke("build_project", {"path": str(tmp_path)},
                                       context_for(tmp_path, Confirm(), "shell.run"))
    assert result.ok, result.content
    assert result.content.startswith("The build failed")
    assert "missing_name" in result.content.split("The end of the output:")[0]


def test_build_output_is_told_apart():
    assert coding._MESSAGE.findall("[1/2] Building C object a.c.obj\nmain.c:3:1: error: "
                                   "expected ';'\nok\nmain.c:9: warning: unused variable 'x'") == [
        "main.c:3:1: error: expected ';'", "main.c:9: warning: unused variable 'x'"]
    assert sys.platform  # the module imports on any platform


def test_a_file_given_at_the_wrong_place_is_found_where_it_is(tmp_path):
    (tmp_path / "Core" / "Src").mkdir(parents=True)
    (tmp_path / "Core" / "Src" / "main.c").write_text(MAIN, encoding="utf-8")
    result = edit(tmp_path, Confirm(), "while (1)", "for (;;)")
    assert not result.ok
    assert str(tmp_path / "Core" / "Src" / "main.c") in result.content
    assert "write_file" not in result.content, "not a second main.c beside the first"
