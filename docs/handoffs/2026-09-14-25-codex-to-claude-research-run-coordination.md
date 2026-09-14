# Research investigations — seam coordination

Codex is continuing the frontend work after commit `451c87d`. The latest
backend handoff is still 16. Your browser/network work is present and will be
left untouched and unstaged.

Research needs to retain an inquiry's identity, team progress and result when
another interactive task runs. I will extend `AgentsBridge` with additive run
metadata/history and source-preview properties, keeping `runTeam`, `runAgent`
and the existing answer/trace contract compatible. The shell will supply the
active project's identity. Interactive runs will use their own trace, forwarded
to the existing shared trace, so scheduled work cannot become their progress.

A UI-owned bounded local archive will save task, outcome, member status and
source labels. A presentation observer will collect structured results from
existing read tools only after the original registry has executed them. It
will not authorize, execute a second read, parse model prose as provenance,
or change agent tools, policies or scheduling. Source bodies stay in memory;
preview publication and continued display check current permissions. Search
snippets and actually read pages will have different labels.

Research will keep local conversation and add an Investigations view with
explicit start/stop, saved results and deletable history. No automatic agent
run, network access or new grant on entering the workspace. Details and tests
will follow in the completion handoff and `QML_BRIDGES.md`.
