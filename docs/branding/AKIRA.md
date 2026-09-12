# Akira — approved identity

The user chose **Akira**, in tribute to **Akira Nakashima**, and approved the
emerald and black circular pixel portrait as the final logo. This supersedes
every concept retained below. Do not restart logo exploration or substitute an
earlier tarot, star-mask, relay, or statue design.

## Production assets and UI usage

- Approved original: [akira-logo-v1.png](akira-logo-v1.png).
- Transparent production PNG: [akira-logo.png](../../akira/ui/assets/akira-logo.png).
- Windows icon: [akira.ico](../../akira/ui/assets/akira.ico).
- Reusable QML component: [BrandMark.qml](../../akira/ui/qml/Akira/BrandMark.qml).

The source art is unchanged. The UI uses the mark at 36px in the sidebar,
64px in the welcome state, and 32px beside assistant replies. The decoder
samples a smaller image before display so the face survives at small sizes,
including the software renderer. Do not add a second ring, tint, star, or glow.

The portrait carries the original emerald, approximately `#379062`, and sparse
vermilion, approximately `#EB2417`. UI colors adapt for contrast:

| Role | Dark appearance | Light appearance |
|---|---|---|
| Action / selection / focus | `#49AE80` | `#236F4C` |
| Action hover | `#60BD92` | `#2B805A` |
| Action pressed | `#3C9A6E` | `#1E6042` |
| Action text | `#08150E` | `#FFFFFF` |
| Danger | `#F06456` | `#BF3025` |
| Danger text | `#08150E` | `#FFFFFF` |

Use the tokens in [Theme.qml](../../akira/ui/qml/Akira/Theme.qml), not copied hex
values. Green indicates action or selection; red is for errors, stopping and
destructive actions. Keep the surrounding surfaces neutral and the authored
landscape, space and abyss palettes independent. Static supporting text and
filled action states are checked for at least 4.5:1 contrast on opaque surfaces.
