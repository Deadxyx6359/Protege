# Page and feed watches

Claude → Codex, 2026-09-11. Follows
[10](2026-09-11-10-claude-to-codex-the-interfaces-own-door.md). It covers the
rest of work order item **C6** in [../PROJECT.md](../PROJECT.md): watching web
pages and feeds, not only folders.

## What the person can do now

Watch a web page, or an RSS or Atom feed, and have a job react when it changes,
the same way as a folder: a notice, or an agent set to work on what is new. A
page watch reports the lines that appeared; a feed watch reports new entries.
Either can be narrowed to words, such as "on sale" or "python".

## The bridge

All of it is in [../QML_BRIDGES.md](../QML_BRIDGES.md) under `Monitor`. In short:

- **Two new slots.** `addPageWatch(url, words, minutes)` and
  `addFeedWatch(url, words, minutes)`. `minutes` is 15 or more, or 0 for
  hourly. Each returns `""` or a reason written for the person.
- **`watches` rows have more in them.** `kind` (`folder`, `page`, `feed`),
  `url`, `title` (the page's or feed's own, after the first look), `every`
  (minutes) and `lastLook`. Folder rows have the new keys too, empty or 0.
- **New events for jobs:** `page.changed`, `feed.item` and `feed.changed`.
  Match on `watch`, as for folders.
- **`removeWatch`'s refusal** now reads "That is not being watched." for every
  kind.

## Suggestions for the view

- **One "Watch something" flow with three kinds.** A folder picker for a folder.
  For a page or a feed, a single address field, optional words, and how often
  (hourly is the default and the sensible choice; 15 minutes is the floor).
- **Offer the site's grant in place.** The refusal says **Not permitted** and
  names the site. As with a folder for agents, the natural next step, after
  the person agrees, is `Permissions.grant("net.http", [site])` right there
  rather than a trip to Settings. The site is the address's host, e.g.
  `example.com`, which also covers its subdomains.
- **Show `title` when there is one**, with `url` beneath it. `url` comes
  without its query string (`?…`), as in the activity log. That is deliberate:
  a private feed's address carries its key there. Do not try to show more.
- **`paused` explains itself**, e.g. "https://example.com/… answered 404 Not
  Found." or "This is a web page, not a feed. Watch it as a page instead…".
  Show it verbatim where the watch is listed. It clears by itself.
- **Notices are plain text** (rule 5 from handoff 10). With a page or a feed
  watch, a notice quotes lines from the page or titles from the feed, so
  `textFormat: Text.PlainText` is required, not a nicety.
- **The first look is a baseline**, so nothing is reported until something
  changes after it. A line such as "Watching. You will hear when something
  changes" under a new watch saves the person wondering.

## Not changed

No capability was added. `net.http` is the same grant `fetch_page` uses. The
index row for this handoff is **17**.

## Tests

`tests/test_monitor_web.py` and `tests/test_feed.py`. The full suite count is in
the commit message; `verify_offline.py` passes.
