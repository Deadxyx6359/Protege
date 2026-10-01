# Codex → Claude: megastructure cameos

The person liked the light scene and asked for integrated references to six favorite media. Updated the single painting, preserving its composition, palette, animation registration and clear chat center.

- Cyberpunk 2077: weathered SAMURAI wall graffiti.
- Elden Ring: Ranni seated on a left gallery.
- Blame!: Killy on the lower bridge.
- Uzumaki: spiral carved into upper-right concrete.
- Silent Hill: Pyramid Head in a right doorway.
- Chainsaw Man: sleeping Pochita on that gallery.

`MegastructureScene.qml` now loads `akira/ui/assets/scenes/megastructure-v2-cameos.png`. Original v1 remains available. Generated edit and exact prompt documented in `docs/branding/megastructure-v2-prompt.md`. No new independent sprites, backend changes, or bridge changes.

Validation: `tests/test_qml_megastructure.py` **2 passed** at 100% and 150%; actual app capture visually inspected. Tests include asset readiness, theme/page visibility, animated opacity, reduced-motion freeze, hidden/minimized lifecycle and draft preservation. Review images: `%TEMP%/akira-megastructure-cameos-review/`.

Dark garden still awaits its own implementation. No commit or push this turn.
