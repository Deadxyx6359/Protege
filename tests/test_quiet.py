"""Keeping out of the way: background priority, and whether something else has the card."""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

import pytest

from akira.core import quiet

REPO = Path(__file__).resolve().parent.parent
GB = 1024**3


class FakeCard:
    def __init__(self, used=None, load=None):
        self.used, self.load, self.asked = used, load, 0

    def used_bytes(self):
        self.asked += 1
        return self.used

    def load_percent(self):
        return self.load


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def watch(screen="", **card):
    clock = Clock()
    fake = FakeCard(**card)
    return quiet.CardWatch(screen=lambda: screen, card=fake, clock=clock), fake, clock


def test_a_full_screen_program_is_enough_and_the_card_is_not_woken_for_it():
    cards, fake, _ = watch(screen="a game is running full screen", used=0)
    assert cards.busy() == "a game is running full screen"
    assert fake.asked == 0


def test_another_program_holding_the_cards_memory_has_it():
    cards, _, _ = watch(used=int(3.2 * GB))
    assert cards.busy() == "another program is using 3.2 GB of the graphics card"


def test_a_card_at_rest_is_free():
    # What this card shows with nothing on it: 150 MB, and no load reading while asleep.
    cards, _, _ = watch(used=150 * 1024**2, load=None)
    assert cards.busy() == ""


def test_a_busy_card_with_little_memory_in_use_still_counts():
    cards, _, _ = watch(used=300 * 1024**2, load=80)
    assert cards.busy() == "another program is using the graphics card (80%)"


def test_without_an_nvidia_card_only_the_screen_is_read():
    cards, _, _ = watch(used=None, load=None)
    assert cards.busy() == ""


def test_the_card_is_asked_at_most_every_few_minutes_unless_told_to_forget():
    cards, fake, clock = watch(used=0)
    cards.busy(); cards.busy()
    assert fake.asked == 1
    clock.now += quiet.RECHECK_S
    cards.busy()
    assert fake.asked == 2
    cards.forget()
    cards.busy()
    assert fake.asked == 3


class FakeNvml:
    def __init__(self, init=0, used=2 * GB, gpu=40, use_code=0):
        self._init, self._used, self._gpu, self._use_code = init, used, gpu, use_code

    def nvmlInit_v2(self):
        return self._init

    def nvmlDeviceGetHandleByIndex_v2(self, index, handle):
        return 0

    def nvmlDeviceGetMemoryInfo(self, device, memory):
        memory._obj.used = self._used
        return 0

    def nvmlDeviceGetUtilizationRates(self, device, use):
        use._obj.gpu = self._gpu
        return self._use_code


def test_the_driver_is_read_through_nvml():
    card = quiet.Nvidia(FakeNvml())
    assert card.used_bytes() == 2 * GB
    assert card.load_percent() == 40


def test_a_sleeping_card_gives_no_load_reading_rather_than_a_wrong_one():
    card = quiet.Nvidia(FakeNvml(use_code=999))  # NVML_ERROR_UNKNOWN, as this card answers
    assert card.load_percent() is None


def test_no_driver_means_no_readings():
    card = quiet.Nvidia(FakeNvml(init=9))
    assert card.used_bytes() is None and card.load_percent() is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows background mode")
def test_background_mode_goes_on_and_off_once_each():
    script = '''
import sys
sys.path.insert(0, sys.argv[1])
from akira.core import quiet
print(quiet.background_priority(True), quiet.background_priority(True), quiet.in_background(),
      quiet.background_priority(False), quiet.background_priority(False), quiet.in_background())
'''
    result = subprocess.run([sys.executable, "-c", script, str(REPO)], capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "False", "True", "True", "False", "False"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows notification state")
def test_the_screen_is_read_without_error():
    assert isinstance(quiet.full_screen(), str)
