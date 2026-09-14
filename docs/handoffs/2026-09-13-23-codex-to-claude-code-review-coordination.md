# Code workspace presentation wiring

Codex → Claude, 2026-09-13. Checkpoint `53313cc` is pushed to `rebuild`.

Continuing the user's frontend assignment with a Code project review panel and
VS Code entry point. I will add a `Coding` presentation bridge and wire it into
`ui/shell.py` and `ui/bridge/__init__.py`. It will invoke your existing
`git_status`, `git_diff`, `git_log` and `open_in_editor` through `ToolRegistry`.

No core tool implementation, Git execution policy, browser/network code or
capability changes are planned. Git output stays display-only: the frontend
will not parse filenames from prose to perform filesystem actions. The editor
target comes from the explicit active project's folder. Review requests run
off the GUI thread, consult the current project policy, and discard results
on project/grant changes. All actions remain user initiated.

Your dirty backend files remain outside my commits. A completion handoff will
document the exact bridge contract, tests and UI limitations.
