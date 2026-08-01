"""The personality editor.

A slider per trait, showing the band prose rather than the number. Profiles are
named sets of slider positions. Custom traits are authored in full by the
user -- the application cannot invent band descriptions for a trait it has
never seen, and generating plausible-sounding ones would be worse than asking.

Live preview regenerates the last response under the current settings without
committing them. The brief flags this as how the sliders actually get
calibrated, so it is a button on this panel rather than buried elsewhere.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from typing import Any, Callable

from ..personality.prompt import build_personality_prompt
from ..schemas import (
    BAND_COUNT,
    TRAIT_ID_RE,
    Personality,
    PersonalityProfile,
    SchemaError,
    Trait,
)
from .widgets import DANGER_FG, MUTED_FG, LabeledSlider, ModalDialog, ScrollableFrame, button_row, read_only_text, set_text

POLL_MS = 60


class NewTraitDialog(ModalDialog):
    """Collects an id, a label, and all five band descriptions.

    Every band is required. An empty band would contribute nothing whenever the
    slider landed on it, which reads as the trait silently not working.
    """

    BAND_RANGES = ("0-20", "21-40", "41-60 (neutral)", "61-80", "81-100")

    def __init__(self, parent: tk.Misc, existing_ids: tuple[str, ...], trait: Trait | None = None) -> None:
        super().__init__(parent, "Trait", width=720, height=620)
        self.existing_ids = existing_ids
        self.editing = trait

        tk.Label(
            self,
            text=(
                "You write the band descriptions. Protege cannot generate meaningful ones for a "
                "trait it has never seen. Phrase each as an instruction describing observable "
                "behaviour -- a small model follows 'States positions plainly' far more reliably "
                "than 'quite direct'."
            ),
            wraplength=680, justify="left", fg=MUTED_FG,
        ).pack(anchor="w", padx=12, pady=(12, 8))

        form = tk.Frame(self)
        form.pack(fill="x", padx=12)
        tk.Label(form, text="id", width=8, anchor="w").grid(row=0, column=0, sticky="w")
        self.id_entry = tk.Entry(form, width=28)
        self.id_entry.grid(row=0, column=1, sticky="w", pady=2)
        tk.Label(form, text="label", width=8, anchor="w").grid(row=1, column=0, sticky="w")
        self.label_entry = tk.Entry(form, width=40)
        self.label_entry.grid(row=1, column=1, sticky="we", pady=2)
        form.columnconfigure(1, weight=1)

        self.band_entries: list[tk.Text] = []
        for i, label in enumerate(self.BAND_RANGES):
            tk.Label(self, text=f"Band {i + 1}  ({label})", anchor="w").pack(anchor="w", padx=12, pady=(8, 0))
            box = tk.Text(self, height=2, wrap="word", padx=4, pady=2)
            box.pack(fill="x", padx=12)
            self.band_entries.append(box)

        if trait is not None:
            self.id_entry.insert(0, trait.id)
            self.id_entry.configure(state="disabled")
            self.label_entry.insert(0, trait.label)
            for box, text in zip(self.band_entries, trait.bands):
                box.insert("1.0", text)

        button_row(self, [("Save", self._save), ("Cancel", self.on_cancel)]).pack(side="bottom", fill="x")

    def _save(self) -> None:
        trait_id = (self.editing.id if self.editing else self.id_entry.get()).strip().lower()
        if not TRAIT_ID_RE.match(trait_id):
            messagebox.showerror("Trait id", "Use lowercase letters, digits and underscores.", parent=self)
            return
        if self.editing is None and trait_id in self.existing_ids:
            messagebox.showerror("Trait id", f"{trait_id!r} already exists.", parent=self)
            return
        label = self.label_entry.get().strip()
        if not label:
            messagebox.showerror("Label", "A label is required.", parent=self)
            return

        bands = [box.get("1.0", "end-1c").strip() for box in self.band_entries]
        missing = [i + 1 for i, text in enumerate(bands) if not text]
        if missing:
            messagebox.showerror(
                "Bands",
                f"Band(s) {', '.join(map(str, missing))} are empty. All {BAND_COUNT} are required -- "
                "an empty band means the trait does nothing when the slider lands on it.",
                parent=self,
            )
            return

        try:
            self.result = Trait(
                id=trait_id,
                label=label,
                bands=tuple(bands),  # type: ignore[arg-type]
                builtin=self.editing.builtin if self.editing else False,
            )
        except SchemaError as exc:
            messagebox.showerror("Trait", str(exc), parent=self)
            return
        self.destroy()


class PersonalityPanel(tk.Frame):
    """Embedded in the Settings window."""

    def __init__(
        self,
        parent: tk.Misc,
        personality: Personality,
        *,
        on_change: Callable[[Personality], None],
        on_preview: Callable[[PersonalityProfile], str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.personality = personality
        self._on_change = on_change
        self._on_preview = on_preview
        self._sliders: dict[str, LabeledSlider] = {}
        self._events: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        # Every LabeledSlider fires its on_change callback while it is being
        # constructed. Without this guard, building the panel commits a
        # partially-populated profile once per slider and reports a change back
        # to the Settings window -- so simply *opening* Settings registered as
        # an unsaved edit and the close confirmation nagged every time.
        self._loading = True

        self._build_profile_row()

        self.warning = tk.Label(self, text="", anchor="w", fg=DANGER_FG, wraplength=640, justify="left")
        self.warning.pack(fill="x", padx=8)

        self.scroller = ScrollableFrame(self)
        self.scroller.pack(fill="both", expand=True, padx=8, pady=4)

        button_row(
            self,
            [
                ("Live preview", self._preview),
                ("Edit bands...", self._edit_trait),
                ("New trait...", self._new_trait),
                ("Reset to neutral", self._reset),
            ],
        ).pack(fill="x", padx=8)

        tk.Label(self, text="Preview", anchor="w").pack(anchor="w", padx=8)
        self.preview = read_only_text(self, "", height=8)
        self.preview.pack(fill="both", expand=False, padx=8, pady=(0, 8))

        self._rebuild_sliders()
        self._loading = False
        self.after(POLL_MS, self._drain)

    # -- profiles -----------------------------------------------------------

    def _build_profile_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill="x", padx=8, pady=8)
        tk.Label(row, text="Profile", width=8, anchor="w").pack(side="left")
        names = [p.name for p in self.personality.profiles] or ["default"]
        self.profile_var = tk.StringVar(value=self.personality.active_profile)
        self.profile_menu = tk.OptionMenu(row, self.profile_var, *names, command=lambda _v: self._switch_profile())
        self.profile_menu.pack(side="left")
        tk.Button(row, text="Save as...", command=self._save_as).pack(side="left", padx=4)
        tk.Button(row, text="Delete", command=self._delete_profile).pack(side="left")

    def _switch_profile(self) -> None:
        self.personality = _replace_personality(self.personality, active_profile=self.profile_var.get())
        self._rebuild_sliders()
        self._commit()

    def _save_as(self) -> None:
        name = simpledialog.askstring("Save profile", "Profile name:", parent=self)
        if not name or not name.strip():
            return
        name = name.strip()
        values = {tid: slider.get() for tid, slider in self._sliders.items()}
        profiles = tuple(p for p in self.personality.profiles if p.name != name)
        profiles += (PersonalityProfile(name=name, values=values),)
        self.personality = _replace_personality(
            self.personality, profiles=tuple(sorted(profiles, key=lambda p: p.name)), active_profile=name
        )
        self._rebuild_profile_menu()
        self._commit()

    def _delete_profile(self) -> None:
        name = self.profile_var.get()
        if len(self.personality.profiles) <= 1:
            messagebox.showinfo("Profiles", "Keep at least one profile.", parent=self)
            return
        if not messagebox.askokcancel("Delete profile", f"Delete profile {name!r}?", parent=self):
            return
        profiles = tuple(p for p in self.personality.profiles if p.name != name)
        self.personality = _replace_personality(
            self.personality, profiles=profiles, active_profile=profiles[0].name
        )
        self.profile_var.set(profiles[0].name)
        self._rebuild_profile_menu()
        self._rebuild_sliders()
        self._commit()

    def _rebuild_profile_menu(self) -> None:
        menu = self.profile_menu["menu"]
        menu.delete(0, "end")
        for profile in self.personality.profiles:
            menu.add_command(
                label=profile.name,
                command=lambda name=profile.name: (self.profile_var.set(name), self._switch_profile()),
            )

    # -- traits -------------------------------------------------------------

    def _rebuild_sliders(self) -> None:
        # Rebuilding is not editing. The loading guard keeps each slider's
        # construction callback from committing a half-built profile -- with
        # `self._sliders` partially populated, `_current_profile()` would drop
        # every trait not yet created.
        was_loading = self._loading
        self._loading = True
        try:
            for child in list(self.scroller.inner.children.values()):
                child.destroy()
            self._sliders.clear()

            active = self.personality.active()
            for trait in self.personality.traits:
                slider = LabeledSlider(
                    self.scroller.inner,
                    trait.label,
                    trait.bands,
                    active.values.get(trait.id, trait.default_value),
                    on_change=lambda _v: self._slider_moved(),
                )
                slider.pack(fill="x", padx=4, pady=2)
                self._sliders[trait.id] = slider
            self.scroller.scroll_to_top()
        finally:
            self._loading = was_loading
        self._update_warning()

    def _slider_moved(self) -> None:
        self._update_warning()
        if self._loading:
            return
        self._commit()

    def _current_profile(self) -> PersonalityProfile:
        return PersonalityProfile(
            name=self.profile_var.get(),
            values={tid: slider.get() for tid, slider in self._sliders.items()},
        )

    def _update_warning(self) -> None:
        prompt = build_personality_prompt(self.personality, self._current_profile())
        active_count = len(prompt.used) + len(prompt.dropped)
        if prompt.over_cap:
            self.warning.configure(
                text=(
                    f"{active_count} traits are away from neutral, over the "
                    f"{self.personality.max_active_traits}-trait cap. Only the "
                    f"{len(prompt.used)} furthest from neutral are sent; the rest are ignored. "
                    "Past about eight competing instructions a small model starts dropping them "
                    "unpredictably."
                )
            )
        else:
            self.warning.configure(text="")
        set_text(self.preview, prompt.text or "(all traits neutral - no personality text is sent)")

    def _new_trait(self) -> None:
        trait = NewTraitDialog(self, tuple(t.id for t in self.personality.traits)).show()
        if trait is None:
            return
        self.personality = _replace_personality(
            self.personality, traits=self.personality.traits + (trait,)
        )
        self._rebuild_sliders()
        self._commit()

    def _edit_trait(self) -> None:
        names = [t.label for t in self.personality.traits]
        if not names:
            return
        choice = simpledialog.askstring(
            "Edit bands", f"Trait label to edit:\n\n{', '.join(names)}", parent=self
        )
        if not choice:
            return
        match = next((t for t in self.personality.traits if t.label.lower() == choice.strip().lower()), None)
        if match is None:
            messagebox.showerror("Trait", f"No trait labelled {choice!r}.", parent=self)
            return
        # Shipped traits are editable exactly like custom ones -- `builtin`
        # records provenance, not protection.
        updated = NewTraitDialog(self, tuple(t.id for t in self.personality.traits), trait=match).show()
        if updated is None:
            return
        traits = tuple(updated if t.id == match.id else t for t in self.personality.traits)
        self.personality = _replace_personality(self.personality, traits=traits)
        self._rebuild_sliders()
        self._commit()

    def _reset(self) -> None:
        for slider in self._sliders.values():
            slider.set(50)
        self._commit()

    # -- live preview -------------------------------------------------------

    def _preview(self) -> None:
        if self._on_preview is None:
            messagebox.showinfo(
                "Live preview",
                "Send a message first -- preview regenerates the most recent response under the "
                "current slider positions.",
                parent=self,
            )
            return
        set_text(self.preview, "Regenerating the last response under these settings...")
        profile = self._current_profile()
        threading.Thread(target=self._preview_worker, args=(profile,), daemon=True).start()

    def _preview_worker(self, profile: PersonalityProfile) -> None:
        try:
            self._events.put(("preview", self._on_preview(profile)))
        except Exception as exc:  # noqa: BLE001
            self._events.put(("preview", f"Preview failed: {type(exc).__name__}: {exc}"))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "preview":
                    set_text(self.preview, payload)
        except queue.Empty:
            pass
        self.after(POLL_MS, self._drain)

    # -- persistence --------------------------------------------------------

    def _commit(self) -> None:
        profile = self._current_profile()
        profiles = tuple(
            profile if p.name == profile.name else p for p in self.personality.profiles
        )
        if all(p.name != profile.name for p in profiles):
            profiles += (profile,)
        self.personality = _replace_personality(
            self.personality, profiles=profiles, active_profile=profile.name
        )
        self._on_change(self.personality)


def _replace_personality(personality: Personality, **changes) -> Personality:
    from dataclasses import replace

    return replace(personality, **changes)
