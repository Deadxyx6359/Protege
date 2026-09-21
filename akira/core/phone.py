"""Texts, read from the Phone Link window (C5): what its Messages tab shows, and nothing else.

The person chose to reach their phone's texts through Phone Link, Windows' own
link to a phone. Phone Link keeps no messages on disk that Akira could read, so
they are read from its window the way a screen reader reads them: through
Windows' accessibility interface (UI Automation), from PowerShell, which Windows
ships. Nothing is installed. Nothing in the window is clicked, typed into,
scrolled or changed, and the script that reads it has no way to: it asks for
names and positions and nothing else, which a test holds it to.

What is read is what Phone Link tells a screen reader: each conversation in the
list, as Phone Link describes it, and the messages of the conversation that is
open, each marked as the person's or the other side's by which side of the
thread it sits on. Phone Link must be open on Messages; Akira never opens it.

One-time codes are hidden before anything leaves this module. A text that talks
of a code, a password, a PIN or a sign-in has any code-like run of 4 to 8
characters in it replaced, because such a code is a credential, and credentials
never reach a model.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass

#: How long reading the window may take.
READ_TIMEOUT_S = 20.0

#: The most conversations, and messages of the open one, that are read.
MAX_CONVERSATIONS = 30
MAX_MESSAGES = 60

#: The most of one description that is kept.
MAX_TEXT = 1_000

#: What stands in for a hidden code.
HIDDEN = "[code hidden]"

#: A text that talks about one of these may carry a code.
_ABOUT_CODES = re.compile(
    r"\b(codes?|passcode|password|pin|otp|verif\w*|sign[- ]?in|log[- ]?in|login|2fa|"
    r"two[- ]factor|security|authenticat\w*|one[- ]time)\b", re.IGNORECASE)

#: A code: 4 to 8 digits standing alone, perhaps after a letter prefix such as G-.
#: Not part of a longer number, a price or a decimal.
_CODE = re.compile(r"(?<![\w.,$£€])(?:[A-Z]{1,3}-)?\d{4,8}(?![\w.,%])")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

#: Reads names and positions from Phone Link's window, and nothing else. It calls
#: no pattern that acts (Invoke, SetValue, Select, SetFocus, Scroll), which
#: `tests/test_phone.py` checks.
_READ = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A = [System.Windows.Automation.AutomationElement]
$T = [System.Windows.Automation.TreeScope]
$K = [System.Windows.Automation.ControlType]
function Where-Is($property, $value) {
    New-Object System.Windows.Automation.PropertyCondition($property, $value)
}
$most = [int]$env:AKIRA_PHONE_MOST
$out = @{ window = $false; messages_tab = $false; conversations = @(); title = '';
          detail = ''; thread = @() }
$process = Get-Process -Name PhoneExperienceHost -ErrorAction SilentlyContinue |
    Select-Object -First 1
if ($process) {
    $window = $A::RootElement.FindFirst($T::Children, (Where-Is $A::ProcessIdProperty $process.Id))
    if ($window) {
        $out.window = $true
        $list = $window.FindFirst($T::Descendants, (Where-Is $A::AutomationIdProperty 'CVSListView'))
        if ($list) {
            $out.messages_tab = $true
            $rows = $list.FindAll($T::Descendants, (Where-Is $A::ClassNameProperty 'ListViewItem'))
            foreach ($row in $rows) {
                if ($out.conversations.Count -ge $most) { break }
                $out.conversations += [string]$row.Current.Name
            }
        }
        $pane = $window.FindFirst($T::Descendants,
            (Where-Is $A::AutomationIdProperty 'ConversationPane'))
        if ($pane) {
            $texts = $pane.FindAll($T::Children, (Where-Is $A::ControlTypeProperty ($K::Text)))
            if ($texts.Count -gt 0) { $out.title = [string]$texts[0].Current.Name }
            if ($texts.Count -gt 1) { $out.detail = [string]$texts[1].Current.Name }
            $thread = $pane.FindFirst($T::Children, (Where-Is $A::ControlTypeProperty ($K::List)))
            if ($thread) {
                $frame = $thread.Current.BoundingRectangle
                $middle = $frame.X + $frame.Width / 2
                $walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
                $rows = $thread.FindAll($T::Descendants,
                    (Where-Is $A::ClassNameProperty 'ListViewItem'))
                foreach ($row in $rows) {
                    $side = ''
                    $bubble = $walker.GetFirstChild($row)
                    if ($bubble) {
                        $box = $bubble.Current.BoundingRectangle
                        if (-not $box.IsEmpty) {
                            $side = if ($box.X + $box.Width / 2 -gt $middle) { 'you' } else { 'them' }
                        }
                    }
                    $out.thread += @{ text = [string]$row.Current.Name; side = $side }
                }
            }
        }
    }
}
$out | ConvertTo-Json -Depth 4 -Compress
"""


