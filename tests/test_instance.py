"""One Akira at a time: launched again, it brings the running one forward."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from akira.ui import instance as instance_module
from akira.ui.instance import Instance, default_name

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows named objects")

REPO = Path(__file__).resolve().parent.parent


def unique() -> str:
    return f"Akira.Test.{os.getpid()}.{time.perf_counter_ns()}"


def test_a_second_akira_asks_the_first_to_show_itself_and_leaves():
    name = unique()
    first = subprocess.Popen(
        [sys.executable, "-c", '''
import os, sys, time
sys.path.insert(0, sys.argv[1])
from akira.ui.instance import Instance
me = Instance(sys.argv[2])
assert me.first
me.listen(lambda: (print("called", flush=True), os._exit(0)))
print("ready", flush=True)
time.sleep(30)
''', str(REPO), name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert first.stdout.readline().strip() == "ready"
        second = Instance(name)
        assert not second.first
        assert second.call_first()
        assert first.stdout.readline().strip() == "called"
        assert first.wait(10) == 0
    finally:
        first.kill()
        first.wait()


def test_once_the_first_has_quit_the_next_launch_is_the_first():
    name = unique()
    first = Instance(name)
    second = Instance(name)
    assert first.first and not second.first
    second.release()  # as its process ending would
    first.release()
    again = Instance(name)
    assert again.first
    again.release()


def test_the_first_does_not_call_itself():
    me = Instance(unique())
    assert me.first and not me.call_first()
    me.release()


def test_another_configuration_is_another_akira(monkeypatch, tmp_path):
    monkeypatch.setattr(instance_module, "config_dir", lambda: tmp_path / "one")
    one = default_name()
    monkeypatch.setattr(instance_module, "config_dir", lambda: tmp_path / "two")
    assert default_name() != one
    monkeypatch.setattr(instance_module, "config_dir", lambda: Path(str(tmp_path / "ONE") + "\\"))
    assert default_name() == one, "the same folder however it is written"
