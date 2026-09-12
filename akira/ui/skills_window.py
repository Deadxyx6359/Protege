"""Skills: authoring, approval, and running.

The approval control is the whole point of this window, so it is deliberately
not a one-click affair. Approving binds to the file's SHA-256 and the digest is
shown next to it, because "approved" and "approved for the version I actually
read" are different claims and only the second one is worth anything.

Nothing here runs a skill without an explicit Run press on an approved,
digest-matching file at trust tier 2 or above.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from ..lock.pipeline import OutputGate
from ..models import ModelManager
from ..schemas import Manifest, Settings
from ..security.paths import PathPolicy, capabilities
from ..skills.author import SkillAuthor, SkillAuthoringError
from ..skills.sandbox import approve, digest_of, revoke, run_skill
from . import theme
from .widgets import DANGER_FG, MUTED_FG, ModalDialog, button_row, read_only_text, set_text

POLL_MS = 60


class SkillsWindow(ModalDialog):
    """Returns the (possibly updated) manifest."""

    def __init__(
        self,
        parent: tk.Misc,
        vault: Path,
        project: str,
        manifest: Manifest,
        settings: Settings,
        manager: ModelManager,
        gate: OutputGate,
    ) -> None:
        super().__init__(parent, "Skills", width=900, height=700)
        self.vault = Path(vault)
        self.manifest = manifest
        self.settings = settings
        self.author = SkillAuthor(vault, project, manifest, settings, manager, gate)
        self.policy = PathPolicy.build(vault, trust_tier=manifest.trust_tier)
        self._events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self._busy = False
        self._pending = None

        caps = capabilities(manifest.trust_tier)
        tk.Label(
            self,
            text=(
                f"Skills are written to disk and never run on their own. Running one needs explicit "
                f"approval bound to the file's exact contents, plus trust tier 2. "
                f"You are at {caps.label}."
            ),
            wraplength=860, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        self._build_author_row()
        self._build_body()

        button_row(
            self,
            [
                ("Close", self._close),
                ("Run", self._run),
                ("Revoke", self._revoke),
                ("Approve", self._approve),
            ],
        ).pack(side="bottom", fill="x")

        self._refresh()
        self.after(POLL_MS, self._drain)

    # -- construction -------------------------------------------------------

    def _build_author_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill="x", padx=12, pady=4)
        tk.Label(row, text="New skill for", anchor="w").pack(side="left")

        topics = self.manifest.unlocked_topics
        self.topic_var = tk.StringVar(value=topics[0] if topics else "")
        if topics:
            tk.OptionMenu(row, self.topic_var, *topics).pack(side="left", padx=4)
        else:
            tk.Label(row, text="(no unlocked topics)", fg=MUTED_FG).pack(side="left", padx=4)

        self.description = tk.Entry(row)
        self.description.pack(side="left", fill="x", expand=True, padx=4)
        self.author_button = tk.Button(row, text="Author", width=10, command=self._author)
        self.author_button.pack(side="left")
        tk.Button(row, text="Library...", width=10, command=self._show_library).pack(
            side="left", padx=(4, 0)
        )

        tk.Label(
            self,
            text="Skills can only be authored for unlocked topics -- a skill is durable, executable "
                 "knowledge, and writing one for a locked topic would record what the model is not "
                 "supposed to know in a form that later runs.",
            wraplength=860, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(0, 6))

    def _build_body(self) -> None:
        body = tk.Frame(self)
        body.pack(fill="both", expand=True, padx=12)

        left = tk.Frame(body)
        left.pack(side="left", fill="y")
        tk.Label(left, text="Skills in this project", anchor="w").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=40, height=14, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._show_selected())

        right = tk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.detail = read_only_text(right, "", height=14)
        self.detail.pack(fill="both", expand=True)

        # Arguments. Every library skill is documented as `something.py <file>`,
        # so without this the Run button could only ever point a skill at itself.
        argv = tk.Frame(self)
        argv.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(argv, text="Arguments", anchor="w", width=10).pack(side="left")
        self.args_entry = tk.Entry(argv)
        self.args_entry.pack(side="left", fill="x", expand=True)
        self.args_entry.bind("<Return>", lambda _e: self._run())
        tk.Button(argv, text="File...", width=8, command=self._add_file_arg).pack(
            side="left", padx=(4, 0)
        )

        self.usage_label = tk.Label(
            self, text="", anchor="w", fg=MUTED_FG, justify="left",
            font=theme.ui_font(size=theme.UI_SIZE - 1),
        )
        self.usage_label.pack(fill="x", padx=12, pady=(2, 0))

        self.status = tk.Label(self, text="", anchor="w", fg=MUTED_FG, wraplength=860, justify="left")
        self.status.pack(fill="x", padx=12, pady=4)

        tk.Label(self, text="Output", anchor="w").pack(anchor="w", padx=12)
        self.output = read_only_text(self, "", height=8)
        self.output.pack(fill="x", padx=12, pady=(0, 6))

    # -- listing ------------------------------------------------------------

    def _skills(self) -> list[Path]:
        return self.author.list_skills()

    def _rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.policy.vault_root).as_posix()

    def _state_of(self, path: Path) -> str:
        approval = self.manifest.skill_approval(self._rel(path))
        if approval is None:
            return "unapproved"
        try:
            if approval.sha256 != digest_of(path):
                return "CHANGED"
        except OSError:
            return "unreadable"
        if approval.topic and not self.manifest.is_unlocked(approval.topic):
            return "topic locked"
        return "approved"

    def _refresh(self) -> None:
        self.listbox.delete(0, "end")
        self._paths = self._skills()
        for path in self._paths:
            self.listbox.insert("end", f"[{self._state_of(path)}] {path.name}")
        if not self._paths:
            set_text(self.detail, "No skills yet. Describe one above and press Author.")

    def _selected(self) -> Path | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        return self._paths[selection[0]]

    def _show_selected(self) -> None:
        path = self._selected()
        if path is None:
            return
        state = self._state_of(path)
        approval = self.manifest.skill_approval(self._rel(path))
        header = [f"{path.name}   [{state}]", f"on disk:  {digest_of(path)}"]
        if approval:
            header.append(f"approved: {approval.sha256}")
            header.append(f"at:       {approval.approved_at}   topic: {approval.topic or '(none)'}")
        if state == "CHANGED":
            header.append("")
            header.append(
                "This file has been edited since approval. Approval covers exact content, so it is "
                "void until you read the new version and approve it again."
            )
        header.append("-" * 70)
        self._show_usage(path)
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            source = f"(cannot read: {exc})"
        set_text(self.detail, "\n".join(header) + "\n" + source)

    def _show_usage(self, path: Path) -> None:
        """Surface the skill's own usage line next to the argument box.

        Every skill's docstring opens with `usage: python name.py <file>`. Making
        the user open the source to find out what to type would be a poor joke
        in a program whose whole premise is that it explains itself.
        """
        import re

        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            self.usage_label.configure(text="")
            return
        match = re.search(r"^usage:\s*(.+)$", source, re.M)
        self.usage_label.configure(
            text=f"usage: {match.group(1).strip()}" if match
            else "this skill documents no arguments"
        )

    def _show_library(self) -> None:
        """Install a ready-made skill from the shipped library."""
        from .skill_library_dialog import SkillLibraryDialog

        installed = SkillLibraryDialog(self, self.author.project.skills_dir).show()
        if installed:
            self.status.configure(
                text=f"installed {len(installed)} skill(s) -- unapproved until you approve them",
                fg=MUTED_FG,
            )
            self._refresh()

    # -- authoring ----------------------------------------------------------

    def _author(self) -> None:
        if self._busy:
            return
        topic = self.topic_var.get().strip()
        description = self.description.get().strip()
        if not topic:
            messagebox.showerror("Skills", "Unlock a topic before authoring a skill.", parent=self)
            return
        if not description:
            messagebox.showerror("Skills", "Describe what the skill should do.", parent=self)
            return

        self._busy = True
        self.author_button.configure(state="disabled")
        self.status.configure(text="authoring...", fg=MUTED_FG)
        threading.Thread(target=self._author_worker, args=(topic, description), daemon=True).start()

    def _author_worker(self, topic: str, description: str) -> None:
        try:
            self._events.put(("authored", self.author.author(topic, description)))
        except SkillAuthoringError as exc:
            self._events.put(("error", str(exc)))
        except Exception as exc:  # noqa: BLE001
            self._events.put(("error", f"{type(exc).__name__}: {exc}"))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "authored":
                    self._show_authored(payload)
                elif kind == "error":
                    self._busy = False
                    self.author_button.configure(state="normal")
                    self.status.configure(text=payload, fg=DANGER_FG)
                elif kind == "ran":
                    self._show_run(payload)
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain)

    def _show_authored(self, skill) -> None:
        self._busy = False
        self.author_button.configure(state="normal")
        if skill.blocked:
            self.status.configure(text=f"not saved -- {skill.block_reason}", fg=DANGER_FG)
            set_text(self.detail, f"BLOCKED\n\n{skill.block_reason}\n\n{'-' * 70}\n{skill.source}")
            return
        try:
            path = self.author.save(skill, self.policy)
        except SkillAuthoringError as exc:
            self.status.configure(text=str(exc), fg=DANGER_FG)
            return
        self.status.configure(
            text=f"saved {path.name} -- unapproved. Read it, then press Approve to allow it to run.",
            fg=MUTED_FG,
        )
        self._refresh()

    # -- approval and running -----------------------------------------------

    def _approve(self) -> None:
        path = self._selected()
        if path is None:
            messagebox.showinfo("Skills", "Select a skill first.", parent=self)
            return
        digest = digest_of(path)
        if not messagebox.askokcancel(
            "Approve skill",
            f"Approve {path.name} to run?\n\n"
            f"SHA-256: {digest[:32]}...\n\n"
            "This approves exactly this content. Editing the file revokes it.\n\n"
            "A Python subprocess is not a security boundary -- treat this like running a script "
            "someone sent you.",
            parent=self,
        ):
            return
        approval_topic = self.topic_var.get().strip()
        self.manifest = approve(self.manifest, self.policy, path, topic=approval_topic)
        self.result = self.manifest
        self.status.configure(text=f"approved {path.name}", fg=MUTED_FG)
        self._refresh()
        self._show_selected()

    def _revoke(self) -> None:
        path = self._selected()
        if path is None:
            messagebox.showinfo("Skills", "Select a skill first.", parent=self)
            return
        self.manifest = revoke(self.manifest, self.policy, path)
        self.result = self.manifest
        self.status.configure(text=f"revoked {path.name}", fg=MUTED_FG)
        self._refresh()

    def _run(self) -> None:
        path = self._selected()
        if path is None:
            messagebox.showinfo("Skills", "Select a skill first.", parent=self)
            return
        if self._busy:
            return
        self._busy = True
        set_text(self.output, "running...")
        args = self._args()
        threading.Thread(target=self._run_worker, args=(path, args), daemon=True).start()

    def _args(self) -> list[str]:
        """Split the argument box, honouring quotes.

        `shlex` in POSIX mode eats Windows backslashes, so a pasted path like
        `C:\\Users\\me\\notes.md` would arrive as `C:Usersmenotes.md` -- a file
        not found error with no visible cause. `posix=False` keeps separators
        and still handles quoted paths with spaces.
        """
        import shlex

        text = self.args_entry.get().strip()
        if not text:
            return []
        try:
            return [part.strip('"') for part in shlex.split(text, posix=False)]
        except ValueError:
            return text.split()

    def _add_file_arg(self) -> None:
        chosen = filedialog.askopenfilename(title="Argument for this skill", parent=self)
        if not chosen:
            return
        existing = self.args_entry.get().strip()
        quoted = f'"{chosen}"' if " " in chosen else chosen
        self.args_entry.delete(0, "end")
        self.args_entry.insert(0, f"{existing} {quoted}".strip())

    def _run_worker(self, path: Path, args: list[str]) -> None:
        # `run_skill` never raises; every failure comes back as a SkillRun.
        self._events.put(("ran", run_skill(self.manifest, self.policy, path, args=args)))

    def _show_run(self, run) -> None:
        self._busy = False
        parts = [run.summary()]
        if run.stdout:
            parts.append(f"--- stdout ---\n{run.stdout}")
        if run.stderr:
            parts.append(f"--- stderr ---\n{run.stderr}")
        set_text(self.output, "\n\n".join(parts))
        self.status.configure(text=run.summary(), fg=MUTED_FG if run.ok else DANGER_FG)

    def _close(self) -> None:
        self.result = self.manifest
        self.destroy()

    def on_cancel(self) -> None:
        self._close()
