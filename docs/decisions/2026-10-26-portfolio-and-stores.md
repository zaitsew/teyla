# 0.32: the portfolio, a readable window, the iPhone, the stores

Decided 2026-10-26. The owner's words this plan serves, verbatim:

> I would add some dashboard showing the progress on products (i don't know how to track them - on github PRs or something else), their status by platforms, etc.

> Think deeply what else Teyla can cover

> Fix UI - like on the top right corner green dot is not accurate, needs you fields are not clearly readable because they are too wide

> Fill free to change UX / UI / texts / Teyla positioning

> Develop ios version in addition to macos. Publish macos and ios version to TestFlight and App Store.

## What we found

- **The green dot.** It turns green when `teyla state` returns, so it says "Live" while a product
  page still reads 30 days of sessions, and it stays green after the Mac slept for an hour. Green
  is also the brand's "money saved" colour (docs/BRAND.md), so the dot spends it on decoration.
- **Too wide.** Cards stretch to the window: a question runs 180 characters on one line at 1600 pt.
  Readable prose is 45 to 75 characters a line.
- **Old questions.** 15 of 39 open questions on the owner's machine are older than 7 days. They sit
  above fresh ones that unblock a release.
- **Progress is already measured, in six places.** `teyla testflight`, `teyla play`, `teyla productize`,
  `teyla reviews`, `teyla routines` and the GitHub backlog cache each know one part. Nothing joins them.
- **The stores.** No App Store Connect record exists for `com.zaitsew.teyla`. The Mac app runs the
  `teyla` command and reads `~/.claude`; the Mac App Store and Mac TestFlight require App Sandbox,
  which forbids both.

Similar tools (Conductor, Vibe Kanban, Devin, the Codex app, GitHub Agent HQ) show sessions as a list
or a board. Linear shows each project's health as on track, at risk or off track, with a written reason.
Runway shows a release train. None ranks what waits on the owner by what it unblocks; Teyla keeps that.

## Positioning

Teyla is the chief of staff for a one-person software studio. One screen says what waits on you,
where every product stands on every platform, and what the agents cost. It runs on your Mac;
nothing leaves it unless you turn the iPhone relay on.

## Phase 1: the portfolio (CLI)

- `portfolio` in the snapshot (version 3, contract in [APP.md](../APP.md)): health per product with
  reasons, a row per platform, PRs, activity, spend, the next milestone.
- `teyla portfolio [--refresh]`: the network pass joins TestFlight, Play and GitHub into
  `~/.teyla/portfolio-cache.json`; the snapshot only reads the cache.

## Phase 2: the window (Mac)

- The status dot tells the truth: "Updating" while anything reads, "Up to date" in a neutral colour,
  "Stale" after 2 minutes, "Offline" on an error. Store data shows its own age ("stores checked 3 h ago").
- Cards and prose stop at a reading width (720 pt); the space beside them holds the product's status.
- Questions older than 7 days fold into "Older", each with "Still needed?" and one-click close.
- A Portfolio screen: one row per product with its health, a platform strip, PRs and last activity;
  a click opens the product page, which gets the same platform row at the top.

## Phase 3: the iPhone

- Portfolio tab, the same readable cards and the "Older" fold.
- A sample mode for anyone without a paired Mac (App Review included), from the bundled fixture.
- Store readiness: icon, privacy manifest, screenshots, review notes (POLICY §15).

## Phase 4: the stores

- One App Store record for iPhone and Mac (universal purchase), China excluded, free.
- The Mac store build is sandboxed: it reads the relay folder the owner picks, like the phone, and
  shows the sample until a Mac is paired. The build installed by `apps/mac/install.sh` keeps running
  the `teyla` command and stays the full app.
- TestFlight for both, then App Review with sample mode and notes.

## What else Teyla can cover (next, not this sprint)

1. A weekly portfolio digest: health changes, builds that reached a person, spend per product.
2. Spend against use: 7-day spend next to the usage probe, as cost per active user.
3. Widgets on iPhone and Mac: "3 need you · 1 off track".
4. Park suggestions: no session and no user for 30 days proposes parking (POLICY §14).
5. A release train per product: what is in review, what goes next, and the two-week rule.
