# Claude → Codex: "Do it", Claude in the chat window, firmware tools, and Settings as pages

The person asked for these in order: run the behaviour eval again; hand a chat's
request to the software team; Claude, through Anthropic's API, chosen in the chat
window rather than in Settings (Opus 5.5 where a model is named); as many
firmware tools as can be given, since firmware and software are their main work;
then Settings reorganised after Claude's own settings menu, with a page for each
category and a short description for every setting; and a last full test run.

## The behaviour eval

53 of 53 and 20 of 20 again (`tools/behaviour_eval.py`). It holds the graphics
card for its whole run, so Akira crawls if it is open at the same time; the chat
now warns once when another program holds a gigabyte or more of the card.

## "Do it"

Below a chat's answer, "Do it" hands the request to the software team in a folder
the person chooses, with the chat's own words as the task (`akira/core/handoff.py`).
The team's answer comes back into the chat. See "Do it" under `Chat` in
QML_BRIDGES.md.

## Claude Opus 5.5, chosen in the composer

- The composer's model menu has Local and Claude Opus 5.5. Choosing Claude
  without a key opens `ClaudeSheet.qml` for it. Settings, Models has the key too.
- `akira/core/cloud.py` is raw HTTP through the one door (`net/client.py`), not
  Anthropic's SDK: `call()` gained a sign-in header (`key=`) and validated extra
  `headers=`; no new hosts, nothing loosened for reading sites.
- The key is sealed with DPAPI (`model.anthropic`) and checked against Anthropic
  before it is kept. Connecting allows `model.cloud` for "anthropic"; it can be
  taken back in Permissions, Models.
- Each request asks for `fallbacks: "default"` (server-side fallback when Opus
  declines), effort medium for everyday chat and high for code and agents, no
  `thinking` or `temperature`, not streamed, 16,000 tokens at most.
- "Do it" from a Claude chat runs the team on Claude too.
- **Never tested against the live API**: there is no key on this computer.

## Firmware

- Tools (`akira/core/tools/builtin/firmware.py`): `list_boards`, `read_serial`,
  `read_register` (`device.read`); `flash_firmware` (`device.write`, asked every
  time, never "don't ask again"); `generate_cubemx_code`; `stm32_pins` and
  `find_vendor_names`. Registers are named from the CMSIS device header.
- The implementer has all of them; the architect and reviewer the lookups.
- **Bug fixed in the last check:** given a project folder, `flash_firmware` chose
  the newest build when asking and again when writing, so a build finishing in
  between would have been written instead of the one approved. The file shown
  is now the one written, and a change to it after the question refuses.
- **Untested on hardware**: no board was connected, and nothing was ever flashed.

## Settings, a page at a time

- `SettingsSheet.qml`: a list on the left (`Sheet.sidebar`, new), one page on the
  right, at a fixed size. Pages: General, Appearance, Models, Voice, Firmware,
  Permissions, Accounts, Web search, Location, Chats.
- `FormRow` shows its `description` again, one short line under the name.
- The Permissions, Place and Accounts sheets are gone: their content is
  `PermissionsPane`, `PlacePane` and `AccountsPane`, loaded only while their page
  is shown. Every "Permissions" button calls `settingsSheet.show("permissions")`.
  `VoicePane` is both the Voice page and the composer's microphone sheet.
- Permissions shows one group at a time. **Bug fixed:** the boards', Akira's own
  calendar's and cloud drives' permissions were in no group, so they could be
  allowed nowhere. A test now checks every domain is grouped.
- New bridge `Firmware` (`bridge/firmware.py`) for the Firmware page: ST's tools
  found or not, and Look for boards (needs `device.read`, recorded either way).

See "Settings" and `Firmware` in QML_BRIDGES.md.

## Notifications say "Akira"

Windows had recorded Akira's notifications under its bare AppUserModelID,
`Akira.Desktop.1`, which it shows as the name when the id has none (not seen
first-hand: read from its notification records). At start, the real app now
names the id "Akira", with its logo, under
`HKEY_CURRENT_USER\Software\Classes\AppUserModelId\Akira.Desktop.1`; nothing
is written when it is already there, and tests use a fake registry.

## Tests

Full suite: 3133 passed, 8 skipped, none failing (2026-10-02); verify_offline.py passes.

Every page and sheet was also drawn offscreen at 900 × 600 in both appearances,
with no QML warnings and nothing cut off. Untested: Claude against the live API
(no key here) and the board tools on a board (none connected; nothing flashed).
