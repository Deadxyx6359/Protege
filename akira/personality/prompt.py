"""Turning slider positions into prompt text.

Three rules from the brief, all of which are easy to get wrong and all of which
are asserted by tests:

1. **Only non-neutral traits are injected.** A prompt listing ten traits at
   "balanced" wastes context and dilutes the two the user actually moved. A
   fresh install with every slider centred therefore contributes *zero* text.

2. **The number never enters the prompt.** The slider selects a band; the
   band's prose is what gets injected. An 8B model does not reliably
   distinguish "formality: 60" from "formality: 70", so a number is at best
   inert and at worst read as a weight it cannot honour.

3. **At most `max_active_traits` are injected.** Past roughly eight competing
   behavioral instructions, a small model starts dropping them unpredictably --
   and which ones it drops is not something the user can see or control. The UI
   warns beyond the cap; this module enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas import NEUTRAL_BAND, Personality, PersonalityProfile, Trait, band_for_value


@dataclass(frozen=True)
class ActiveTrait:
    trait: Trait
    value: int
    band: int

    @property
    def text(self) -> str:
        return self.trait.bands[self.band]

    @property
    def distance(self) -> int:
        """How far from neutral, for ranking when the cap bites."""
        return abs(self.band - NEUTRAL_BAND)

    def line(self) -> str:
        return f"- {self.trait.label}: {self.text}"


def active_traits(personality: Personality, profile: PersonalityProfile | None = None) -> list[ActiveTrait]:
    """Non-neutral traits, most extreme first.

    Ordering matters once the cap applies: if the user has moved ten sliders,
    the eight that survive should be the eight they moved furthest, not the
    eight that happen to sort first alphabetically.
    """
    profile = profile or personality.active()
    out: list[ActiveTrait] = []
    for trait in personality.traits:
        value = profile.values.get(trait.id, trait.default_value)
        try:
            band = band_for_value(value)
        except Exception:
            # A corrupt slider value must not break the turn. Personality is
            # cosmetic; skipping one trait is the right failure.
            continue
        if band == NEUTRAL_BAND:
            continue
        out.append(ActiveTrait(trait=trait, value=value, band=band))
    out.sort(key=lambda a: (-a.distance, a.trait.label.lower()))
    return out


@dataclass(frozen=True)
class PersonalityPrompt:
    text: str
    used: tuple[str, ...]
    dropped: tuple[str, ...]

    @property
    def over_cap(self) -> bool:
        return bool(self.dropped)


def build_personality_prompt(
    personality: Personality,
    profile: PersonalityProfile | None = None,
    *,
    limit: int | None = None,
) -> PersonalityPrompt:
    """Compose the personality block, or empty text when nothing is set."""
    cap = personality.max_active_traits if limit is None else limit
    traits = active_traits(personality, profile)
    used = traits[:cap] if cap > 0 else []
    dropped = traits[cap:] if cap > 0 else traits

    if not used:
        return PersonalityPrompt(text="", used=(), dropped=tuple(t.trait.id for t in dropped))

    lines = ["RESPONSE STYLE:"]
    lines.extend(t.line() for t in used)
    return PersonalityPrompt(
        text="\n".join(lines),
        used=tuple(t.trait.id for t in used),
        dropped=tuple(t.trait.id for t in dropped),
    )


def truncate_personality(prompt_text: str, keep_lines: int) -> str:
    """Shorten the personality block to fit the budget.

    Called only under budget pressure. Personality is truncated so the lock
    directive survives intact -- if the two competed and personality won, lock
    compliance would degrade in proportion to how much personality the user had
    configured, which is a spectacularly bad property for a security control.
    """
    if keep_lines <= 0:
        return ""
    lines = prompt_text.splitlines()
    if not lines:
        return ""
    header, rest = lines[0], lines[1:]
    kept = rest[:keep_lines]
    if not kept:
        return ""
    return "\n".join([header] + kept)
