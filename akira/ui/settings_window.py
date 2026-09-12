"""The settings window.

Tabbed with `ttk.Notebook`, styled by `theme._style_ttk` to match the
purple/black/ivory palette.

Changes are applied to in-memory objects as they are edited and written to disk
on Save. The trust tier is the exception: it is the one setting that can hand
the model filesystem access, so it re-prompts for the PIN before taking effect.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from .. import store
from ..lock.tripwires import TopicTripwires, TripwireSet, validate_pattern
from ..plugins import EXAMPLE_PLUGIN
from ..plugins import discover as discover_plugins
from ..plugins import plugin_dir
from ..schemas import (
    AuditorSettings,
    Manifest,
    ModelSettings,
    Personality,
    Settings,
)
from ..security.paths import TIERS, capabilities
from .personality_panel import PersonalityPanel
from .pin_dialog import PinChangeDialog, confirm_pin
from . import theme
from .widgets import DANGER_FG, MUTED_FG, WARNING_BG, button_row, read_only_text, set_text


class SettingsWindow(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Misc,
        vault: Path,
        manifest: Manifest,
        settings: Settings,
        personality: Personality,
        *,
        on_apply: Callable[[Manifest, Settings, Personality], None],
        prompt_view: str = "",
        on_preview=None,
    ) -> None:
        super().__init__(parent)
        self.title("Akira settings")
        self._requested_size = (theme.px(940), theme.px(760))
        self.geometry(f"{self._requested_size[0]}x{self._requested_size[1]}")
        self.transient(parent)
        theme.apply_window_chrome(self)
        # Not a ModalDialog, so it needs its own fit-to-content pass. Every tab
        # is measured, not just the visible one -- a notebook sizes to the
        # active page, so a wide tab can hide off-screen controls until the
        # moment someone clicks it.
        self.after_idle(self._fit_to_content)

        self.vault = Path(vault)
        self.manifest = manifest
        self.settings = settings
        self.personality = personality
        self._on_apply = on_apply
        self._prompt_view = prompt_view
        self._on_preview = on_preview

        # Snapshots for the unsaved-changes check. The personality panel
        # updates its preview live as sliders move, which reads as "applied" --
        # so closing without saving has to ask rather than silently discard.
        self._original_settings = settings.to_json()
        self._original_personality = personality.to_json()
        self._original_tier = manifest.trust_tier

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self._build_models_tab()
        self._build_prompt_tab()
        self._build_personality_tab()
        self._build_lock_tab()
        self._build_tripwire_tab()
        self._build_memory_tab()
        self._build_retention_tab()
        self._build_security_tab()
        self._build_plugins_tab()

        button_row(self, [("Save", self._save), ("Cancel", self._cancel)]).pack(side="bottom", fill="x")
        # The window's X must take the same route as Cancel, or closing that
        # way is a silent discard.
        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _fit_to_content(self) -> None:
        """Grow to the widest tab, then pin a minsize."""
        try:
            self.update_idletasks()
            need_w = self.winfo_reqwidth()
            need_h = self.winfo_reqheight()
            # Walk every tab: the notebook only requests space for the active
            # page, so the Models tab being 114px too wide is invisible while
            # Prompt is showing.
            current = self.notebook.select()
            for tab in self.notebook.tabs():
                self.notebook.select(tab)
                self.update_idletasks()
                need_w = max(need_w, self.winfo_reqwidth())
                need_h = max(need_h, self.winfo_reqheight())
            if current:
                self.notebook.select(current)

            # Floor is the requested size, not winfo_width(): an unmapped
            # window reports 1x1 and this would shrink instead of grow.
            floor_w, floor_h = self._requested_size
            max_w = self.winfo_screenwidth() - theme.px(80)
            max_h = self.winfo_screenheight() - theme.px(120)
            want_w = min(max(need_w, floor_w), max_w)
            want_h = min(max(need_h, floor_h), max_h)
            self.geometry(f"{want_w}x{want_h}")
            self._requested_size = (want_w, want_h)
            self.minsize(min(min(need_w, floor_w), max_w),
                         min(min(need_h, floor_h), max_h))
        except tk.TclError:
            pass

    # -- closing --------------------------------------------------------------

    def _pending_changes(self) -> list[str]:
        """Which sections differ from what was open when Settings launched."""
        changed: list[str] = []
        if self.personality.to_json() != self._original_personality:
            changed.append("personality")
        if self.tier_var.get() != self._original_tier:
            changed.append("trust tier")
        try:
            if self._collect() != self._original_settings:
                changed.append("settings")
        except (ValueError, TypeError):
            # A field currently holds something unparseable, which is itself an
            # edit the user has not saved.
            changed.append("settings")
        return changed

    def _cancel(self) -> None:
        changed = self._pending_changes()
        if changed and not messagebox.askokcancel(
            "Discard changes?",
            f"You have unsaved changes to: {', '.join(changed)}.\n\nClose without saving?",
            parent=self,
        ):
            return
        self.destroy()

    # -- helpers ------------------------------------------------------------

    def _tab(self, title: str) -> tk.Frame:
        frame = tk.Frame(self.notebook)
        self.notebook.add(frame, text=title)
        return frame

    @staticmethod
    def _field(parent: tk.Misc, row: int, label: str, value: str, width: int = 44) -> tk.Entry:
        tk.Label(parent, text=label, anchor="w", width=22).grid(row=row, column=0, sticky="w", pady=3)
        entry = tk.Entry(parent, width=width)
        entry.insert(0, value)
        entry.grid(row=row, column=1, sticky="we", pady=3)
        parent.columnconfigure(1, weight=1)
        return entry

    @staticmethod
    def _note(parent: tk.Misc, text: str) -> None:
        tk.Label(parent, text=text, wraplength=780, justify="left", fg=MUTED_FG, anchor="w").pack(
            anchor="w", padx=10, pady=(0, 8)
        )

    # -- models -------------------------------------------------------------

    def _build_models_tab(self) -> None:
        tab = self._tab("Models")
        grid = tk.Frame(tab)
        grid.pack(fill="x", padx=10, pady=10)

        models = self.settings.models
        self.main_path = self._field(grid, 0, "MAIN model (.gguf)", models.main_path)
        tk.Button(grid, text="Browse", command=lambda: self._browse(self.main_path)).grid(row=0, column=2, padx=4)
        self.auditor_path = self._field(grid, 1, "AUDITOR model (.gguf)", models.auditor_path)
        tk.Button(grid, text="Browse", command=lambda: self._browse(self.auditor_path)).grid(row=1, column=2, padx=4)

        self.main_ctx = self._field(grid, 2, "MAIN context length", str(models.main_ctx), width=12)
        self.auditor_ctx = self._field(grid, 3, "AUDITOR context length", str(models.auditor_ctx), width=12)
        self.temperature = self._field(grid, 4, "Temperature", str(models.temperature), width=12)
        self.top_p = self._field(grid, 5, "Top-p", str(models.top_p), width=12)
        self.max_tokens = self._field(grid, 6, "Max response tokens", str(models.max_tokens), width=12)
        self.gpu_layers = self._field(grid, 7, "GPU layers (-1 = all)", str(models.n_gpu_layers), width=12)

        tk.Label(grid, text="Model loading", anchor="w", width=22).grid(row=8, column=0, sticky="w", pady=3)
        self.loading_var = tk.StringVar(value=models.loading)
        loading_row = tk.Frame(grid)
        loading_row.grid(row=8, column=1, sticky="w")
        for mode in ModelSettings.VALID_LOADING:
            tk.Radiobutton(loading_row, text=mode, variable=self.loading_var, value=mode).pack(side="left")

        self._note(
            tab,
            "Sequential keeps one model resident at a time -- slower per turn, far less system RAM. "
            "llama.cpp maps the whole GGUF into host memory during load regardless of where the "
            "layers end up, so on a 16GB machine this is the setting that decides whether a large "
            "model is usable at all. Quantization is a property of the .gguf file itself; pick a "
            "Q4_K_M build when you download one.",
        )
        self._note(
            tab,
            "Pointing AUDITOR at the same file as MAIN is supported and loads it once -- the auditor "
            "then costs no extra memory and reads MAIN's output in exactly the same dialect. "
            "GPU layers: -1 offloads everything, which only fits if the model is smaller than your "
            "VRAM. For a model larger than the card, set a number instead and lower it until the "
            "load leaves a few hundred MB of VRAM free for the KV cache.",
        )

        grid_context = tk.Frame(tab)
        grid_context.pack(fill="x", padx=10, pady=6)
        context = self.settings.context
        self.total_budget = self._field(grid_context, 0, "Context budget (tokens)", str(context.total_budget_tokens), width=12)
        self.reserve = self._field(grid_context, 1, "Reserved for response", str(context.reserve_for_response), width=12)
        self.max_chunks = self._field(grid_context, 2, "Max retrieved chunks", str(context.max_retrieved_chunks), width=12)

    def _browse(self, entry: tk.Entry) -> None:
        path = filedialog.askopenfilename(
            title="Select a GGUF model", filetypes=[("GGUF models", "*.gguf"), ("All files", "*.*")], parent=self
        )
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    # -- prompt -------------------------------------------------------------

    def _build_prompt_tab(self) -> None:
        tab = self._tab("Prompt")
        tk.Label(tab, text="System prompt (entirely yours)", anchor="w").pack(anchor="w", padx=10, pady=(10, 2))
        self.system_prompt = tk.Text(tab, wrap="word", height=12, padx=6, pady=6)
        self.system_prompt.insert("1.0", self.settings.system_prompt)
        self.system_prompt.pack(fill="both", expand=False, padx=10)
        self._note(
            tab,
            "Akira adds nothing to this but the lock directive, the unlocked-topic list, and your "
            "active personality bands. There is no vendor preamble, no default persona, and no "
            "behavioural boilerplate you did not write.",
        )

        tk.Label(tab, text="Last assembled prompt", anchor="w").pack(anchor="w", padx=10, pady=(8, 2))
        viewer = read_only_text(
            tab,
            self._prompt_view or "Send a message to see exactly what MAIN received.",
            height=18,
        )
        viewer.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    # -- personality --------------------------------------------------------

    def _build_personality_tab(self) -> None:
        tab = self._tab("Personality")
        self.personality_panel = PersonalityPanel(
            tab,
            self.personality,
            on_change=self._personality_changed,
            on_preview=self._on_preview,
        )
        self.personality_panel.pack(fill="both", expand=True)

    def _personality_changed(self, personality: Personality) -> None:
        self.personality = personality

    # -- lock layers --------------------------------------------------------

    def _build_lock_tab(self) -> None:
        tab = self._tab("Lock layers")
        layers = self.settings.lock_layers

        self.layer_vars = {
            "directive": tk.BooleanVar(value=layers.directive),
            "retrieval": tk.BooleanVar(value=layers.retrieval),
            "tripwires": tk.BooleanVar(value=layers.tripwires),
            "auditor": tk.BooleanVar(value=layers.auditor),
        }
        descriptions = {
            "directive": "Layer 2 - tells MAIN what it may discuss. The weakest layer; it leaks.",
            "retrieval": "Layer 3 - hides locked-topic notes from search, memory notes included.",
            "tripwires": "Layer 4 - deterministic pattern checks over MAIN's output.",
            "auditor": "Layer 5 - a second model reads the draft and returns a verdict.",
        }

        for name, var in self.layer_vars.items():
            row = tk.Frame(tab)
            row.pack(fill="x", padx=10, pady=(8, 0))
            tk.Checkbutton(row, text=name, variable=var, command=self._update_layer_warning).pack(side="left")
            tk.Label(row, text=descriptions[name], fg=MUTED_FG, anchor="w").pack(side="left", padx=8)

        self.layer_warning = tk.Label(tab, text="", wraplength=780, justify="left", anchor="w",
                                      bg=WARNING_BG, padx=8, pady=6)
        self.layer_warning.pack(fill="x", padx=10, pady=10)
        self._update_layer_warning()

        tk.Label(tab, text="Auditor strictness", anchor="w").pack(anchor="w", padx=10, pady=(10, 2))
        self.strictness_var = tk.StringVar(value=self.settings.auditor.strictness)
        row = tk.Frame(tab)
        row.pack(anchor="w", padx=10)
        for level in AuditorSettings.VALID_STRICTNESS:
            tk.Radiobutton(row, text=level, variable=self.strictness_var, value=level).pack(side="left")
        self._note(
            tab,
            "Strictness widens what counts as a clean PASS. No level makes the auditor fail open: a "
            "missing, malformed, contradictory or late verdict always blocks.",
        )

        grid = tk.Frame(tab)
        grid.pack(fill="x", padx=10)
        self.auditor_timeout = self._field(grid, 0, "Auditor timeout (s)", str(self.settings.auditor.timeout_s), width=12)
        self._note(
            tab,
            "Scale the timeout to your model's speed. A missed deadline blocks the response -- "
            "correct behaviour, but on a slow model a too-short deadline turns ordinary work into "
            "constant blocks. A 24B at ~2 tokens/sec needs several minutes to audit a long "
            "unlock demonstration; an 8B needs seconds.",
        )

    def _update_layer_warning(self) -> None:
        off = [name for name, var in self.layer_vars.items() if not var.get()]
        if off:
            self.layer_warning.configure(
                text=(
                    f"WARNING: {', '.join(off)} disabled. Locked knowledge may reach you unfiltered. "
                    "The layers fail in different ways on purpose -- the directive and the auditor are "
                    "both language models and fail together; the tripwires are the only check with no "
                    "model in it."
                ),
                bg=WARNING_BG,
            )
        else:
            self.layer_warning.configure(text="All five layers active.", bg=self.cget("bg"))

    # -- tripwires ----------------------------------------------------------

    def _build_tripwire_tab(self) -> None:
        tab = self._tab("Tripwires")
        self._tripwires = TripwireSet.load(self.vault)

        body = tk.Frame(tab)
        body.pack(fill="both", expand=True, padx=10, pady=10)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Topics", anchor="w").pack(anchor="w")
        self.tripwire_list = tk.Listbox(left, width=26, height=18, exportselection=False)
        self.tripwire_list.pack(fill="y", expand=True)
        self.tripwire_list.bind("<<ListboxSelect>>", lambda _e: self._load_tripwire())
        tk.Button(left, text="Add topic...", command=self._add_tripwire_topic).pack(fill="x", pady=4)

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        tk.Label(right, text="Keywords (one per line, matched on word boundaries)", anchor="w").pack(anchor="w")
        self.keyword_box = tk.Text(right, height=8, wrap="none", padx=4, pady=4)
        self.keyword_box.pack(fill="both", expand=True)
        tk.Label(right, text="Regex patterns (one per line)", anchor="w").pack(anchor="w", pady=(8, 0))
        self.pattern_box = tk.Text(right, height=8, wrap="none", padx=4, pady=4)
        self.pattern_box.pack(fill="both", expand=True)
        tk.Button(right, text="Save patterns for this topic", command=self._save_tripwire).pack(anchor="e", pady=4)

        self._note(
            tab,
            "Tripwires fire only for locked topics. They produce false positives by design -- a list "
            "tight enough never to misfire would be loose enough to miss the paraphrase. Blocked "
            "responses show which rule fired on which text.",
        )
        self._refresh_tripwire_list()

    def _refresh_tripwire_list(self) -> None:
        self.tripwire_list.delete(0, "end")
        locked = [t for t in sorted(self._tripwires.by_topic) if not self.manifest.is_unlocked(t)]
        unlocked = [t for t in sorted(self._tripwires.by_topic) if self.manifest.is_unlocked(t)]
        for topic in locked:
            self.tripwire_list.insert("end", topic)
        for topic in unlocked:
            self.tripwire_list.insert("end", f"{topic}  (unlocked - inert)")

    def _selected_tripwire_topic(self) -> str:
        selection = self.tripwire_list.curselection()
        if not selection:
            return ""
        return self.tripwire_list.get(selection[0]).split("  ")[0]

    def _load_tripwire(self) -> None:
        topic = self._selected_tripwire_topic()
        rules = self._tripwires.by_topic.get(topic)
        self.keyword_box.delete("1.0", "end")
        self.pattern_box.delete("1.0", "end")
        if rules:
            self.keyword_box.insert("1.0", "\n".join(rules.keywords))
            self.pattern_box.insert("1.0", "\n".join(rules.patterns))

    def _add_tripwire_topic(self) -> None:
        from tkinter import simpledialog

        from ..schemas import SchemaError, normalize_topic

        raw = simpledialog.askstring("Tripwire topic", "Topic id:", parent=self)
        if not raw:
            return
        try:
            topic = normalize_topic(raw)
        except SchemaError as exc:
            messagebox.showerror("Topic", str(exc), parent=self)
            return
        self._tripwires.by_topic[topic] = TopicTripwires(topic=topic)
        TripwireSet.save_topic(self.vault, self._tripwires.by_topic[topic])
        self._refresh_tripwire_list()

    def _save_tripwire(self) -> None:
        topic = self._selected_tripwire_topic()
        if not topic:
            messagebox.showinfo("Tripwires", "Select a topic first.", parent=self)
            return
        keywords = tuple(line.strip() for line in self.keyword_box.get("1.0", "end-1c").splitlines() if line.strip())
        patterns = tuple(line.strip() for line in self.pattern_box.get("1.0", "end-1c").splitlines() if line.strip())

        for pattern in patterns:
            error = validate_pattern(pattern)
            if error:
                messagebox.showerror("Pattern rejected", f"{pattern!r}\n\n{error}", parent=self)
                return

        rules = TopicTripwires(topic=topic, keywords=keywords, patterns=patterns)
        TripwireSet.save_topic(self.vault, rules)
        self._tripwires.by_topic[topic] = rules
        messagebox.showinfo("Tripwires", f"Saved {len(keywords) + len(patterns)} rule(s) for {topic}.", parent=self)

    # -- memory -------------------------------------------------------------

    def _build_memory_tab(self) -> None:
        tab = self._tab("Memory")
        memory = self.settings.memory

        self.memory_enabled = tk.BooleanVar(value=memory.enabled)
        tk.Checkbutton(tab, text="Enable session memory", variable=self.memory_enabled).pack(anchor="w", padx=10, pady=(10, 0))
        self.consolidate_var = tk.BooleanVar(value=memory.consolidate_on_session_end)
        tk.Checkbutton(tab, text="Consolidate at session end", variable=self.consolidate_var).pack(anchor="w", padx=10)
        self.auto_confirm = tk.BooleanVar(value=memory.auto_confirm)
        tk.Checkbutton(tab, text="Confirm consolidation automatically (not recommended)",
                       variable=self.auto_confirm).pack(anchor="w", padx=10)
        self.delete_now = tk.BooleanVar(value=memory.delete_transcript_immediately)
        tk.Checkbutton(tab, text="Delete transcripts immediately instead of holding them",
                       variable=self.delete_now).pack(anchor="w", padx=10)
        self.keep_transcripts = tk.BooleanVar(value=memory.keep_transcripts)
        tk.Checkbutton(tab, text="Keep transcripts permanently, searchable under Session history",
                       variable=self.keep_transcripts).pack(anchor="w", padx=10)

        grid = tk.Frame(tab)
        grid.pack(fill="x", padx=10, pady=8)
        self.holding_days = self._field(grid, 0, "Transcript holding (days)", str(memory.holding_days), width=12)

        self._note(
            tab,
            "Consolidation is done by an 8B model and will sometimes produce lossy or wrong notes. "
            "The transcript is kept in memory/holding until you confirm, so the source is still "
            "there when you notice. Deleting it is irreversible.\n\n"
            "Keeping transcripts moves them to memory/archive instead of deleting them, where "
            "Session history can search them. It is off by default because the safe default for "
            "a local assistant is not to accumulate a record of everything you ever said. If both "
            "'delete immediately' and 'keep' are ticked, delete wins.",
        )

    # -- retention ------------------------------------------------------------

    def _build_retention_tab(self) -> None:
        tab = self._tab("Review")
        retention = self.settings.retention

        self.retention_enabled = tk.BooleanVar(value=retention.enabled)
        tk.Checkbutton(tab, text="Remind me to re-demonstrate topics that have gone stale",
                       variable=self.retention_enabled).pack(anchor="w", padx=10, pady=(10, 0))
        self.retention_relock = tk.BooleanVar(value=retention.auto_relock)
        tk.Checkbutton(tab, text="Re-lock topics automatically once they are well overdue",
                       variable=self.retention_relock).pack(anchor="w", padx=10)

        grid = tk.Frame(tab)
        grid.pack(fill="x", padx=10, pady=8)
        self.review_after_days = self._field(
            grid, 0, "Review after (days)", str(retention.review_after_days), width=12
        )
        self.retention_grace = self._field(
            grid, 1, "Grace before re-lock (days)", str(retention.grace_days), width=12
        )

        self._note(
            tab,
            "A topic unlocked once stays unlocked forever unless something asks whether "
            "it held. Reviewing runs the same demonstration again against your notes as "
            "they stand now; passing it resets the clock and grants nothing new, and "
            "failing it costs nothing -- the topic stays unlocked and stays due.\n\n"
            "Automatic re-locking is off by default. It waits for the review interval "
            "*and* the grace period, so falling due and losing access never happen on "
            "the same day. Set the interval to 0 to switch the whole feature off.",
        )

    # -- security -----------------------------------------------------------

    def _build_security_tab(self) -> None:
        tab = self._tab("Security")

        tk.Label(tab, text="Trust tier", anchor="w", font=(theme.font_family(), 10, "bold")).pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        self.tier_var = tk.IntVar(value=self.manifest.trust_tier)
        for tier, caps in sorted(TIERS.items()):
            row = tk.Frame(tab)
            row.pack(fill="x", padx=10)
            tk.Radiobutton(row, text=caps.label, variable=self.tier_var, value=tier).pack(side="left")
        self._note(
            tab,
            "Tiers gate the model, not Akira. No tier grants network access -- that is enforced "
            "structurally, by no networking module existing anywhere in the inference or "
            "skill-execution path. Changing this asks for your PIN.",
        )

        tk.Label(tab, text="Skill language", anchor="w").pack(anchor="w", padx=10, pady=(8, 2))
        self.skill_language = tk.Entry(tab, width=20)
        self.skill_language.insert(0, self.settings.skill_language)
        self.skill_language.pack(anchor="w", padx=10)

        self.logging_var = tk.BooleanVar(value=self.settings.logging_enabled)
        tk.Checkbutton(
            tab,
            text="Write a local audit log of lock decisions (off by default)",
            variable=self.logging_var,
        ).pack(anchor="w", padx=10, pady=(10, 0))
        self._note(
            tab,
            f"Appends one line per gate decision to {store.protege_dir(self.vault) / 'protege.log'} -- "
            "which layer fired, on which topic, how long it took. Never the text involved: a log "
            "holding blocked drafts would be a plaintext copy of exactly what the lock system "
            "withheld, sitting in the vault.",
        )

        tk.Label(
            tab,
            text="The runtime network guard is always on and has no setting. It installs before "
                 "anything else is imported.",
            wraplength=780, justify="left", fg=MUTED_FG, anchor="w",
        ).pack(anchor="w", padx=10)

        tk.Button(tab, text="Change PIN...", command=self._change_pin).pack(anchor="w", padx=10, pady=10)

        tk.Label(tab, text=f"Vault: {self.vault}", anchor="w", fg=MUTED_FG).pack(anchor="w", padx=10)
        tk.Label(
            tab,
            text=f"Projects: {self.vault / 'projects'}   (switch projects from the status line; "
                 "point Akira at a different vault with --vault)",
            anchor="w", fg=MUTED_FG, wraplength=780, justify="left",
        ).pack(anchor="w", padx=10)
        tk.Label(
            tab,
            text=(
                "The PIN is an access convenience, not encryption. Your vault is plain markdown on "
                "disk. Use full-disk encryption, and add an OS firewall rule denying this binary "
                "egress -- network-level blocking is stronger than any guarantee this application "
                "can make about itself."
            ),
            wraplength=780, justify="left", fg=DANGER_FG, anchor="w",
        ).pack(anchor="w", padx=10, pady=10)

    # -- plugins ------------------------------------------------------------

    def _build_plugins_tab(self) -> None:
        tab = self._tab("Plugins")
        self._enabled_plugins = dict(self.settings.enabled_plugins)

        self._note(
            tab,
            f"Plugin files in {plugin_dir(self.vault)}. Enabling one runs its code -- verify_offline "
            "cannot vouch for a file that did not exist when it ran. Approval binds to the file's "
            "SHA-256, so editing a plugin disables it until you approve it again.",
        )

        body = tk.Frame(tab)
        body.pack(fill="both", expand=True, padx=10)
        self.plugin_list = tk.Listbox(body, height=12, exportselection=False)
        self.plugin_list.pack(side="left", fill="both", expand=True)
        self.plugin_list.bind("<<ListboxSelect>>", lambda _e: self._show_plugin())

        self.plugin_detail = read_only_text(body, "", height=12)
        self.plugin_detail.pack(side="left", fill="both", expand=True, padx=(10, 0))

        row = tk.Frame(tab)
        row.pack(fill="x", padx=10, pady=6)
        tk.Button(row, text="Enable / re-approve", command=self._enable_plugin).pack(side="left")
        tk.Button(row, text="Disable", command=self._disable_plugin).pack(side="left", padx=4)
        tk.Button(row, text="Write example plugin", command=self._write_example).pack(side="right")

        self._refresh_plugins()

    def _refresh_plugins(self) -> None:
        self._discovered = discover_plugins(self.vault)
        self.plugin_list.delete(0, "end")
        for found in self._discovered:
            approved = self._enabled_plugins.get(found.name)
            if approved is None:
                state = "disabled"
            elif approved != found.sha256:
                state = "CHANGED"
            else:
                state = "enabled"
            self.plugin_list.insert("end", f"[{state}] {found.name}")
        if not self._discovered:
            set_text(self.plugin_detail, "No plugin files found.")

    def _selected_plugin(self):
        selection = self.plugin_list.curselection()
        if not selection:
            return None
        return self._discovered[selection[0]]

    def _show_plugin(self) -> None:
        found = self._selected_plugin()
        if found is None:
            return
        approved = self._enabled_plugins.get(found.name)
        lines = [f"{found.name}", f"on disk:  {found.sha256}"]
        lines.append(f"approved: {approved}" if approved else "approved: (not enabled)")
        lines.append("-" * 60)
        try:
            lines.append(found.path.read_text(encoding="utf-8"))
        except OSError as exc:
            lines.append(f"(cannot read: {exc})")
        set_text(self.plugin_detail, "\n".join(lines))

    def _enable_plugin(self) -> None:
        found = self._selected_plugin()
        if found is None:
            messagebox.showinfo("Plugins", "Select a plugin first.", parent=self)
            return
        if not messagebox.askokcancel(
            "Enable plugin",
            f"Enable {found.name}?\n\nSHA-256: {found.sha256[:32]}...\n\n"
            "This runs the plugin's code at startup. Read it first.",
            parent=self,
        ):
            return
        self._enabled_plugins[found.name] = found.sha256
        self._refresh_plugins()

    def _disable_plugin(self) -> None:
        found = self._selected_plugin()
        if found is None:
            return
        self._enabled_plugins.pop(found.name, None)
        self._refresh_plugins()

    def _write_example(self) -> None:
        target = plugin_dir(self.vault) / "example_word_count.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not messagebox.askokcancel(
            "Overwrite", f"{target.name} exists. Overwrite?", parent=self
        ):
            return
        target.write_text(EXAMPLE_PLUGIN, encoding="utf-8")
        self._refresh_plugins()
        messagebox.showinfo("Plugins", f"Wrote {target}. It is disabled until you enable it.", parent=self)

    def _change_pin(self) -> None:
        if not self.manifest.pin.is_set:
            messagebox.showinfo("PIN", "No PIN is set yet. Restart Akira to set one.", parent=self)
            return
        new_hash = PinChangeDialog(self, self.manifest.pin.hash).show()
        if new_hash:
            self.manifest = self.manifest.with_pin(new_hash)
            messagebox.showinfo("PIN", "PIN changed.", parent=self)

    # -- saving -------------------------------------------------------------

    def _save(self) -> None:
        try:
            payload = self._collect()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Invalid setting", str(exc), parent=self)
            return

        try:
            new_settings = Settings.from_json(payload)
        except Exception as exc:  # noqa: BLE001 - SchemaError and friends
            messagebox.showerror("Invalid setting", str(exc), parent=self)
            return

        manifest = self.manifest
        if self.tier_var.get() != manifest.trust_tier:
            target = capabilities(self.tier_var.get())
            if not confirm_pin(self, manifest.pin.hash, f"Confirm your PIN to switch to {target.label}"):
                messagebox.showerror("Trust tier", "PIN not confirmed; the tier was not changed.", parent=self)
                return
            manifest = manifest.with_trust_tier(self.tier_var.get())

        if new_settings.lock_layers.any_disabled and not messagebox.askokcancel(
            "Lock layers disabled",
            f"You are disabling: {', '.join(new_settings.lock_layers.disabled_names)}.\n\n"
            "Locked knowledge may reach you unfiltered. Continue?",
            parent=self,
        ):
            return

        store.save_settings(self.vault, new_settings)
        store.save_manifest(self.vault, manifest)
        store.save_personality(self.vault, self.personality)

        self._on_apply(manifest, new_settings, self.personality)
        self.destroy()

    def _collect(self) -> dict:
        def as_int(entry: tk.Entry, label: str) -> int:
            try:
                return int(entry.get().strip())
            except ValueError as exc:
                raise ValueError(f"{label} must be a whole number") from exc

        def as_float(entry: tk.Entry, label: str) -> float:
            try:
                return float(entry.get().strip())
            except ValueError as exc:
                raise ValueError(f"{label} must be a number") from exc

        base = self.settings.to_json()
        base["models"] = {
            **base["models"],
            "main_path": self.main_path.get().strip(),
            "auditor_path": self.auditor_path.get().strip(),
            "main_ctx": as_int(self.main_ctx, "MAIN context length"),
            "auditor_ctx": as_int(self.auditor_ctx, "AUDITOR context length"),
            "temperature": as_float(self.temperature, "Temperature"),
            "top_p": as_float(self.top_p, "Top-p"),
            "max_tokens": as_int(self.max_tokens, "Max response tokens"),
            "n_gpu_layers": as_int(self.gpu_layers, "GPU layers"),
            "loading": self.loading_var.get(),
        }
        base["context"] = {
            **base["context"],
            "total_budget_tokens": as_int(self.total_budget, "Context budget"),
            "reserve_for_response": as_int(self.reserve, "Reserved for response"),
            "max_retrieved_chunks": as_int(self.max_chunks, "Max retrieved chunks"),
        }
        base["lock_layers"] = {name: var.get() for name, var in self.layer_vars.items()}
        base["auditor"] = {
            **base["auditor"],
            "strictness": self.strictness_var.get(),
            "timeout_s": as_float(self.auditor_timeout, "Auditor timeout"),
        }
        base["memory"] = {
            **base["memory"],
            "enabled": self.memory_enabled.get(),
            "consolidate_on_session_end": self.consolidate_var.get(),
            "auto_confirm": self.auto_confirm.get(),
            "delete_transcript_immediately": self.delete_now.get(),
            "keep_transcripts": self.keep_transcripts.get(),
            "holding_days": as_int(self.holding_days, "Transcript holding"),
        }
        base["retention"] = {
            **base.get("retention", {}),
            "enabled": self.retention_enabled.get(),
            "auto_relock": self.retention_relock.get(),
            "review_after_days": as_int(self.review_after_days, "Review after"),
            "grace_days": as_int(self.retention_grace, "Grace before re-lock"),
        }
        base["system_prompt"] = self.system_prompt.get("1.0", "end-1c")
        base["skill_language"] = self.skill_language.get().strip() or "python"
        base["logging_enabled"] = self.logging_var.get()
        base["enabled_plugins"] = dict(self._enabled_plugins)
        return base