class PhoneError(RuntimeError):
    """Phone Link could not be read, with a reason for the person."""


@dataclass(frozen=True)
class Said:
    text: str
    side: str
    """"you", "them", or "" when Phone Link had it out of sight and its side is unknown."""


@dataclass(frozen=True)
class Shown:
    conversations: tuple[str, ...]
    """Each conversation in the list, as Phone Link describes it to a screen reader."""
    title: str
    """Who the open conversation is with, or ""."""
    detail: str
    """What Phone Link shows beneath that, usually a number."""
    thread: tuple[Said, ...]
    """The open conversation's messages, oldest first, as far as Phone Link has them."""


def hide_codes(text: str) -> str:
    """\a text with any one-time code hidden, when it talks about codes at all."""
    if not _ABOUT_CODES.search(text):
        return text
    return _CODE.sub(HIDDEN, text)


def _clean(text) -> str:
    words = " ".join(str(text or "").split())
    return hide_codes(words[:MAX_TEXT])


def _run(command: list[str], **options):
    """Runs the reader. Looked up when called, so a test can stand in for it."""
    return subprocess.run(command, **options)


def read() -> Shown:
    """What Phone Link's Messages tab shows now. Raises `PhoneError`."""
    if sys.platform != "win32":
        raise PhoneError("Phone Link is a Windows app.")
    try:
        done = _run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _READ],
                    env={**os.environ, "AKIRA_PHONE_MOST": str(MAX_CONVERSATIONS)},
                    capture_output=True, stdin=subprocess.DEVNULL, timeout=READ_TIMEOUT_S,
                    creationflags=_NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise PhoneError("Reading Phone Link took too long.") from None
    except OSError as exc:
        raise PhoneError(f"Phone Link could not be read: {exc}") from None
    if done.returncode != 0:
        lines = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PhoneError(f"Phone Link could not be read: {lines[-1] if lines else 'no reason'}")
    try:
        data = json.loads(done.stdout.decode("utf-8-sig", "replace") or "{}")
    except ValueError:
        raise PhoneError("Phone Link's window could not be read.") from None
    if not isinstance(data, dict) or not data.get("window"):
        raise PhoneError("Phone Link is not open. Open it on its Messages tab, and Akira can read "
                         "what it shows.")
    if not data.get("messages_tab"):
        raise PhoneError("Phone Link is open, but not on its Messages tab. Open Messages.")
    conversations = [_clean(item) for item in _items(data.get("conversations"))]
    thread = []
    for item in _items(data.get("thread")):
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            side = str(item.get("side") or "")
            thread.append(Said(_clean(item["text"]), side if side in ("you", "them") else ""))
    return Shown(tuple(c for c in conversations if c)[:MAX_CONVERSATIONS],
                 _clean(data.get("title"))[:200], _clean(data.get("detail"))[:200],
                 tuple(thread[-MAX_MESSAGES:]))


def _items(value) -> list:
    # PowerShell writes a list of one as the one item.
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
