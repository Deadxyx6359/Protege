# The network door (C1), and the logo

Claude → Codex, 2026-09-11. Follows
[08](2026-09-11-08-claude-to-codex-place-and-hemisphere.md). It covers work order
item **C1** in [../PROJECT.md](../PROJECT.md), and the logo the person has chosen.

## The logo

The person chose the green pixel portrait badge, a woman with bangs and red
earrings inside a green ring. It is one of yours: `exec-56fcb24d-….png` in your
`generated_images` folder. The original is now also in the repo, at
[docs/branding/akira-logo-v1.png](../branding/akira-logo-v1.png).

They asked for **just the circle**, so it has been cut out of its white
background. The surround is transparent, and the ring's stepped pixel edge is
kept as drawn, not replaced with a smooth circle. There is no pale halo on dark
backgrounds.

- **`protege/ui/assets/akira-logo.png`**: 1024 × 1024, transparent outside the
  ring. Use it wherever the app shows its mark: the sidebar, an about panel,
  empty states.
- **`protege/ui/assets/protege.ico`**: the window and taskbar icon, now that badge
  at 16, 24, 32, 48, 64, 128 and 256 px. `shell.py` already sets it, so there is
  nothing to wire. The file name stays until the Akira rename.

Please record the choice in `AKIRA.md`. That is your file, and I have not
touched it. Below about 32 px the face becomes a green dot in a ring. If a
smaller mark is wanted for a tight spot, a simplified drawing would serve
better than a scaled-down portrait.

## C1: the network has one door

Agents can now read web pages from sites the person allows, with the new
`fetch_page` tool. Nothing else in Protégé connects. The rules are in
`PROJECT.md` under C1: https only, never to this computer or the local network,
each redirect checked, size and time limits, and everything audited.

What it means for the interface:

- **Any copy that says nothing leaves this computer is now wrong** as soon as
  a site is granted. Something like "Nothing leaves this computer except
  requests to sites you allow" stays true.
- **The `net.http` picker asks for a site**, e.g. `example.com`, which covers
  its subdomains. `Permissions.grant` refuses `com`, full addresses, wildcards
  and paths, with a reason. Show it. See the new note in
  [../QML_BRIDGES.md](../QML_BRIDGES.md) under `Permissions`.
- `fetch_page` calls appear in `AgentTrace` like any tool. A refusal names the
  site that was not allowed, including when a page redirects somewhere else.
- When "Fetch web pages" is granted, the security review's "leaves this
  computer" note lists it.

No bridge changed.

## Not done yet

- `git push`: git runs as its own process, which the network door does not
  cover, so it needs its own design.
- Search (C2), the browser (C3) and connectors (C5) are next in line, now that
  they have a door to go through.
- Index: add rows **15** (this one) and **13–14** (07 and 08 of today) when you
  commit `README.md`, after the rows 07–12 listed in handoff 06.

## Tests

Full suite at the C1 commit: 1664 passed, 2 skipped, 2 failed. The two failures
are the usual legacy Tk settings-geometry tests. `verify_offline.py` passes, and
now says: nothing but `protege.core.net.client` can reach the network. The logo
commit changes no code.
