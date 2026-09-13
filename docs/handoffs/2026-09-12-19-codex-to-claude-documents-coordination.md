# Documents UI adapter — work in progress

Codex → Claude, 2026-09-12. The user asked to begin the ranked UI work after
handoff 18. I am implementing the Documents workspace now.

Coordination before changing the shared seam: I plan to add a new
`akira/ui/bridge/documents.py` (`DocumentsBridge`) and register `Documents` in
`ui/shell.py`. Existing bridge signatures and backend document tools remain
unchanged. Please avoid editing those new adapter/wiring pieces concurrently;
I will publish the finished contract and tests in a follow-up handoff.

The UI will browse explicitly chosen local folders under `files.read`, preview
Office/PDF through `read_document` (`docs.read`), and text through `read_file`.
Content search will use the existing `search_documents` tool and its structured
passages. Work runs off the UI thread, stale results are discarded, and changes
to global/project grants or the active project clear the displayed data. The
screen offers a link to the existing permission editor; it does not grant
anything as a side effect of choosing a folder or file.

Planned UI data: current folder, entries, selected path, text preview, search
passages, loading/error states and folder history. Listing returns structured
metadata directly after the existing policy check because `list_directory`
currently returns only prose and a count. Filenames will never be parsed out
of that prose. No shell launch, document writes or new document-format parser
is part of this frontend pass.

This is a coordination note, not a claim that the feature is already complete.
