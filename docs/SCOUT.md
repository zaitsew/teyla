# The design scout

Status: shipped in Sprint 1 of [Studio](STUDIO.md) (decision S9, lane D). `teyla scout design` reads the design
feeds once a week and lists what changed. It no longer writes proposals: [Playbook](PLAYBOOK.md) holds the reusable
patterns, and its Friday digest is the one weekly interrupt (decision P9). It never edits a rule.

```
teyla scout design --dry          # which URLs it would read; fetches and writes nothing
teyla scout design                # this week: the weekly file
teyla scout design --week 2026-W44
```

Quick start: `teyla scout design --dry`, then `teyla scout design`. It needs network (safe mode refuses it without
`--allow-network`).
The Friday weekly routine runs it (`teyla routine install --if-stale` adds the line to an old wrapper).

## The sources

[`templates/design/SOURCES.md`](../templates/design/SOURCES.md) is the list. A row is read when its **Kind** is
`rss`, `atom` or `hig`; a `hig` row lists the Apple HIG page slugs, one JSON request each. Rows of the kinds `html`
and `x` are never fetched. The section "Needs a priced yes (X reads cost $0.005 a post)" is off: the scout skips
that section and has no fetcher for X, so adding a fetcher is the step that needs the §11 yes. `--sources FILE`
reads another list. Each fetch uses only the Python standard library over HTTPS, with a 15-second timeout, a
4 MB cap, and the user agent `teyla-scout/<version>`. A feed that declares XML entities is refused.

## The weekly file

`~/.teyla/scout/design/<week>.md` (an ISO week such as `2026-W44`): at most 20 items, each with its title, source,
date, URL and one line. With no `--week`, the week is the current one and the items are those of the last 7 days;
with `--week`, that week's Monday to Sunday. The 20 are chosen by taking turns across the sources, newest first, so a
chatty feed cannot fill the file. A feed that failed is listed under "Not read"; the run fails (exit 1) only when
no source could be read at all.

## What leaves the Mac

The HTTPS fetches of the sources, and nothing else. [PRIVACY.md](PRIVACY.md), row 26. Proposal files an older
version wrote under `~/.teyla/scout/design/proposals/` stay where they are; delete them by hand.
