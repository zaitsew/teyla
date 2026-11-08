# Changelog

## 0.45.0 — 2026-11-08 — Drafts count for a goal

- **A waiting draft belongs to one goal, so Today can say "N drafts for this goal".** A goal in `~/.teyla/gtm/goals.toml` takes a `[goal.drafts]` table with `products`, `platforms` and `kinds` lists; the first goal whose lists all match claims the draft, and an empty list matches nothing. `teyla growth tag ID... --goal GOAL` tags a draft by hand and wins over the rules; `--goal none` keeps it out of every goal and `--goal auto` hands it back to the rules. A tag naming a goal that is gone is ignored. `teyla gtm today --json` adds, per goal, `drafts {total, growth, by_source}`, and at the top `untagged_drafts` and `draft_goals`. `teyla gtm init` writes an example rule. See docs/GTM.md, "Drafts and goals".
- **Today's next step uses them.** The lead goal's next line reads "2 replies to answer, then 8 drafts for this goal", and a quiet line says how many drafts have no goal, with a link to Growth. On Growth each draft has a goal menu: a goal, "No goal", or "Let the rules decide". The iPhone card says the same next line; the relay sends the per-goal draft count and the untagged count.

## 0.44.1 — 2026-11-08 — A weekly check that the README and the store listing follow the product

- **`teyla freshness`: does the README, the store text and the screenshots still match the product.** For each product it counts the user-facing changes (the `teyla whats-new` split) that landed on the default branch since the newest commit of `README.md`, the oldest local screenshot the README shows (logos, icons and SVGs are skipped), the What's New notes (`docs/whats-new/`, `release_notes.txt` or `whats_new.txt`; a generic note is flagged, and a product with no notes file yet, as on a first store version, is skipped), the store listing text (release notes excluded) and the store screenshots, all read from the default branch. Maintenance does not count: a change must touch a path outside docs, tests, hooks, `teyla.toml` and the store files. A check is stale at 10 changes and 14 days; `[freshness]` in `teyla.toml` sets `changes`, `days`, `skip`, `listing`, `screenshots` and `whats_new`. `--quiet` writes `~/.teyla/freshness.problems`, which the session-start banner and the weekly digest read (rank 5, "N stale README or store items"); the weekly routine runs it and an older wrapper is rewritten. Offline: git only, no model call. See docs/COMMANDS.md.

## 0.44.0 — 2026-11-08 — Today puts your goals first

- **Today leads with your goals, one circle per real outcome.** The queue and board layouts are gone (and the `teyla.today.layout` default with them). Teyla Admin's Today now opens on the goal furthest behind this week: one row per outcome target, one circle per unit of the weekly number. A circle fills only when an outcome came back; a draft or a send never fills one. A chip says "Behind this week · N short" or "On pace this week". Under the rows, the next step for the goal: replies first, then drafts, with one button. Other goals sit below as thin rows; a goal with no number asks "What would count as progress this week?" and offers Set a number. Sent (ticks against the daily target), Came back and Prepared are one quiet line at the top. The GitHub-style activity graph follows the goals and stays on Growth. Clicking the lead goal opens its detail: weeks to the deadline, the last eight weeks per target and which sources feed it. Drafts are reviewed on Growth. See docs/GTM.md, "In the apps".
- **A three-step first run writes your first goal.** With no goals file, Today asks "What should this work lead to?": the outcome in your words (or a starter: conversations, testers, customers, investors), an optional "done when" and deadline, one weekly number, and the daily send target. A live preview shows the card it will make.
- **`teyla gtm goal add|set`: change goals without opening the file.** `goal add --title T [--weekly STAGE=N] [--deadline D] [--done-when TEXT] [--per-day N]` appends a goal and creates `goals.toml` when there is none; `goal set ID [--weekly STAGE=N] ...` rewrites only that goal's block (STAGE=0 removes a number). Both write nothing when the result would not parse. Goals take a `done_when` line. `teyla gtm today --json` adds `week_end` and, per goal, `weeks_left`, `short` (how far this week's outcomes are from their targets; approaches never count), `fed_by` and `unfed`, and per target its `counter` and an eight-week `history` from the saved weeks.
- **The iPhone Today card follows.** It shows the lead goal's circles, its pace and deadline, one "Next" line, and the quiet line. The relay sends the new fields; an older `teyla` still decodes.

## 0.43.0 — 2026-11-07 — Teyla Admin opens on Today, and a Today card on the iPhone

- **Teyla Admin opens on Today; the iPhone shows a Today card.** The admin Mac build's first screen reads `teyla gtm today --json`: the ordered next actions, the drafts waiting for approval (A approves, which only marks a draft; S skips; O opens; Reject asks for a reason), what waits per source with an Open button when the source gave a page, today's sends against the daily target, this week's outcomes against each goal's targets with the days left, and the source checks. Two layouts, `queue` and `board`, switch with `defaults write com.zaitsew.teyla.local teyla.today.layout`. No commit counts. The store build has no Today. See apps/mac/README.md, "Today".
- **The iPhone snapshot carries the GTM Today card.** `teyla relay sync` adds a `gtm` block from `teyla gtm today --json`: waiting counts, today's distribution against its target, goal titles with weekly targets and days left. It has no source names, no links and no people. An older `teyla` leaves it out and the card stays hidden.

## 0.42.0 — 2026-11-07 — Publish approved posts, a daily engage list, and store notes that say what changed

- **`teyla growth publish`: approved posts go out through the networks' own APIs.** `teyla growth connect linkedin|threads|instagram|youtube` runs the OAuth flow in your own terminal and keeps the token in the macOS Keychain (`teyla-growth-<network>`), never in a file or a log; `--status` and `--forget` show and remove it. `teyla growth publish <id..>|--day D` posts only approved items: LinkedIn (Posts API, as a member), Threads, Instagram (a Reel, resumable upload) and YouTube Shorts (resumable upload; private until Google audits the app). Each item and network has an idempotency key, so a second run does nothing and a run that never finished waits for `--retry`. A post lands in the ledger as `published` with its URL, `by: owner-approved`. A network that is not connected, safe mode, or X (its API is paid; `x_paid = true` still finds no adapter) gets today's packet instead. PRIVACY.md rows 46 to 49. See docs/GROWTH.md, "Publishing".
- **`teyla growth engage`: 20 posts a day worth a reply, each with an angle, never a ready reply.** It reads `~/.teyla/growth/targets.toml` (`engage init` writes one with placeholders; groups founders, c-level, investors, builders), runs one cached `grok -p` X scan a day with a 4-turn cap (at most two a day with `--refresh`) and your RSS and Substack feeds. A row keeps only an `x.com` status link by one of your targets. `engage done <n..>` logs a reply in the activity graph, as a claim from an agent session. PRIVACY.md rows 50 and 51. `teyla console growth` carries `engage {day, scanned, total, done, goal}`.
- **Teyla Admin: "Ready to publish" and "Engage" on the Growth page.** An approved item has one button, "Publish to connected networks", which runs `teyla growth publish <id> --json` after a confirmation and shows the result per network. Engage lists today's posts: Open, Done, and ↑ ↓ Return D on the keyboard. The iPhone shows "Replies today". Nothing in the apps writes or sends a reply. See docs/APP.md, "Growth page".
- **`teyla gtm`: one screen for what waits for you today, and a weekly review per goal.** `teyla gtm` (or `gtm today`) lists what waits for approval (the growth review queue and each source's queue), what waits to be sent, replies to answer, today's posts and approaches against `[distribution] per_day`, this week's outcomes against each goal's weekly targets, and the days left to each deadline. It starts with an ordered next-actions list. `teyla gtm week` shows the funnel and conversion per stage, stalled items, offer fit, outcomes by channel, missed targets and next week's targets, and saves the week to `~/.teyla/gtm/weeks/`. Three counters never mix: preparation (agent work, never a success metric), distribution (what you sent; a row logged from an agent session counts 0) and outcomes. Goals live in `~/.teyla/gtm/goals.toml` (`teyla gtm init` writes an example with a relationship funnel ending in offer fit: hire, consulting or product). Products feed it with a JSON file in `~/.teyla/gtm/sources/` or a read-only command. A missing source is one doctor line and never fails. No network call. See docs/GTM.md.
- **`teyla policy sync` writes a shorter merge list and tells Hermes the owner's rules.** The generated Codex, Grok and Cursor copies keep the MERGE-APPROVED block with every repo name in order but drop the `#` provenance comments (about 44 KB to 28 KB, under the 32 KiB size warning) and point to `~/.claude/CLAUDE.md` for them; the source file is not changed. The Hermes section now says to follow `~/.agents/POLICY.md` and the owner's rules in `~/.claude/CLAUDE.md`, and adds the merge rule (merge only into a MERGE-APPROVED repo, never squash, never force-push). The previous section is recognised, so existing installs upgrade without an inbox entry. The work policy template no longer lists Zed, which only reads a repo's AGENTS.md.
- **`teyla whats-new`: a store "What's New" that names what a user would notice.** `draft <repo> --version V` lists the PRs merged since the newest version tag (any prefix, or `--since`), splits user-facing candidates from internal ones (docs, tests, CI, deps, listing and policy items) and prints a template body; `--write` creates `docs/whats-new/<V>/<locale>.txt` placeholders and never overwrites real text. `check` exits 1 for a locale with no file, an empty or placeholder file, or a generic line such as "Bug fixes and improvements" in English, Spanish or Russian. Offline. See docs/COMMANDS.md.
- **AI directory listings show up as platforms.** A repo's `teyla.toml` can declare `[directories.claude]`, `[directories.chatgpt]` and `[directories.gemini]`, each with the state copied from the portal (`published`, `approved`, `needs_changes`, `in_review`, `draft`, ...), the kind (`connector`, `plugin`, `app`) and the date. `teyla portfolio` adds one row per listing after the device platforms, with role `directory`: `published` reads `live`, `approved` and `needs_changes` read `blocked`. These rows never change health and are never something to install. The Mac app draws them after a divider in the Platforms column, which is now wide enough for eight icons; the iPhone app names them. Teyla reads no portal, so a row is as fresh as its `as_of`.

## 0.41.0 — 2026-11-07 — An activity graph, Teyla Admin, and apps that show the release number

- **The iPhone, Mac store and Teyla Admin apps show the release version.** TestFlight said 0.32.0 and Teyla Admin said 0.1.0 while the CLI was 0.40.0, so you could not tell whether the newest build was installed. `scripts/release.sh` now sets `CFBundleShortVersionString` in `apps/ios/project.yml` and `apps/mac/project.yml`, and `tests/test_app_versions.py` fails when they drift. The App Store version record stays 0.32.0 while Apple's 4.3 reply is open.
- **`teyla storage sweep` now removes temp DerivedData that holds Swift packages.** Every temp build folder with SwiftPM dependencies was kept: the packages' own `SourcePackages/checkouts/*/.git` looked like a git checkout, and their test certificates looked like key files. On 2026-11-06 that left 8.5 GB in session scratchpads and a 2.4 GB `*-verify` folder while the disk sat at 17 GB free and the guard refused 143 builds in an hour. SwiftPM's clones no longer count once `git status` says every checkout is clean; an edited checkout, one that is not a git checkout, or a key file outside the clones still keeps the folder. The sweep also takes pytest runs but the newest three (`pytest-of-<user>/pytest-<N>`), Chrome's code-sign clones while Chrome is closed, `$TMPDIR/DockerDesktopUpdates` idle 7 days, and, under `sweep_urgent_free_gb`, the clang module cache while no compiler runs. A job started without `TMPDIR` finds the per-user temp folder with `getconf`.
- **`teyla growth activity`: a GitHub-style graph of your marketing and sales activity.** Any post, comment, reply, e-mail, DM, call, meeting, ad or outreach is +1. `teyla growth log` takes the new kinds and `response`, an optional `--product`, `--count N` (1..50) and `--day` (up to 7 days back). Weeks are ISO weeks, Monday first; levels come from the quartiles; the streak and the longest run are shown, with meetings held and responses as outcomes. A row logged from an agent session is a claim and counts for nothing. `--json` is the contract for the apps (`version` 1). No network call. See docs/GROWTH.md, "Activity".
- **An activity graph in the Mac and iPhone apps.** Growth leads with the contribution graph of your marketing and sales activity
  (any post, comment, email or meeting counts +1): 53 weeks on the Mac, 17 on the phone, today, the streak and the outcomes. A "+1"
  button (⌘L on the Mac) logs one with `teyla growth log`; on the phone it is a new signed outbox kind, `activity`, that the Mac turns into
  exactly `teyla growth log --kind <kind>` for one of eleven fixed kinds. The relay snapshot gains an `activity` block of counts
  (version stays 3). Two Mac layouts, `year` and `quarter`, switch with `defaults write com.zaitsew.teyla.local teyla.activity.layout`.
  Needs `teyla growth activity`; an older command shows "Update the teyla command to see activity.". See docs/APP.md, "Activity graph".
- **The full Mac build is now Teyla Admin.** `apps/mac/install.sh` installs it as `~/Applications/Teyla Admin.app`, so Finder, Spotlight and the Dock tell it apart from the store build named Teyla (which TestFlight keeps updated in `/Applications` and which has no admin sections). The old `~/Applications/Teyla.app` is removed only when its bundle id is the full build's, `com.zaitsew.teyla.local`; the bundle id and settings are unchanged.
- **The MCP server's own text states facts and gives no commands.** Anthropic's directory review asked that instructions,
  tool and parameter descriptions and tool outputs describe what the server does, not tell the assistant what to do.
  Twelve descriptions and fourteen error texts are reworded; behaviour, tool names and schemas are unchanged. The one
  data change: `teyla_monitor` leaves out each finding's `action` (an imperative sentence for the owner at a terminal) and
  adds `omitted` saying where those sentences are printed. `teyla asks` and `teyla answer` lookup errors, and the clipboard
  detail of `teyla answer`, are reworded the same way. `tests/test_mcp.py` scans all of it with the command regex the directory review suggested.

## 0.40.0 — 2026-11-05 — Test builds report from every platform, and idle apps go when memory is tight

- **`teyla storage apps`: quit the apps you listed when memory is tight and you have not used them for hours.** Off by default (`guard.apps_quit = off | dry | on`, `guard.apps_quit_list`, `apps_quit_idle_h` 4, `apps_quit_every_min` 5). `guard tick` asks one idle listed app to quit, the largest, at most one per 5 minutes, only on memory pressure, a full compressor or heavy swap-out (disk and CPU load do not count). It is the Cmd-Q request, never a signal; an app with unsaved changes stays and is not asked again until it was in front. Finder, Teyla, Claude, ChatGPT, Codex, terminals, editors, Xcode, Simulator and browsers are protected, Docker only goes with no container running. `dry` journals `would-quit` rows in `~/.teyla/app-quit.tsv` and posts one notice after a week; `--report` sums them per app; `--quit` runs one pass now. The quit call was tried on one app from a launchd job; a full tick in `on` mode has not run yet. See docs/MANUAL.md.
- **Android review capture: `packages/review-android`.** A test build of a Compose app gets the same shake-and-write feedback as iOS, macOS and web, and a Settings row that works with a D-pad on a TV. Two Gradle modules share one public API: the real one is linked in `debug` and `internal`, the no-op one in `release`, so `teyla review store-check app.aab` passes on a store build (a fixture app proves both directions with R8 on). `Modifier.reviewPrivate()` areas are painted black in the picture; a `FLAG_SECURE` window is refused rather than sent blank. Unsent captures wait in app storage and retry. Dictation is left out so the library asks for no microphone permission. Not run on an emulator yet. See docs/REVIEW.md, section "Android".
- **Every product owes its testers a way to report.** `teyla productize` R11 fails when a product shared with others has no feedback capture in test builds of its primary platform, and warns for an owner-only product. `teyla scaffold` gives `app` and `ios` repos `docs/FEEDBACK.md`, and `teyla review privacy --product <name>` prints the note above Send and a privacy-policy paragraph.
- **Web review capture: `packages/review-web`.** A test build of a web product gets the same tap-and-write feedback as iOS. Three locks keep it out of a production build (a build flag, a host allow-list, a dynamic import), so `teyla review store-check <dist>` passes on a flag-off build. Private areas and password fields are painted black in the picture. Unsent captures wait in the browser and retry. See docs/REVIEW.md, section "Web".
- **The review package builds for macOS and opens a feedback form there.** `ReviewCommands()` adds a Help menu item,
  "Report a problem…", with Control-Option-Command-F; `ReviewMenuButton()` is the Settings row. The window is frozen with
  `cacheDisplay` at the backing scale and opens in a window of its own beside a form sized for a pointer: click a spot or drag
  an area, type, send. `.reviewPrivate()` paints black in the saved and sent picture, and a view that cannot report its frame
  hides the whole window. The first-send notice, the preview, `requiresHealthConsent` and the refused states are the iOS code,
  not a copy. The capture format stays v1 (`device: "Mac"`, `comment.input: "text"`). Maps, video and 3D views can come out
  blank in `cacheDisplay`; the form says so when it finds one. The second lock reads StoreKit's `AppTransaction.environment`
  (`.xcode` and `.sandbox` open the form; `.production`, an error or no answer refuse it). iOS behaviour is unchanged.
- **`teyla review store-check` reads a Mac `.pkg`.** It expands the installer with `pkgutil --expand-full` and checks every
  `.app` in it; Mac `.app` and `.xcarchive` bundles (`Contents/Info.plist`, `Contents/MacOS`) have tests of their own.

## 0.39.0 — 2026-11-04 — A startup page that names the next missing fact

- **`teyla startup`: one page per product, with the next fact it is missing.** Types are venture, indie, open-source and
  personal; unset uses the venture ladder. Rungs (Built, Tried, Used, Retained, Paid, Repeating, Sustaining) are earned from
  stored evidence and checked on their own. Zero, unknown and stale stay different. Agent-claimed growth rows do not count.
  Startup commands read the cache and make no new network call. `teyla portfolio --refresh` writes one row per product per
  day to `~/.teyla/startup/snapshots.jsonl`.
  See docs/STARTUP.md.
- **`teyla startup yc`: a 15-box YC sheet.** A box means "I can answer this honestly, with evidence"; a true $0 still checks
  `pay`. All 15 show the apply link. Teyla never submits. Answers stay on the Mac in a 0600 file, an agent's answer is a draft,
  and `yc confirm` is refused in an agent session.
- **Mac: a startup section on the product page, the YC sheet, and the stage on Products.** The Mac sale ledger now treats rows
  an agent logged as claimed, as the CLI does.
- **iPhone: the same section, read from the snapshot.** It shows the stage, the ladder and the metrics, and "0 of 15 boxes" with
  the next question. The sheet and its answers stay on the Mac: the relay is signed, not encrypted.

- **The iOS review package sends to the shared channel by itself, and asks the tester first.** With `TeylaReviewChannelURL` and
  `TeylaReviewChannelKey` in the Info.plist (and no `deliver` closure), `TeylaReview` PUTs the picture and then the JSON, counts a
  capture as sent only after both answer 200, retries 429, 503 and network errors, and never retries a 400, 401, 403, 413 or 422.
  `app.product` comes from `$0.product` or `TeylaReviewProduct`. New: a first-send notice (what, who, why, how long; once per
  install), `.reviewPrivate()` to paint a view black in every capture, and `requiresHealthConsent` for a checkbox before Send.
  By default nothing leaves the device unless the plist keys or a `deliver` are set. `teyla review store-check` now also fails
  a store build whose Info.plist holds `TeylaReviewChannelURL`. See docs/REVIEW.md, "The shared channel" and "Privacy".
- **Channel captures expire on the Mac.** Each `teyla review pull --channel` removes a capture 30 days after it was closed, or 90 days after import if it was never opened. The inbox gains `closed_at`.
- **A shared review channel.** `packages/review-channel/` is a write-only service (Python standard library, one container) that
  takes feedback captures from every product and platform; `teyla review pull --channel` moves them over SSH into the inbox
  within the hour and deletes the server copy. `teyla review channel key add|revoke|path` manages one key per product and
  `teyla review channel install` adds the hourly agent. Captures from it are marked "sender unverified" in `teyla review list`.
  PRIVACY row 45; see docs/REVIEW.md, "The shared channel".
- **A production build provably has no review entry point.** `teyla review store-check PATH` reads an `.xcarchive`, `.app`,
  `.ipa`, `.aab`, `.apk` or a web `dist` and exits 1 naming what it found. docs/REVIEW.md now says a store build is a separate
  archive of the same commit, built with `TEYLA_REVIEW_ENABLED=NO` and `TEYLA_REVIEW=0`, and a TestFlight build is never promoted.
- **The capture format names more builds.** `app.configuration` gains `play_internal` and `test_host`; `app.product` carries a slug
  for a web build; `reporter` is the sender's claimed name. `v` stays 1. On the Mac the package asks StoreKit which channel the
  install came from (not yet checked on a real Mac TestFlight build).

## 0.38.1 — 2026-11-04 — The iPhone gets the admin tabs

- **The phone's Growth snapshot says how many slots have no draft, and which products nobody tried to sell.**
  `teyla state` carries `gaps` and `not_tried` (product ids only, a few bytes each) in the compact growth part. No draft text
  and no quote goes with them.

- **iPhone: Growth and More tabs.** Growth shows posts today against the target, the channels still waiting for a post,
  drafts waiting, the queue, the pipeline and the products nobody tried to sell. More holds Money, Operations, Playbook
  and Settings (moved off the Home toolbar), each with its live figure. Products marks a product "Not tried to sell yet".
  A figure the phone is not sent is a dash with "On your Mac". Drafts stay on the Mac: the relay is signed, not
  encrypted. `-TEYLA_MORE` and a long-text fixture help with screenshots. The Older fold opened from Home's Next line is
  now covered by tests.

## 0.38.0 — 2026-11-04 — The apps become an admin, and the content factory runs

- **Mac: Settings is a page.** The sidebar's Settings opens Teyla's own settings file in plain groups: folders, updates,
  machine guard, disk clean-up, what Teyla keeps, which products and agents it looks at. A value the file does not set shows
  its default in grey. Environment variables show their names only, and no secret is ever shown. The page reads the file and
  never writes it; the file's path and a "Show in Finder" button are on the page. The voice, shortcut and iPhone switches sit
  on it too.

- **The video channels get a daily clip with no filming.** When there is no clip you filmed, the best lesson the editor
  passed becomes a silent 16 to 28 second vertical video: your own words, line by line, on a dark card, the hook in
  the first second, the artifact on the last card. It goes through the same frame check as the session reel. Drawing
  needs the `reel` extra: `teyla update` keeps it on a Mac with a growth config, `teyla growth doctor` has a `reel
  extra` row, and the slot report names the command when Pillow is missing. See docs/GROWTH.md, "The daily video".

- **Mac: a product page shows users and selling.** Four figures: active users this week, sale attempts (posts,
  marketing, ICP meetings, counted from the growth ledger), what shipped in 7 days, and feedback and crashes (a dash:
  nothing reports them yet). A product nobody tried to sell reads "Not tried yet. Next in line."; the page never
  proposes closing it.

- **The content factory ranks by what passes and mines its own stories.** `teyla growth plan` gives the next slot to the
  idea the editor is likely to pass: a lesson with a number and an artifact first, a bare product summary never. Once a
  week the harvest step makes one model call over your policy file, the last `teyla you` report, crash and load counts,
  AI spend at list price, the CHANGELOG and merged fix PRs of public products. A story enters only when its excerpt exists
  in the material, every number is in the excerpt and no leak, employer, job search, person or store dispute is named.
  The harvest line counts what the checks dropped. See docs/GROWTH.md, "Stories".

- **Mac: Growth is a full page.** Slots filled today and the drafts waiting for you come first. You read a draft in
  full, with its editor score and its voice and leak checks, then approve, reject with a reason, or edit it. Approving
  only marks a draft; nothing is posted or sent from the app. Channels, pipeline, episodes, trend ideas and outreach
  counts follow. Two layouts (review queue first, channel board first) sit behind a switch until you choose.

- **Mac: Playbook is a full page.** Contradictions between your rules and your corrections, the guidelines (each opens
  its file), the model ladder with new models and the arena shortlist (every row "candidate, not a decision"), counts of
  what is kept, and what the sessions say about you with the chores to hand off. A part that fails shows its reason and
  the rest still load.

- **Mac: Money is a full page.** Cash per month is the first figure and comes only from the subscriptions you list.
  List price of the local AI sessions has its own section, labelled "Not cash", with a 7 or 30 day switch, bars by day,
  and by product and model. Provider billing, credits, renewals, cloud rows and Actions minutes follow. A price the
  report lacks is a dash with the reason.

- **Mac: Operations is a full page.** It replaces Tools. Figures first (failures, safe to leave, disk, swap), then the
  machine with 24-hour lines, the failures with their actions, scheduled tasks worst first, harnesses and AGENTS.md sync
  state, and security counts. A figure the report lacks is a dash with the reason.

- **The Mac app reads the admin report.** The sidebar is Home, Decisions, Products, then Growth, Money, Operations and
  Playbook, with Settings at the foot; Tools is part of Operations. The app reads `teyla console --json` from its cache
  first, reads again in the background, and shows a section's own error without hiding the others. The four pages show
  their headline figure for now; each section gets its full screen in the next changes.

- **Home starts with figures, not a paragraph.** Five tiles (Decisions, Running, Posts today, Cash per month, Disk free)
  read `console` in the snapshot; a figure with no source shows a dash and the reason, never a zero. Under them one Next
  line of at most 10 words names the top decision and opens it. A model's brief appears there only when it fits.
- **All products is a table on the Mac.** Icon, sparkline, platform icons and figures in aligned columns; a raw next step
  shows only when it is a short English line, otherwise the count of open items. The iPhone row follows the same rules.
- **Decision cards keep one order on both apps:** question, why, proposed default, action. Long text stops at three lines
  with More.

- **The apps share one visual grammar.** `apps/mac/Teyla/UI/Grammar.swift`, compiled into the iPhone app too, holds `Page`,
  `PageHeader`, `SectionHeader`, `StatTile`, `Scorecard`, `RowCard`, `EmptyState`, `ErrorRow` and `ClampedText`.
  `apps/mac/README.md` says how to use them. The PNG hook now draws every page: `TEYLA_PREVIEW_SNAPSHOT_VIEW` takes
  `decisions`, `portfolio`, `product:<id>`, `tools` and `settings`.
- **Console: the Money section, and `teyla subs`.** `teyla console money` answers "what leaves my accounts". The headline is
  the cash per month: the sum of the subscriptions you list in `~/.teyla/subscriptions.toml`, with every row that has no
  price named, never estimated. `teyla subs list|add|set|remove` edits that file. Beside it, kept apart and labelled as
  list price: what the local AI sessions cost over 7 and 30 days, by product, model and day, what the providers billed
  where an admin key exists, GitHub Actions minutes, credits and the cloud lines. The session scan is cached; `section()`
  reads files only.
- **The apps have one small type system.** Mac and iPhone use exactly five type levels plus one style for big numbers, and
  every size, gap, radius and colour comes from a token. The iPhone has real token enums now. A test fails on a literal.
  The toolbar's status dot no longer touches the edge of its capsule.
- **Console: the Operations section.** `teyla console operations` answers "what failed or needs capacity": machine health
  (RAM, swap, compressor, disk with a 24 h series, agents, top apps), `leave {ok, blockers}` (can the lid close), the
  unresolved failures from `teyla attention`, every scheduled task, the connected harnesses with versions, whether the
  generated AGENTS.md copies match the policy, and the cached security counts. It reads local files only and returns in
  about 7 seconds. `teyla state` starts a detached 30-minute refresh of the cache for the phone.
- **`teyla schedules` no longer calls the relay agent STALE.** It runs `relay sync --quiet` and logs nothing, so the log's
  age said "14 hours" while the snapshot was a minute old. The agent's run time is now the snapshot time in `relay.json`.
- **A product can carry a tester's review captures.** `$0.deliver` hands a saved capture to the product's own backend, and
  retries what was saved earlier, with no relay key needed. The package itself still makes no network call.
  `teyla review pull --vouched-folder DIR` imports what the product's script downloaded.
- **Review mode no longer looks like a hang.** The frozen app shrinks into a framed picture with a "Review mode" label,
  and the panel takes its own space above the safe area and the keyboard, so typed text and the buttons stay visible.
  Three steps: tap a spot or circle an area (a new optional `region` in the capture), write or dictate, then a screen
  that says whether the capture was sent or only saved on this phone. A product translates the words with `$0.strings`.
- **`teyla testflight` warns when a store build lags main.** A repo declares `[[release.store_target]]` in `teyla.toml`;
  when the platform's newest upload is more than three days older than the newest change on the default branch to the
  target's sources, the row says so and prints the release command (`--platform macos` for the Mac). A target frozen for
  30 days is skipped. It reads the `beta reached` answer and git only. The Teyla repo declares its `TeylaStore` target.

## 0.37.4 — 2026-11-03 — One command connects the store app

- **`teyla relay connect`.** One command for the whole relay setup: it turns the relay on, makes the key and opens the
  store app with a `teyla-pair:` link. Its text now names the Mac app, not the iPhone, and says what to do when an older
  build ignores the link.
- **The store app and the iPhone pair from a link.** The folder panel opens on `iCloud Drive/Teyla`, and the Mac shows a QR
  code for the iPhone. A link never replaces a stored key by itself: a different key waits for the owner's yes, a key
  that could not be read is left alone, and a second different link makes that yes store nothing.
- **teyla.dev.** The homepage, support and privacy URLs now point at the new site.

## 0.37.3 — 2026-11-02 — Doctor names a failed store read

- **`teyla doctor` names a failed store read.** A store read that failed in the last `teyla portfolio --refresh` is now
  a doctor row. An expired gcloud login is a fix row with its command: `gcloud auth login && teyla portfolio --refresh`.
  It reads the portfolio cache and calls no store.

## 0.37.2 — 2026-11-02 — Refresh updates the user numbers

- **Refresh updates the user numbers.** `teyla portfolio --refresh` now runs the usage probes, so Home no longer waits
  for the weekly `teyla products`. It runs outside safe mode only, also from the 6-hour background pass. Probes started
  by the app or launchd now find `teyla` and the tools in user directories.
- **A probe with no numbers keeps the last good row.** A probe that exits 0 with no output, or with a marker such as
  `usage_probe=needs_teyla` or `probe=needs_key`, no longer blanks the repo's counters in the usage cache.

## 0.37.1 — 2026-11-02 — Probes read the default branch

- **Usage probes read the default branch.** `teyla products` and the Home numbers run `check.sh` as committed on
  `origin/HEAD`, with the checkout's `.env`, so a checkout on a feature branch no longer hides a merged probe. A repo
  named on the command line and safe mode still run the checkout's file. Nothing is fetched: the ref moves when
  something fetches.

## 0.37.0 — 2026-11-02 — Home is a scoreboard

- **`teyla state` and `teyla portfolio` rank the products.** `portfolio.home` holds three ranked sections: people use
  it (active or new users in 7 days), being built (5 or more commits in 7 days), quiet. Parked products are always
  quiet. Each product gets `summary`, `icon_jpeg` and `metrics`: users, commits with 12 weeks, agent spend and money
  for 7, 30 and 365 days. A number nobody counted is null and shows as "—", never as zero.
- **Monetization is per product.** `[monetization] enabled = true` in a repo's `teyla.toml` turns it on; it is off by
  default. The usage probe gives `mrr_usd`, `paying_users` and `revenue_*_usd`.
- **The iPhone Home is a scoreboard too.** The same three sections and Week / Month / Year switch. Being built and
  Quiet open with "Show all". An older Teyla on the Mac still gets the "Update Teyla on your Mac" card.
- **The Mac Home is a scoreboard.** Three sections instead of the core list: "People use these" (a card per product
  with active, new and total users, commits with a 12-week chart, agent spend and a Monetization chip), "Being built"
  and "Quiet". A Week / Month / Year switch changes the numbers and never the order. The sections and their order come
  from `portfolio.home`; an older `teyla` command still gets the core products as a plain list. The star now pins a
  product to the front of its section, and Home no longer has a star or a "Core products" section.
- **`teyla reviews settle` closes an open P1 on a merged PR.** A PR merged after its last review found a P1 stays
  in `teyla reviews` and `teyla attention` as "merged with an open P1", even when a later commit fixed it. `settle`
  appends one `skip` line, the kind `review-gate` writes at merge, after checking the evidence in git: the PR is
  merged and has an open P1, a decision file on the default branch names the PR, and for `fixed` the commit is on
  that branch and after the reviewed commit. `--dry` prints the line. The ledger is never edited by hand.

## 0.36.1 — 2026-11-02 — iPhone Home and Decisions

- **The iPhone app gets Home and Decisions.** Home shows your core products with their progress and the top
  decisions of the week. Decisions groups your questions Pay, Decide, Do, with "Use default", "Teyla suggests closing",
  "Agents can settle" and "Teyla closed". Accepting a close and undoing one work from the phone through two new relay
  kinds, `close` and `reopen`, each running exactly one `teyla asks` command. An older Teyla on the Mac gets an
  "Update Teyla on your Mac" card. The Today tab is gone and Portfolio is now Products.
- **A product without a Play package no longer voids the store pass.** `teyla portfolio --refresh` now marks that
  product's Android row unknown and checks the rest.
- **`teyla shield` reports a symlink loop as FIX on Python 3.12.** It crashed with a traceback before, for the
  accepted-risk doc, `hosts` and `core.hooksPath`.

## 0.36.0 — 2026-11-02 — Home: your core products and only the decisions that are yours

- **The Mac app opens on Home.** Your core products with their progress, then the top decisions from the last 7 days,
  ranked by what they unblock. A core product is one you starred, or else one with weekly users or at least $40 of spend in 7 days, up to 6.
  `teyla product core` manages the stars. `teyla state --json` carries `portfolio.core` and each product's `progress`.
  Update the app and the CLI together: an older CLI gives the new app an empty grid.
- **Decisions.** Questions are grouped Pay, Decide, Do. "Agents can settle N" lists what needs only a go, and each
  answer goes to its own session; nothing there runs by itself. "Teyla suggests closing N" stays open until you accept,
  with an Undo.
- **Triage (`teyla asks triage`, `teyla asks accept-close`).** Rules decide first and the configured model classifies
  the rest. A price, a secret, a step on your device or another person always stays yours. The model never closes a
  question, age never closes one, and similar questions are never merged. A failed call leaves them as your questions.
- **`teyla attention`: what is wrong on this Mac, in one read-only list.** Failing schedules, open P1s on merged PRs,
  builds that are behind, low disk, doctor rows, the machine guard, and offers you have not answered. It adds no outbound
  call. A source that fails or times out is a row saying so, so "Nothing needs you here" means the list is empty.
- **Tools page and a ⌘K command bar in the Mac app.** An action goes preview, confirm, run, refresh, through a tested
  allow-list. The store build has no Tools page.

## 0.35.0 — 2026-11-01 — Packs: pick what you need, hear about the rest when it would help

- **`teyla features`: Teyla as a kit of ten packs.** Six automatic packs change settings, hooks or launchd jobs:
  `cost` (O1 to O4 and the context-budget hook), `load` (the machine guard and its recorder agent), `disk` (the
  simulator and sweep agents), `inbox` (O6 and prompt capture), `policy` (O5) and `daily` (O7). Four toolkit packs
  install nothing and name their commands: `security`, `design`, `ship` and `writing`. `teyla features` shows each
  one as on, partly or off; `on` makes its changes after showing them, `off` turns its switches off and undoes its
  O1 to O4 changes, `choose` records a checklist answer. `docs/FEATURES.md`.
- **`teyla start` opens with a checklist.** After the summary card, tick the packs you need; only their offers
  are asked, then the rest of each ticked pack. Packs already on, packs whose problem was seen, and on a first run
  `cost` and `inbox` start ticked. A pack left out and still off gets its plugin hook quieted
  (`guard.enabled = false`, `intent.enabled = false`) while the key is at its default. `--agent` adds `features`
  to the JSON, and AGENTS.md tells an agent to show it as one checklist.
- **Reminders when a problem shows up.** `teyla doctor` adds a `feature:<pack>` WARN when a pack is off and its
  problem appears: a kernel panic or CRITICAL load (`load`), a disk under 25 GB free (`disk`), token waste the
  last `teyla start` priced at $20 a month or more (`cost`), 3 or more unread questions (`inbox`). The
  session-start banner shows it once. `teyla features off <pack> --quiet` mutes it.

## 0.34.0 — 2026-10-28 — Teyla as an MCP server

- **`teyla mcp`: Teyla as an MCP server.** Any MCP client (Claude Code, Codex, Cursor) can now ask Teyla over stdio.
  Six tools, each one a call of the Teyla CLI in a child process: `teyla_asks` (what your sessions wait on),
  `teyla_answer` (send your answer to the session that asked; the description tells the model to send only text you
  wrote or approved), `teyla_intent` (your own words for a product), `teyla_load`, `teyla_routines` and
  `teyla_monitor`. Five only read. Nothing that changes state without your word is exposed: no `asks done`,
  `--record`, `--issues`, `--share` or `--model`. The protocol is implemented by hand (2024-11-05, 2025-03-26 and
  2025-06-18), so Teyla keeps zero dependencies; it opens no port. `teyla mcp --list-tools` prints the tools.
  The Claude plugin registers it in `plugin/.mcp.json`; for Codex run `codex mcp add teyla -- teyla mcp`. The OpenAI
  skills-only archive leaves `.mcp.json` out.

## 0.33.1 — 2026-10-27 — The settle lease knows which worktree a command runs in

- **The settle lease knows which worktree a command runs in.** 0.33.0 compared the hook's own directory, so two
  sessions that start in one directory and run `cd /worktree-a && xcodebuild` and `cd /worktree-b && xcodebuild`
  counted as one job and passed each other's lease. The hook now passes the command's `cd`/`pushd` target as
  `teyla load --admit KIND --cwd DIR`, and the lease keeps that directory's git worktree root, so a subdirectory of the
  same worktree still counts as the same job. A target the hook cannot know (`cd $VAR`, `cd -`) gets no exemption.
  `--wait` takes `--cwd` too.

## 0.33.0 — 2026-10-27 — The guard measures footprint, admits one heavy job at a time and sees simulators it did not admit

- **The guard counts physical footprint, not RSS.** RSS counts a shared page in every process that maps it, and misses
  what a process keeps compressed or in a VM. On 2026-10-27 two iOS simulators (454 processes) showed 18.4 GB of RSS, one
  sample 40.6 GB on a 24 GB Mac, while their footprint was 6.3 GB; Docker's `com.apple.Virtualization.VirtualMachine`
  showed 0.8 GB of RSS and 5.05 GB of footprint. So the alert and the `top` line blamed the wrong process.
  `teyla load` now reads `ri_phys_footprint` with one `proc_pid_rusage` call per process (about 5 ms for 1,200
  processes) and keeps the RSS for a process it cannot read (root-owned ones, other systems). The `load.tsv` column
  names are unchanged so `--replay` still reads old files; their values are footprint from this release on.
- **One heavy admission at a time.** Each waiter polled on its own. At 19:41:32 a build and at 19:41:39 a simulator, which
  had waited 35 and 16 minutes, were both admitted on the same OK reading, and the load went 90, 175, 205 on 10 cores
  within two minutes: a job just let in does not show in the counts until its processes appear. `--admit` and `--wait`
  now write a lease (`~/.teyla/guard-lease.json`) when they let a simulator or a build in, and a new simulator or build
  is refused for `guard.settle_s` (default 180; 0 = off) seconds after it: "a simulator was let in 40 s ago; waiting for
  it to settle". Deciding and taking the lease happen under one `flock`, so two waiters polling in the same second
  cannot both pass. The same worktree is not held by its own lease: a build and then its tests are one job.
  Lanes are unaffected. A broken lock or lease file lets the work through.
- **Simulators the guard did not admit are reported.** A pool script boots simulators with `xcrun simctl`
  inside itself, so the hook never saw it: a simulator booted at 19:45 during a CRITICAL hold and nothing
  recorded it. Each `guard tick` now compares the booted simulators (boot time from `ps` etime) with the admitted `sim`
  decisions in `guard-decisions.tsv`. One with no admission in the 5 minutes before its boot gets one `bypassed`
  decision row (once per UDID per boot), and `teyla load` prints "N simulators booted without the guard (UDID...)".
  The hour summary counts `bypassed` rows apart from admitted and refused ones, and they never start a hold.
## 0.32.1 — 2026-10-27 — A low disk gets the full sweep

- **The guard runs the full sweep when the disk is low.** Under `sweep_urgent_free_gb` (20 GB) free, the guard ran only
  the temp sweep. On 2026-10-27 that sweep removed 0 B for a day while the disk fell to 3.6 GB free, and a hand cleanup
  then freed 12 GB. Now the minute tick runs the full sweep at most every 6 hours and the temp sweep every 15 minutes
  in between. A full sweep that finds another sweep running is tried again 15 minutes later.
- **The sweep clears old app caches.** A new `app caches` category removes Playwright browser revisions older than the
  newest of the same browser, and app-update downloads (`*.ShipIt/update.*`, `*-updater`). Each one must be idle for
  `sweep_app_cache_days` (7) and used by no process. A revision that an installed Playwright still lists in
  `ms-playwright/.links` stays.
- **Under 10 GB free, whole caches go.** Below `sweep_critical_free_gb` (10), the sweep runs `npm cache clean --force`
  instead of `npm cache verify`, adds `deno clean`, and removes every Docker image no container uses, not only dangling
  ones. Docker volumes are never touched.

## 0.32.0 — 2026-10-26 — Where every product stands: the portfolio, an honest status, Teyla for iPhone and the App Store builds

- **`teyla portfolio`: each product's health, with the reason.** Each product gets one word (off track, at risk, on track or
  parked) and one line saying why, such as "iPhone build 15 is waiting for App Review" or "a question has waited 9 days".
  The rules are in `docs/APP.md`: off track when the primary platform is blocked or more than two days behind, a question
  has waited more than seven days, or a merged pull request has an open P1; at risk for any blocked or behind platform,
  a question older than three days, an unreviewed merge in seven days, or a building product with no session in fourteen.
  Each platform gets a line: version, build and state (live, in review, current, behind, blocked, no build). Pull requests,
  activity, spend and the next step sit beside it. `--refresh` asks TestFlight, Google Play and GitHub once and writes
  `~/.teyla/portfolio-cache.json` (mode 600); every other read, `teyla state` included, uses that cache. The snapshot
  contract is version 3.
- **The Mac window tells the truth about its data.** The green dot said "Live" whenever the last command returned, even
  while a product page was loading or after the Mac slept. The toolbar now says "Updating…", "Up to date" in a neutral
  colour, "Stale · N min" after two minutes, or "Offline" with the error in its tooltip, and "Sample data" for made-up
  data. Question cards are at most 720 pt wide, so "Needs you" reads at a glance. A Portfolio page lists every product with
  its health, platforms and reasons, with a "Needs attention" filter. A close that failed can be tried again.
- **Teyla for iPhone 0.32.** A Portfolio tab with the same health, platform lines and detail pages. Questions older than a
  week fold into "Older". An unsent answer survives the fold and a refresh. "See a sample" shows every screen with made-up
  data before pairing, and nothing is sent from it. App icon, privacy manifest (no tracking, no data collected) and an
  iPhone-only target.
- **A Mac App Store build.** The store requires App Sandbox, and a sandboxed app cannot run the `teyla` command. So the new
  `TeylaStore` target (`com.zaitsew.teyla`) is a companion like the iPhone app: it reads the signed iCloud relay folder,
  checks the signature before it decodes anything, and leaves signed answers. The full app built by `install.sh` is now
  `com.zaitsew.teyla.local` and copies its old settings once.
- **One script writes the App Store record.** `apps/store/app-store.py` (`status`, `push`, `screenshots`, `submit`,
  `--platform ios|macos`) writes the listing from `apps/store/listing/`. China mainland stays off, with the reason beside
  the setting. The age rating is 4+. The script refuses a field over Apple's limit or a model provider's name in the listing.
  The reviewer contact comes from the environment.
- **README: the chief of staff for a one-person software studio.** The README opens with what Teyla is for now, and has a new
  "Where every product stands" section and the iPhone and store companions under "The Mac app".

## 0.31.0 — 2026-10-25 — Start here: a diagnosis with undoable fixes, a dashboard, a Mac first run, setup by your agent

- **A README a stranger can act on, and a guide that holds the depth.** The README is 93 lines: the lockup, the one-line promise,
  a screenshot of the Start page, then the line to paste into Claude Code or Codex ("Set up https://github.com/zaitsew/teyla"),
  the install by hand (`uv tool install --python 3.12 git+https://github.com/zaitsew/teyla`, then `teyla start`) and a try-first
  `uvx` line. Four short blocks follow, each with the command that opens it: cost and waste, what waits on you, products and
  notes, one policy for every agent. Then the Mac app, privacy (the calls that can leave your Mac, with a link to the full table),
  undo and uninstall. Terms are defined where they first appear. `docs/GUIDE.md` is rebuilt by the same four blocks and keeps
  every section the old README and guide had, with new sections for `teyla start`, the daily screen, `teyla web`, the Mac app,
  products, notes, privacy and undo, and a list of every document. `tests/test_readme.py` parses every `teyla` command in both
  files with the CLI parser, checks each relative link and anchor, and keeps the README to 120 lines.
  The Mac app's "teyla not found" screen now shows the same pinned install command (not rebuilt in this change), and the `uvx` line in `AGENTS.md` pins Python 3.12 too.
- **Install by agent: fixes from a stranger's run.** Every install line pins `--python 3.12` (uv no longer picks a newer
  Python on a Mac with only 3.9; a download of about 25 MB may follow). `teyla start --agent` leaves out the closing line meant
  for a person at a terminal. `harness sync`, `harness status`, O6 and `doctor` share one "installed" test (the harness's
  home directory), so doctor prints no FIX for a harness it calls absent. O6 names the harnesses it hooks and installs the
  Claude Code plugin when it is missing; `teyla apply O5 --owner NAME` names the policy's owner; every offer carries
  `preview`. `doctor` says it writes files and makes one update check, calls a GitHub 403/429 INFO ("rate limit; try
  later"), finds Codex the same way in `tools` and `health`, and prints Setup before Machine. Counts agree with their noun.
- **`teyla web`: a local dashboard for the diagnosis, today, products and notes.** One command opens a page in your
  browser with five tabs. Start shows the diagnosis card and the seven offers, each with Apply (one confirm step that
  names the file and the key) and Undo (the message of `teyla undo` is shown, including the refusal for O5 to O7). Today
  is `teyla today`. Products lists stage, focus, waiting questions and notes, with a page per product (questions, notes,
  recent sessions and cost, repos). Notes adds, links and drops. Spend shows this week against last by day, model and
  product, with inline-SVG bars. It is a stdlib server on 127.0.0.1 with a random port, a per-run token that becomes an
  HttpOnly SameSite=Strict cookie, a Host allowlist, a token header on every POST, a strict content policy, and a stop after
  two hours idle. The diagnosis runs in the background, so the page opens with the last count. No npm, CDN or web fonts.
  `docs/WEB.md`.
- **An AI agent can set Teyla up from the repo URL.** `AGENTS.md` at the root tells an agent asked to "set up
  https://github.com/zaitsew/teyla" how to install it (`uv tool install git+https://github.com/zaitsew/teyla`, `pipx` as the
  fallback), run `teyla start --agent`, show the summary, and ask about each offer on its own before `teyla apply <id> --yes`.
  It lists what never happens without a yes (settings writes, hooks, launchd jobs, the policy), the undo commands, the
  common `teyla doctor` fixes and the Codex hook-trust step. `CLAUDE.md` sends an installing agent there and a contributor to
  `CONTRIBUTING.md`. `uvx --from git+https://github.com/zaitsew/teyla teyla start` runs the diagnosis with nothing installed.
  `tests/test_agents_md.py` parses every `teyla ...` command in the guide.
- **`templates/POLICY.md` is a 70-line generic starter.** It was the long policy of one person, with store-review, platform and
  release rules. The starter keeps the model ladder (markers for `teyla models --write-policy`), second opinions from another
  provider, "ask about decisions, not permission", merge only where allowed, the laptop as the gate, the price before anything
  paid, honest reporting and the session-end card, with `<placeholders>` to edit. It stamps `<!-- teyla-template: starter -->`.
  `teyla policy refresh` merges template changes only into a policy that carries the template's marker; a policy without one
  (written from the old long template, or by hand) is yours and is never merged, and `teyla doctor` says so. Nothing changes in an
  existing `~/.agents/POLICY.md`. `docs/GUIDE.md`.
- **Every network call is listed.** `docs/PRIVACY.md` has 21 rows, one per call: the command, the host, what is sent, whether it
  runs without a flag, and what safe mode does. The only call that carried session text, the model brief (`teyla state` sends up
  to 15 open questions to Anthropic through `claude -p`), is now opt-in. The update check stays on and sends only the version.
  library, `gh`/`ssh`/`curl`, a git remote operation, a model CLI, a release tool or the iCloud folder and is not in its
  allowlist, and when the allowlist and the table disagree.
- **The model brief is off for a new install.** A config with no `state.model_brief` key means off; turn it on with
  `teyla config set state.model_brief=true`. `teyla doctor` prints one line, "Model brief: on/off", with the command to switch it.
  Rule-based briefs are unchanged. An existing config that sets the key keeps its value.
- **`teyla doctor` accepts a `CLAUDE.md` that names `AGENTS.md`.** A link or an `@AGENTS.md` import now passes the
  `repos:agents-md` check; the two files no longer have to match text for text.
- **One promise.** `teyla.PROMISE` is the sentence in the welcome screen, in `AGENTS.md` and in the package description; a test
  keeps them equal.
- `docs/DIRECTORY.md` no longer names a version in the example archive names (`dist/` is untracked build output).
- **Mac: a first run that says what to do, and a page per product.** On a Mac where Teyla has seen no sessions, the window
  shows the lockup, the one-line promise and one button, "Run diagnosis". It runs `teyla start --json` in the background
  (a seconds counter; up to a minute on a large machine) and then shows the cost, the facts under it and each offer with its
  saving or benefit, its trade-off and its undo. "Apply…" opens one sheet that names the file and the key (or the command),
  then runs `teyla apply <id> --yes`; an offer whose undo is `teyla uninstall` says so there. "Diagnosis" stays in the new
  sidebar (Today, Diagnosis, Products). When `teyla` is not found, the window gives the exact install command with Copy,
  "Check again" and "Choose…" (the file is stored and tried first); the app asks a login shell (`/bin/zsh -lc 'command -v
  teyla'`) once before the fixed paths. Clicking a product in the questions, the Notes chips, the Products column or the
  sidebar opens its page: name, stage menu, focus star, primary platform, the questions waiting (answerable there), the
  notes with Link and Drop, the last 10 sessions and the spend over 7 and 30 days. Stage and focus call `teyla product set`.
  New: `teyla product show <id> [--json] [--quick]` is the page's data. `apps/mac/Tools/make_fixtures.py` regenerates the
  app's JSON samples from the real CLI. `docs/APP.md`, `docs/PRODUCTS.md`.
- **A first screen: `teyla` shows a welcome, `teyla today` the day, `teyla help` six groups.** Bare `teyla` used to end in an
  argparse error. It now prints at most 15 lines: the brand mark and version, the one-line promise, three live numbers (spend
  of the last 7 days at list price, questions waiting, notes in the Inbox) each with the command that opens it, and the next
  three commands, `teyla start` first until you have applied or declined an offer. Spend and questions come from
  `~/.teyla/first-screen.json`, refreshed in the background, so the call takes tens of milliseconds. `teyla today
  [--json] [--fresh]` is the daily screen (questions by product, the Inbox, the week against the week before, one suggested
  action by a written rule). `teyla --help` and `teyla help` list the commands in Start, Daily, Products, Spend, Setup and
  Advanced in under 40 lines; `teyla help --all` lists every one, and a test fails for a command without a group. An unknown
  command prints the nearest match and the help (exit 2); a missing package or unreadable `~/.teyla` file prints one line
  with the fix (`TEYLA_DEBUG=1` restores the traceback). `NO_COLOR`, `TERM=dumb` and pipes give plain text. `docs/TODAY.md`.

- **`teyla start`: diagnose your agent spend and fix it with one keystroke.** Reads the sessions on disk (no network, no
  write) and prints a card of at most 12 lines: the window's cost at list price, the share spent re-reading and storing
  context, sessions past 250k tokens, Opus's share of subagent cost, questions waiting. Then seven offers, each with its
  change, a saving range (or a benefit when no honest figure exists), the trade-off and the undo: O1 `autoCompactWindow`, O2
  `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, O3 a Haiku `scout` agent, O4 Codex `model_reasoning_effort=medium`, O5 `policy sync`,
  O6 `harness sync`, O7 `routine install`. `teyla apply` makes a change after a 0600 backup (atomic write, JSON order and
  indent kept) and logs it in `~/.teyla/changes.jsonl`; `teyla undo` reverts only the key it wrote, byte for byte when the file
  is untouched since, and stops when the key changed (`--force`). `teyla changes` lists them. `teyla start --agent` prints
  `{summary_text, diagnosis, offers}` for an AI agent to relay and applies nothing. Sessions now record the messages past 250k
  tokens (`Session.long_msgs`), lane units record usage, the explicit model and whether they wrote, and `pricing.cost_parts`
  splits a cost into input, cache write, cache read and output. The window is the last N local days and counts only turns
  inside it. O5 to O7 run the existing syncs as they are and are logged as commands; `teyla undo` points to `teyla uninstall`
  for them. `docs/START.md`.
- **Mac: quick note on a shortcut you choose, and Notes in the window.** A global shortcut (⌥Space by default, recorded in
  Settings, optional, never push-to-talk's ⌥⌘Space) opens a floating panel: type, ⏎ saves, ⇧⏎ adds a line, Esc keeps the
  draft. The product chip pre-selects from `teyla note --suggest` and changes in one click or ⌘0–⌘9. The window gets a Notes
  section (Inbox count, newest five, Link…, Drop). CLI: `teyla note --suggest "<text>" --json [--cwd DIR]` writes nothing and
  prints `{product, linked_by, candidates}`; `teyla note … --json` (also `link`, `drop`) prints the note. `docs/NOTES.md`,
  `docs/APP.md`, `apps/mac/README.md`.

## 0.30.0 — 2026-10-25 — Products you can trust: a registry, text notes, asks by product; a guard that watches memory

- **`teyla asks` files an ask under the product it is about, and shows the whole question.** A session that ran outside any
  repo, or in the wrong one, used to land under `unassigned` or another product. `registry.attribute()` now decides by `[assign]`,
  then the one product the session title names, then the repo of the session's PR link (the last PR is not always the
  subject), then the registered directory, then the one product the question names (only without a registered directory),
  then an unregistered checkout. `--json` adds `attributed_by`, and `teyla asks --why <id>` prints the rule and its evidence. `match_text` also takes
  hyphens as spaces and the display name. A question clipped to its tail now starts at its sentence, and a bare instruction
  gets the session title as its lead. `docs/PRODUCTS.md`, `docs/ASKS.md`.
- **`teyla asks` hides what never needed you: merged PRs and repeats.** An ask whose `pr` link points to a merged or closed PR
  (after the ask) is done, note `auto: PR merged <url>`; the state comes from the backlog cache, then `~/.teyla/pr-state.json`
  (30 minutes), then one batched `gh api graphql` query that only `teyla asks` runs and that fails quietly. Within one product,
  a `question` asked twice (same session and question, or a token Jaccard of 0.8 on 6+ words) collapses into the newest, which
  shows `(+N similar)` and `dupes: [ids]` in `--json`; when it is done, the repeats are done too (`auto: duplicate of <id>`).
  The listing ends with `filtered: N resolved (PR merged/closed), M duplicates — teyla asks --all`. New `teyla asks undo <id>`
  reopens one and keeps it from being closed again. `teyla state --json` (still version 2) adds `resolved` and `duplicates` to
  `totals`. `docs/ASKS.md`, `docs/APP.md`.
- **`teyla asks` groups by product, and a parked product stays quiet.** The default listing prints one header per product,
  `<name>  <n> waiting  [stage]`, with `focus` products first, then the oldest ask, and `unassigned` last; `--flat` keeps the
  old list. `--json` adds `groups`, `muted` and `muted_products` beside the unchanged keys, and `--html` gets the same headings.
  An ask in a `parked` product is left out of the list and of the session-start count, and the listing ends with `N muted in
  parked products (a, b) — teyla asks --all, or teyla product wake <id>`. `--all` or `--product <parked id>` shows them. A
  `blocked` ask, or one naming security, money or a release failure (`CRITICAL_TERMS`), is never muted and shows marked
  `parked`. `teyla state --json` (still version 2) adds `muted` to `asks[]` and `muted` to `products[]`, where `waiting` now
  counts unmuted asks only; muted asks rank last and stay out of the brief. `docs/ASKS.md`, `docs/PRODUCTS.md`.
- **Text notes (`teyla note`, `teyla notes`).** Quick ideas are kept as typed, linked to a product, and counted in the snapshot.
  `teyla note "text"` writes one event to `~/.teyla/notes/notes.jsonl` (append-only, 0600, under a flock) and prints its id,
  product, how the product was chosen and the first 60 characters. Without `--product` the product is the one the text
  names, else the registered product of the current directory, else `inbox`; an unknown `--product` is refused with the
  close names. `link`, `drop` and `undrop` are appended events that the reader folds. A note linked to a registered
  product is also added, as typed, to that product's `teyla intent` file; `link` adds it under the new product. `teyla
  notes [--product P | --inbox] [--all] [--json]` lists them newest first, and `teyla state --json` gains `notes:
  {inbox, by_product}`. Voice, shaping a note into a task and the Mac capture panel come later. `docs/NOTES.md`.

- **Product registry (`teyla product`).** The product of a session is no longer guessed from its working directory. A file,
  `~/.teyla/products.toml`, maps repos, extra paths and aliases to products, with a stage, a primary platform and a focus
  flag. A session resolves in this order: an `[assign]` correction for its session or ask id; the longest registered repo
  or path (worktrees map to their repo); an unregistered git checkout under `code_root` by its directory name; else
  `unassigned`. `(no repo)`, `(home)`, `(scratch)`, `unknown` and folder-name products are gone. `teyla product
  [list|init|add|set|park|wake|assign]` edits it: `init --write` adds the repos not yet registered and never overwrites an
  edit, `park` remembers the old stage for `wake`, `assign <ask-id> <product>` moves a session's questions.
  `registry.match_text()` finds products named in a text. `teyla state --json` `products[]` adds `id`, `display_name`,
  `stage`, `focus`, `primary` and `registered`, lists parked products with stage `parked`, and puts `unassigned` last.
  `docs/PRODUCTS.md`.
- **`teyla intent` stores only the owner's own words.** Two kinds of text the owner never typed had reached the store.
  The Claude desktop app files a subagent's final report as a user turn (`<agent-message from="...">`, opening with
  `[Subagent hand-back]`); both are now automated turns, in `intent` and, through `human_text`, in `teyla correct` and
  the monitor's human-turn counts. A `grok -p` review brief reached Grok's hook unwrapped; the hook now reads
  `session_kind` (`headless`) from Grok's session store, with `is_non_interactive` in `prompt_context.json` as the
  fallback. New `teyla intent clean [--dry]` re-checks every stored entry under the current rules, copies each changed
  file to `<file>.bak-<UTC time>` (0600) first, and rewrites file and index atomically under the store lock.
- **Plugin directory readiness (0.29.0).** The Claude Code plugin now carries the metadata, `LICENSE` and README the Claude
  directory checks (install line, a Privacy section that lists every path read and written and every network use). Every
  skill and command checks for the `teyla` CLI first and prints one install line when it is missing; hooks stay silent
  and exit 0. `session-start.sh` starts the CLI's daily chain only on a machine with `~/.teyla/config.toml`, so installing
  the plugin never installs launchd agents. Skill text no longer names private paths or products.
  `scripts/build_openai_plugin.py` builds the skills-only archive for OpenAI's directory; `docs/DIRECTORY.md` holds the
  listing text, data-handling answers and the submission checklist for both.
- **Plugin hooks pass the directory validator.** The hooks no longer reach `../src` or run inline `python3 -c` programs:
  `pre-tool-use.sh`, `capture-correction.sh` and `capture-intent.sh` run the installed package with `python -m teyla...`
  (from a checkout, set `PYTHONPATH=src`), `machine-guard.sh` needs the `teyla` CLI, and `context-budget.sh` runs the
  script at `${CLAUDE_PLUGIN_ROOT}/hooks/`. `session-start.sh --context-json` escapes its JSON in sh. The plugin ships
  `.claude-plugin/icon.png` (1024 px).
- **Decision log and replay.** Every `teyla load --admit` and finished `--wait` appends to `~/.teyla/guard-decisions.tsv`
  (time, kind, verdict, admitted or refused, reason, cwd, harness). `teyla load` ends with the last hour's counts.
  `teyla load --replay [--days N]` runs the verdict and the admission over `load.tsv`, per day.
- **The verdict follows the trend.** A new state, WORSENING, sits between BUSY and CRITICAL: the swap-out rate
  (`vm_stat`, now a column in `load.tsv`), swap growing faster than 4 GB per 30 min, or free disk on course to fall
  under `disk_crit_gb` within 30 min. While WORSENING, and for `guard.hold_min` (10) minutes after the last CRITICAL or
  WORSENING sample, a new simulator or build is refused whatever the count; running work and lanes are not touched.
  Swap used alone no longer makes the machine BUSY (it did on 70-95% of samples every day). `max_sims` and `max_builds`
  stay 2. `teyla load` prints the trend and the hold; `--replay` shows what the thresholds decide on the recorded days.

## 0.28.0 — 2026-10-18 — One analytics standard for every product

- **Analytics standard (`templates/analytics/STANDARD.md`, POLICY §14).** What a product measures, with which tool,
  and when it adds the next one. The tier follows `[productize] users`: `owner` counts from its own store through
  `./check.sh usage` and uses the platform's crash reports; `family` / `testers` add weekly active people and 7-day
  retention from the backend; `public` adds the store's analytics, one cookieless web tool and Sentry (EU); PostHog
  Cloud EU comes only with a written funnel question in `docs/ANALYTICS.md`. Events are allowlisted, carry no
  content, stay anonymous and set no cookie. The privacy policy and store labels change in the same PR.
- **`teyla probe-sql <ref> "<query>"`.** One read-only query on a Supabase project for a usage probe; the first row
  prints as `key=value`. It uses the Management API's read-only endpoint with `SUPABASE_ACCESS_TOKEN` or the Supabase
  CLI login, refuses a ref that is not 20 lowercase letters, and sends nothing in safe mode.

## 0.27.0 — 2026-10-17 — Teyla as the coordinator: one window on the Mac and the iPhone

- **Teyla for Mac, version 2 (`apps/mac`).** One window in the order you work: Needs you, Only you (the PRs and issues
  that wait on you), Done since yesterday, Products (issues, PRs waiting, the next step) and Running now. A Codex session
  takes a one-line correction from the window (`teyla say`); the other sessions open. ⌘N starts a new task
  (`teyla dispatch`). A mic on the answer, correction and task fields dictates on the device in English, Spanish or
  Russian (⌥⌘Space from anywhere); words typed while listening stay. One notification per new question. Window → Teyla
  (⌘0) reopens a closed window. Settings turn the iPhone relay on and show the pairing QR code.
- **Teyla for iPhone (`apps/ios`).** The same brief on the phone: Today, Products, New task. You answer by text or voice,
  correct a Codex session or start a task. The app holds no data of its own and talks to no server. Pair once by scanning
  the Mac's QR code; the key lives in the Keychain. It reads `state.teyla` from an iCloud Drive folder and shows nothing
  until the HMAC checks. A sent action shows "Waiting for the Mac", then the result, even after the Mac drops the
  question or the session. Simulator builds only: no TestFlight record exists yet.
- **`teyla state`: snapshot version 2.** Adds `tasks[]` (your open PRs in repos that are not merge-approved, with the
  review state, and issues assigned to you), `done[]` (sessions that ended a turn in the last 24 hours, from the desktop
  app's turn summary; a summary older than the transcript is ignored), product `issues`, `prs_waiting`, `next` and `repo`,
  and `relay`. Two clones of one GitHub repo are one product; two owners with one repo name are two (`alice/app`).
  GitHub data comes from `~/.teyla/state-backlog.json`, refreshed in the background. Contract in `docs/APP.md`.
- **`teyla answer`, `teyla say`, `teyla dispatch`.** `answer` closes a question only after the transcript shows your
  text; otherwise it says "started, not confirmed yet" and leaves the question open. `say <ref> -- <text>` corrects a
  running Codex session through `codex queue`. `dispatch <product> -- <text>` starts a task in a fresh worktree, by
  default through `codex-lane` behind the machine guard; `--dry` shows the plan. Both refuse in safe mode.
- **`teyla relay on|off|status|pair|sync`.** The Mac end of the iPhone link. A launchd agent writes the signed
  `state.teyla` and reads signed `outbox/` entries from an iCloud Drive folder: strict fields, constant-time HMAC, a time
  window, a size cap, and a journal so an entry is delivered once and an interrupted one is never retried. An answer never
  falls back to the clipboard. **Off by default; turn it on only when you pair a phone.** Not yet verified against a real
  iCloud folder and a real launchd agent. See `docs/RELAY.md`.
- **`teyla voice check <file> --chart <dir>`.** Checks a draft against a per-language voice chart (English, Spanish,
  Russian): sentence length, post length per format, banned phrases with stems, hashtags, emoji, exclamations. `--model`
  adds one tone pass. The chart schema is `templates/voice/VOICE.md`; your own charts stay outside the repo.
- **`teyla intent cover <plan> --product P`.** Says which of your own sentences a plan serves and which it leaves out, by
  content-word overlap in English, Spanish and Russian; `--model` settles what words cannot with one Haiku call. Exit 1
  while a sentence is unserved. Also: "can you tell me how…" counts as a request, a sentence wrapped over two lines in the
  plan is one sentence, and a long sentence goes to the model whole.
- **`teyla ux check [repo...]`.** A static audit of a product's UI code against `templates/design/STANDARD.md`: values
  typed into views instead of tokens, screens with too many tap targets, copy with "Please" or "!", a missing `DESIGN.md`.
- **`teyla asks done --older-than N`.** Closes every question older than N days (`--product P` for one).
- **Fixes.** Two tests no longer depend on the wall clock or on the machine they run on (the crash report window and the
  weekly digest). An apostrophe inside an inline list item of a voice chart (`[don't, can't]`) parses as text. On the
  iPhone, one tap sends one entry, and a refresh that began before re-pairing cannot show data signed with the old key.

## 0.26.0 — 2026-10-16 — What waits on you, and your own words

- **README rewritten as one page (about 1,100 words, was 5,800).** It now opens with what Teyla is, a seven-line quick start,
  and eight short sections led by `teyla asks` and `teyla intent`. The long explanations moved, not dropped: `docs/GUIDE.md`
  (install and update, spend, machine guard, harnesses, routines and checks, cloud sessions, the policy, the plugin, prior art),
  `docs/PRODUCTIZE.md` (section 6, the shipping commands and the `platform` / `productize` detail), `docs/WORK.md` (install with
  safe mode on) and `docs/HANDOVER.md` (handing Teyla to an agent). `teyla docs check` reports 0 FIX and 0 WARN on it.
- **`teyla asks`: every question an AI session left waiting on you, in one list.** It reads the Claude desktop
  app's session metadata, Claude Code transcripts, Codex rollouts, pending gated runs and due reminders (all
  read-only), joins a desktop session with its transcript, and lists the open ones by product, oldest first, archived
  sessions included, with the question verbatim (secrets scrubbed), a link that reopens the session and the options the
  agent offered. `done` / `snooze` keep state in `~/.teyla/asks.json`, a later reply closes an item by itself, and
  `--html` writes one self-contained page for your phone. Session start prints "N questions wait for you" from a count
  the daily routine and an hourly background refresh keep (the hook scans nothing). Also fixes the doctor check that
  looked for the gated-run inbox at `~/.teyla/inbox/*.json`; the store is `inbox.jsonl`. Details in `docs/ASKS.md`.
- **`teyla intent`: your own long prompts, kept word for word.** A `UserPromptSubmit` hook (`capture-intent.sh`,
  also wired into Codex, Grok, Cursor and Hermes by `teyla harness sync`) stores each typed prompt of 400
  characters or more in `~/.teyla/intent/<product>.md`, scrubbed, deduplicated, outside the repo.
  `teyla intent backfill --days 30` fills it from Claude Code and Codex transcripts, skipping prompts a script
  or agent wrote. `teyla intent [product]` lists, `teyla intent path <product>` prints the file, session start
  points at it, and the policy says a plan quotes the sentences it serves. No model, no summary: see `docs/INTENT.md`.
- **Writing contract, `teyla prose`, voice chart.** The policy gains "Writing and reporting" (`templates/POLICY.md` §13, a
  shortened §11 in the work variant): three registers, answer-first rules with a ban list, and a session-end card of at
  most 12 lines. `teyla prose [--days N] [--project S] [--json]` measures the replies a human saw (words, long
  sentences, ban-list hits, preambles) per harness and project, and the weekly digest names a median over 150 words.
  `templates/voice/VOICE.md` is a fill-in voice chart (EN, ES, RU sections); `templates/vale/` holds an optional Vale
  style (the sentence-length rule is untested). See `docs/WRITING.md`. `teyla policy refresh` meets a conflict if your
  POLICY.md already has a section 13: keep yours, then `teyla policy refresh --resolved`.
- **`teyla docs check [repo...] [--all] [--json] [--strict]`.** Reads a repo's README and `docs/` and names what to
  fix: no opening paragraph (or the scaffold's placeholder) is FIX; an opening over 60 words, no shell quick start in
  the first 80 lines, a README over 2,500 words (with its largest section), `teyla <sub>` commands the parser no
  longer has (Teyla's own repo), docs that read as decision history, and a doc marked spec or draft that the README
  presents as shipped are WARN. Exit 0 unless `--strict` and a FIX exists. The command table moved from the README to
  `docs/COMMANDS.md`, and `docs/reel.md` now says what shipped.

- **`teyla testflight --china`: no app stays available in China mainland.** The read-only check for POLICY §15 (store
  review): for each product with a TestFlight or App Store path it asks your release tool
  `availability --bundle-id ID --json` (the App Store Connect `appAvailabilityV2` /
  `territoryAvailabilities?include=territory` read, contract in `testflight.py` and `docs/MANUAL.md`) and prints one
  line per product still available in `CHN`, with the fix (exclude CHN in availability, app-wide). It prints nothing
  when none is; a tool that cannot answer is a line of its own, never a pass. `--quiet` runs it too and adds the lines
  to `~/.teyla/testflight.problems`, so the daily routine puts them in the banner and the digest. Teyla still never
  touches the key; the release tool has to implement `availability` first (`~/ops/bin/testflight` does not yet, so the
  daily banner will say it could not read availability until it does).

- **POLICY §12, store review — pass the first time.** A pre-submission checklist built from every App Store and
  Google Play rejection so far: China mainland excluded from the first submission (generative AI needs a Chinese
  permit; any app needs an ICP filing), no model provider named in the listing, a demo account and signed-out
  sample content so a reviewer reaches every declared capability, health data named in the UI and requested only
  with a screen that shows it, a reopenable Mac main window, a complete listing, Play's `targetSdk` /
  `versionCode` / Data safety / AI-report floor, and each rejection logged and generalised into the policy. The iOS
  `docs/RELEASE.md` template points at it and gains a review-history table. `teyla policy refresh` will meet a
  conflict if you already added the same section to your POLICY.md by hand: keep yours, then
  `teyla policy refresh --resolved`.

## 0.25.0 — Session Reel

- **`teyla update` keeps the `reel` extra.** An install with Pillow is reinstalled as `teyla[reel]` (and
  `teyla[work,reel]` with truststore), so a daily update no longer drops what `teyla reel render` needs.
- **`teyla reel list | story | check`.** A Claude Code or Codex session, plus the git history it produced, as a
  redacted, bounded **Story** (title, ask, at most a dozen beats, totals): the input of the video renderer that
  follows. `list` shows the last day's sessions with repo, span, commits and PRs; `story <id>` writes the Story as
  JSON; `check <id|story.json>` prints every string a reel would show and, by reason, how many were dropped
  (counts only, never the text). Beats come from the ask, sub-agent spawns, edits (with the most telling hunk),
  test runs, commits, `gh pr` commands and `codex-review` / `claude-review`; assistant prose and tool output beyond
  counts are never read into a Story. Redaction drops rather than masks: secret shapes (the ones `leak_check.py`
  knows, `NAME=value`, 32+ character runs) and private terms drop the beat, e-mail addresses and phone numbers drop
  the line, paths become repo-relative or `…/<basename>`, URLs become their host. A repo whose own name is a
  private term needs `--allow-repo`. No new dependencies; spec in `docs/reel.md`.
- **`teyla reel render`.** The Story as a vertical video: `reel.mp4` (1080×1920, 30 fps, H.264, no audio),
  `reel.srt` (one caption per beat), `story.json`, `reel.txt` (every string drawn, in order) and `contact.png`
  (nine keyframes). Large monospace type in the platform safe area, green and red diff rows, a session clock, a
  progress bar and live commit / test / PR counters; the clock runs in session time, not video time. Pacing and
  layout are pure functions (`reel/layout.py`); the renderer draws every string through one function that records
  it, and a test asserts each is in `reel.txt`. Optional extra `teyla[reel]` (Pillow) and `ffmpeg` on `PATH`;
  without them `render` still writes `story.json`, `reel.txt` and `reel.srt` and says what is missing. The Story
  gains `ticks` (numbers only) for the counters, the repo name is limited to 24 characters, and an ask is now cut
  at a sentence, never mid-sentence.
- **`teyla reel`: the Codex desktop `exec` wrapper is read call by call.** A `tools.write_stdin(...)` poll made inside
  the wrapper now settles the test run it names (a variable session id settles the only run still going), so a
  completed run is no longer left out of the test beats and totals; and a rejected `apply_patch` inside a wrapper
  that also runs a command is no longer shown as a successful edit.

## 0.24.0 — 2026-10-15 — Did the Android build reach a person

- **`teyla play` knows the account type and production.** The 14-day closed test is a rule of personal
  developer accounts only, and an organization account is common, so a `play` product on one could be
  reported behind for a requirement Google does not have. `[android] account = "personal" | "organization"` in
  `~/.teyla/platform.toml` (default `personal`, today's behaviour): for `organization` a missing or young
  closed test is never a problem, the "N of 14 days" wording is dropped, and the closed track is shown only
  when it has a release. `teyla play` now reads `production` too: a `completed` or `inProgress` release
  (with its rollout fraction) shows on the line and makes the closed-test requirement moot even for a
  personal account. An internal track older than production is a problem. Google's review state is not in
  the Play API, so a first internal release that is still a `draft` says "Play Console may show it in
  review; the API does not expose review state" instead of the generic wording; it still exits 1.

`teyla testflight` answered POLICY §11 for iOS and macOS; Android had nothing equivalent, and `teyla platform`
only checked that a Play Console account and a keystore existed.

- **`teyla play [PATH...] [--json] [--quiet] [--allow-network]`.** Asks your release tool
  (`[android] release_tool` in `~/.teyla/platform.toml`, run as `status --package ID --json`) about each
  product with a `play-internal` or `play` Android path, or `[release] android_package` in its `teyla.toml`.
  Prints the newest version code on the internal track with its release status, and whether a closed test is
  live and for how many of the 14 days Teyla has seen it (Teyla's own count, in `~/.teyla/play-seen.json`: the
  API gives no start date). A draft or halted internal release, nothing on internal, a `play` product without a
  live closed test, or a tool error is a problem and exits 1. It is a separate command rather than
  `testflight --platform android` because it has a different tool, key and verdicts, and no tester email.
- **`teyla play --quiet`** writes `~/.teyla/play.problems`; the banner and the weekly digest read it, and the
  daily routine runs it after `testflight`. An older `daily.sh` is regenerated. Safe mode needs `--allow-network`.
- **`teyla platform`** warns while `[android] release_tool` is unset, missing or not executable.

## 0.23.1 — 2026-10-14 — Forget a task removed on purpose

- **`teyla schedules forget KEY...`** removes a task from the schedules registry and its line from the
  problems file. A task deleted on purpose stops showing as VANISHED; every other problem line stays as
  the last full run wrote it.

## 0.23.0 — 2026-10-14 — A routine can be off on purpose

`teyla schedules` reported routines that the owner keeps off on purpose (a product's daily cycle, a paper
trading engine) as not loaded every day, next to tasks that had really died.

- **`paused = "2026-10-14: reason"` on a `[[routine]]`.** A paused routine shows as `paused` in
  `teyla routines` and DISABLED in `teyla schedules`, and is never a problem. If it is loaded anyway, it
  shows as PAUSED BUT LOADED, which is a problem: the declaration and the machine disagree. A malformed
  value is a manifest error naming the routine.

## 0.22.1 — 2026-10-14 — A quiet agent is not a stale one

- **`teyla schedules`** now counts the stamp a wrapper script writes on each start
  (`date ... > "x.last"`) as evidence that a launchd job ran. Teyla's simulator agent logs only when it
  shuts something down, so on the first live run it showed STALE although it had run minutes earlier.

## 0.22.0 — 2026-10-14 — Every scheduled task in one place, with proof it ran

The owner found that some scheduled tasks had not run and had quietly disappeared. Nothing in Teyla knew
they existed. Three Claude desktop tasks had a folder but no schedule record, so they never fired. Two
launchd agents had failed every run since their sign-in expired. A cloud routine had been switched off.
"Did it run?" had no record to answer from (POLICY §9).

- **`teyla schedules [--json] [--quiet] [--all] [--allow-network]`.** Reads launchd agents, Claude
  desktop scheduled tasks, cloud routines (from the RemoteTrigger calls in transcripts), GitHub
  `schedule:` workflows (scheduled runs only) and `teyla.toml` routines. It keeps a registry in
  `~/.teyla/schedules.json`, so a task that disappears shows as VANISHED instead of dropping out of
  sight. Each task gets a verdict: OK, STALE, FAILING, UNREGISTERED, MISSING DEFINITION, NEVER RAN or
  VANISHED, which are problems, or DISABLED, DONE or UNKNOWN. Vendor launch agents are ignored
  (`schedules.ignore_prefixes`).
- **`teyla testflight --quiet`.** Writes `~/.teyla/testflight.problems`. Both problem files feed the
  session banner and the weekly digest.
- **The daily routine runs both checks before it builds the banner.** An older `daily.sh` is
  regenerated.
- **POLICY §9 names `teyla schedules`** as the record to start from.
- **`teyla productize` R4** accepts Garmin distribution: `garmin-connect` and `connect-iq-store` count
  as public, `connect-iq-sideload` as dev-only.

## 0.21.0 — 2026-10-13 — One primary platform; a build is done when it reaches a person

A product built on iOS, Android and web from day one needed a parity sprint within two weeks, and the
other platforms kept falling behind the one the owner actually used. Builds were uploaded but did not
reach the owner's TestFlight, and a store approved a build far older than the one being tested. The
policy said nothing about which platform comes first or when a build goes out.

- **POLICY §11 — platforms and releases.** One primary platform per product. Every other platform needs
  a written, dated trigger. Secondary platforms catch up in parity trains, porting only settled features,
  and the train's brief is the diff since `synced-to` in `docs/PARITY.md`. A secondary nobody opened in 30
  days is frozen. A build counts as done once the owner can install it, with at most one internal upload
  per app per day. After the first public release, one version is in review at a time and the store
  stays within two weeks of the build the owner uses.
- **`teyla productize` R10 "platforms".** `[productize] primary` plus a dated `[productize.triggers]`
  entry for every other platform (`android = "2026-01-15: a named tester has no iPhone"`). R10 applies
  to every target, including owner-only products, and an unmet R10 becomes an agent step.
- **`teyla testflight [PATH...] [--json]`.** Asks your release tool (`[apple] release_tool`,
  `beta reached --json`) whether `[apple] tester` can install the newest build of each product
  (`[release] apple_bundle_id`). It prints one line per platform with the reason each newer build
  can't be installed. It exits 1 when any platform is behind, so a routine can gate on it. Safe mode
  needs `--allow-network`.

## 0.20.3 — 2026-10-12 — Opus creeping into build lanes is visible

On 2026-10-12 a usage review found that `teyla spend --by-day` lumped Opus 5.5 and Sonnet 5.5 subagent cost
into one "volume" column: both are the volume tier, so a build project running 37 of its 90 lanes on Opus at
about twice the cost looked the same as one running on Sonnet. Telling whether a model's lanes find more or
fewer review P1s took two throwaway scripts.

- **`teyla spend --by-day` splits subagents by model family.** The columns are Opus, Sonnet, Haiku, Fable and
  other (cost/calls), followed by the top-tier share and a new Opus share (Opus subagent dollars over all
  subagent dollars). The JSON rows carry `families` and `opus_share` in place of `tiers`.
- **`teyla lanes [--days N] [--project SUBSTR] [--json]`** prints one row per (subagent type, model): units,
  median turns, median peak context, median and total dollars, and from the review ledger the units matched to
  a review, P1 per matched unit and units with at least one P1. A lane is matched when its transcript holds a
  commit sha a later review covered. The footer says P1 per unit is confounded by task difficulty.
- **The digest names an Opus share over `spend.opus_share_max`** (default 0.25, over the last 7 days):
  "Opus ran X% of subagent cost (N lanes); POLICY: Opus only with a stated reason", step `teyla lanes --days 7`.
  Under $1 of Opus cost it stays quiet.

## 0.20.2 — 2026-10-12 — a seen model is not an adopted model

Haiku 5.5 shipped on 2026-10-07 and was acknowledged with `teyla models watch --ack` the next day. The
Saturday weekly then said "new models: none", and the list of repos still calling Haiku 4.5 went to a
report file with no reader. Acknowledging a model said it was seen; nothing said it was not yet used.

- **The digest names the adoption gap.** `teyla models watch` keeps its live superseded rows in
  `~/.teyla/state/models-watch.json`, and the digest shows `models: N file(s) in M repo(s) still name
  superseded ids: old → new` until a scan finds none. A scan older than 14 days is ignored.
- **PRICE-STALE reads versions correctly.** A dated variant needs a date suffix: `claude-opus-5-5` is no
  longer a dated `claude-opus-5`, which had flagged Opus 5 against Opus 5.5's price.
- `pricing.py` prices `claude-haiku-5-5` ($0.10/$0.50 per 1M up to 100K prompt tokens; the 5x card above
  that is not modelled).

## 0.20.1 — 2026-10-11 — the guard stays installed, and watches the disk

On 2026-10-10 a test in Teyla's own suite reached the real `~/Library/LaunchAgents`: it rewrote the daily
wrapper with a fake binary path and deleted the guard, simulator and sweep agents. Doctor said FIX every
morning; nothing acted. On 2026-10-11 the Mac went from 16 GB to 1 GB free in one morning of agent work and
hung without a panic report — APFS swap shares the disk, so a full disk and a memory hang are one incident.

- **Tests can no longer touch launchd.** A suite-wide fixture moves every launchd path of `routine_install`
  and `control.triggers` into tmp, refuses an unstubbed load or unload, and fails a test that runs a
  launchctl verb that changes launchd.
- **`teyla routine catch-up` repairs the routines.** Run by the daily wrapper and at every session start, it
  first runs `routine install --if-stale` and logs `REPAIR:` lines: an agent whose plist vanished is back
  within one session. The job it runs inside is never booted out (that would end the repair), and wrappers
  are written by rename, since bash reads a running script by offset.
- **Free disk is part of the machine guard.** `teyla load` reports it; under `guard.disk_warn_gb` (25) the
  verdict is BUSY, under `guard.disk_crit_gb` (10) CRITICAL — heavy work is refused, the alert and
  notification fire. `guard tick` runs the temp sweep itself under `[storage] sweep_urgent_free_gb` (20), at
  most every 15 minutes. `load.tsv` records the free disk for `teyla crash`.

## 0.20.0 — 2026-10-09 — machine guard: agents stop overloading the Mac

On 2026-10-09 a 24 GB Mac kernel-panicked (panicked task `simctl`) while dozens of agent sessions each
booted simulators and ran builds in parallel: swap 11+ GB, compressor ~12 GB, load in the hundreds. Each
agent saw only its own task. This release gives the machine one view of itself and puts it in front of
heavy work.

- **`teyla load`: how loaded the Mac is, from one `sysctl` and one `ps`.** RAM, swap, compressor, memory
  pressure, load per core, booted simulators, builds and their compilers, Gradle/Kotlin daemons, agent
  sessions and headless lanes, Chrome, VMs, top apps. A verdict OK / BUSY / CRITICAL with every reason's
  number and threshold (`[guard]` in config). Swap counts as critical only while there is memory pressure,
  because swapped pages linger after a machine recovers. `--admit build|sim|lane` is the admission check
  (fails open), `--wait --kind KIND` blocks until a slot is free, `--record` appends to
  `~/.teyla/load.tsv`. Doctor shows `machine:load`.
- **The machine-guard hook refuses heavy commands on an overloaded Mac.** A PreToolUse hook (Claude Code,
  Codex, Grok) sends `xcodebuild`, `swift build|test`, Gradle tasks, `cargo`/`bazel` builds,
  `simctl boot|create|clone`, and headless lanes (`codex exec`, `codex-lane`, `codex-review`,
  `claude -p`, `grok -p`) to `teyla load --admit`; a refusal tells the agent why and what to do instead
  (reuse a booted simulator, `teyla load --wait --kind … && <command>`). Ordinary commands cost ~3 ms and
  no Python; quoted text is never a command. It fails open; `TEYLA_GUARD=0` or `guard.enabled=false`
  switch it off. Codex runs it after you trust it once.
- **`teyla guard tick|status` and the `com.zaitsew.teyla.load` agent.** Every minute (opt-in:
  `teyla config set guard.agent=true && teyla routine install`): record a load row, keep
  `~/.teyla/load.alert` while CRITICAL (the session-start banner shows it first while fresh), one macOS
  notification per incident, and stop Gradle/Kotlin daemons idle for `guard.gradle_idle_min` (30) with
  no build running — identified by their main class, re-checked right before the signal.
- **`teyla crash`: what happened and what the machine looked like before it.** Kernel panics (real time
  from the report, panicked task, compressor, last kext), watchdog resets and jetsam events from
  DiagnosticReports, each panic with the load rows of the 30 minutes before and the nearest jetsam's top
  apps, and advice computed from those numbers. An unacknowledged panic makes doctor WARN `machine:crash`
  (so the banner shows it) and heads the weekly digest; `--ack` marks it seen.
- **Policy §10: one machine, a budget.** The template tells every harness to check `teyla load` before
  heavy work, wait instead of retrying, reuse and shut down simulators, stop Gradle daemons, and read
  `teyla crash` after a crash. `teyla update` merges it into your `POLICY.md` three-way.

## 0.19.4 — 2026-10-08 — `teyla lang` reads translated prose correctly

- **`teyla lang` ignores quoted labels in English prose and flags a stale clone.** In a comment or doc line,
  non-Latin text inside quotes, or a non-Latin word on a line that is otherwise English prose (3+ Latin words),
  is no longer a finding; mostly non-Latin lines, strings and fixtures count as before. A repo whose HEAD is behind
  its upstream (refs as they are, never a fetch) gets one warning line, plus a `behind` field and a `stale` list
  in `--json`.

## 0.19.3 — 2026-10-08 — localization exempt, Stop hook reads the PR head, quieter models watch

- **`teyla lang` no longer reports Android and string-catalog localization.** Android resource
  qualifiers (`**/res/values-*/strings.xml`, `plurals.xml`, `arrays.xml`) and `**/strings/*.json`
  catalogs are exempt by default. The per-repo exemption list is `.teyla/lang-allow` (globs, any
  depth); `[lang] allow` in config applies to every repo. Both are now spelled out in
  `teyla lang --help` and the README.
- **The cloud Stop hook checks the PR's head.** With an open PR, "pushed" means HEAD is inside the
  PR's head commit (fetched by branch, or by sha for a fork PR), so an upstream that holds HEAD while
  the PR branch is behind no longer lets a session stop with commits missing from the PR. If GitHub
  cannot say which commit the open PR carries, the stop is refused once. Without `gh` or an open PR
  the ref-based count is unchanged. Repos prepared earlier get it on the next `teyla cloud prep`.
- **`teyla models watch` lists only live code and config as superseded-id usage.** Tests, price
  tables, docs/changelogs and migrations are counted on one line as history; `--json` keeps them
  under `superseded_history`.

## 0.19.2 — 2026-10-08 — cloud prep keeps AGENTS.md passive

- **`teyla cloud prep` no longer puts a session-ending checklist in `AGENTS.md`.** The file is read
  by every model run in the repo, including headless one-shot calls a product makes itself; a
  `grok -p` probe followed the "Done, in a cloud session" steps, took twice as long and broke the
  repo's tests. The Shipping section is now passive policy (merge-approved, one PR per unit,
  merge-not-squash, no force-push, the gate line) with a line saying it is not a task; the done
  steps (push, PR, `needs-mac`, second opinion, merge when approved) moved to
  `.claude/rules/cloud.md`, which applies only when `CLAUDE_CODE_REMOTE=true`. `teyla cloud check`
  warns on a repo that still carries the old heading; re-running `teyla cloud prep` replaces the
  section in place.
- **`teyla cloud prep` titles a new `AGENTS.md` with the repository's name** (the origin remote),
  not the name of the git worktree directory it was run from.

## 0.19.1 — 2026-10-08 — `teyla reviews` against the real GitHub and ledger

- **`teyla reviews` failed on every repo**: `gh pr list --json commits` also fetched each commit's
  authors and went over GitHub's GraphQL node limit. It now runs one search per repo that asks only
  for commit ids, newest first.
- **The ledger is read as the review scripts write it**: modes with a detail after `:`
  (`branch:<paths>`, `skip:<why>`), `diff-file`, reviews that name no commit, and skips that name
  the PR by URL (that owner's PR only). A logged skip now outranks an open P1.

## 0.19.0 — 2026-10-08 — the chores that were left: RAM, markdown, language, review debt, updates

- **`teyla storage procs`.** Dev processes an agent left behind (`xcodebuild`, `swift-build`,
  node/vite/next dev servers, `python -m http.server`, supabase) whose working directory sat in a
  worktree or temp folder that is gone: pid, RSS, age, why. Yours only, no terminal, running at
  least `storage.orphan_min_age_min` (30); patterns (`storage.orphan_patterns`) see the executable
  or the interpreted script, never other arguments. `--kill` sends SIGTERM, then SIGKILL after 10 s,
  each signal only after a start-time check and a kqueue exit watch. `storage.orphan_kill=true`
  (off by default) lets the sims agent do it every 10 minutes; `teyla storage` and doctor report the
  RAM held.
- **`teyla tidy`.** Junk in the rule and memory markdown: exact and near duplicates (also across
  POLICY.md and CLAUDE.md), dead `@` imports and links, memory files missing from the index, files
  over `tidy.max_kb`, whitespace, non-English prose in a repo file, dated "for now" lines older than
  `tidy.stale_days`. Read-only by default; `--apply` fixes only the mechanical part after a backup in
  `~/.teyla/tidy-backup/`, and never touches code fences, `<!-- teyla:protect -->` regions or blocks
  Teyla writes. The weekly routine files `tidy.md`; a `tidy` skill joins the plugin.
- **`teyla lang`.** Non-Latin text (Cyrillic, CJK, Greek, Arabic, Hebrew) in tracked files and
  recent commit messages, per repo and kind (doc, comment, string, fixture, commit). Exemptions use
  `.leak-allow` exactly as the leak guard does, plus `[lang] allow`. Weekly, with one digest line.
- **`teyla reviews`.** The review debt: merged PRs of the last N days against the review ledger
  (`review.ledger`), counted per repo as reviewed, merged with an open P1, skipped, exempt or
  unreviewed. Weekly, and the digest carries the totals line while the debt is above zero; a failed
  `gh` query keeps last week's summary instead of reporting zero.
- **Safe mode can update itself.** `safe.auto_update = true` lets the daily routine run `teyla
  update --quiet`; only that command reaches the network, and a pin still wins. The banner says when
  the plugin hooks lag the CLI. `prompts/work-account-update.md` turns it on.
- Re-run `teyla routine install --if-stale` to pick up the new weekly lines (`tidy`, `lang`,
  `reviews`) and, on a safe-mode machine with auto-update, the daily update line.

## 0.18.0 — 2026-10-08 — shareable, and the chores that were scripts

- **The repository is meant to be shared.** Docs, prompts, templates, fixtures and comments no
  longer name one owner's products, people, places or paths, and everything is in English (the
  correction-phrase word lists a feature needs moved to `src/teyla/lexicon.py`). `teyla scaffold
  --owner "<name>"` fills the LICENSE templates. The CI template is `workflow_dispatch` on ubuntu.
- **A leak guard.** `scripts/leak_check.py` scans the tree (part of `./check.sh`), a commit range
  (messages, author and committer, every added line including merge resolutions) and a PR body
  (`--text`). Private terms live outside the repo in `~/.config/teyla/private-terms.txt` or
  `$TEYLA_PRIVATE_TERMS`; emails, home paths, secrets and non-English text are found without a
  list. `.githooks/pre-push` asks the destination which commits it already has and scans the rest;
  enable it with `git config core.hooksPath .githooks`. Exceptions go in `.leak-allow`.
- **`teyla models watch`.** Compares the provider catalogues with a known list
  (`~/.teyla/models-known.json`, `--seed` from a file, `--ack` to accept), names new models and
  greps configs and rule files for ids that a newer model superseded. The weekly routine runs it
  and the digest carries one line.
- **Spend budgets.** `spend.alert_session_usd`, `spend.daily_budget_usd` and
  `spend.budget.<project>` write `~/.teyla/spend.alert`, which the session-start banner shows; an
  alert repeats only after the spend grows another 25%. Advice A20 flags a day where the
  orchestrator model did most of the volume work (`spend.a20_models`, `a20_share`,
  `a20_min_calls`). `teyla spend --by-day` and `--no-write`.
- **`teyla storage sims` and `teyla storage sweep`.** Idle booted simulators are shut down;
  devices matching `storage.sim_prune_pattern` (empty by default: nothing is deleted) are deleted
  once nothing inside them changed for `sim_prune_days`. The sweep removes what agents leave
  behind (temp builds, release leftovers, DerivedData nothing wrote to and whose package checkouts
  are clean, runtime and package caches, dangling and superseded Docker images, archived
  sessions, oversized routine logs), each with its own age and process check; `--dry` reports
  bytes only. Optional LaunchAgents behind `storage.sims_agent` and `storage.sweep_agent` (off by
  default). The doctor summary carries the free disk space.
- **Policy sync keeps hand edits and runs daily.** Generated harness files are fingerprinted; an
  edit made by hand is filed in `~/.teyla/policy-inbox/` before sync overwrites it. `teyla policy
  inbox [--done NAME | --all]`, a doctor WARN, and `teyla policy sync --quiet` in the daily
  routine (unattended: never creates POLICY.md, never edits `~/.claude/CLAUDE.md`).
  `harness.disabled` takes the harnesses you do not use. `teyla uninstall` keeps unreviewed edits.
- **No one owner's layout in the defaults.** Run reports go to `runs_root` (`teyla config set
  runs_root=...`), by default `<ops_root>/runs`; an install that already has its reports in the
  older tree keeps using it. `release_tool` has no guessed default: doctor says it is not
  configured and where to set it. `teyla scaffold` fills the registry owner in the deploy
  compose fragment. The model ladder in the policy templates is marked as an example.
- **The work-account prompt targets 0.18.0.** `prompts/work-account-update.md` and `docs/WORK.md`
  pin, install and add the plugin at 0.18.0.

## 0.17.0 — 2026-10-07 — what agents leave on disk, and routines that fail quietly

- **The work-account prompt targets 0.17.0.** `prompts/work-account-update.md` pins, installs and
  adds the plugin at 0.17.0, and `docs/WORK.md`'s update example follows. Step 9 no longer says the
  hook defaults are 300k/40k; its explicit 240k/30k line now only overrides an older setup's values.
- **A routine that runs and fails is FAILING, not ok.** A failing run still touches its log, so
  mtime alone called it fine: a sync routine in a product repo failed every 30 minutes for hours
  while `teyla routines` reported nothing not running. For a `.jsonl` log Teyla now reads the last
  run's outcome (dry runs ignored) and reports FAILING with the streak's start, length and first
  error line. FAILING counts as not running in the exit code, digest, banner and feedback.
- **Self-ignoring caches are not work.** mypy, ruff and pytest write a `.gitignore` of `*` inside
  their cache, so git listed the files inside (`api/.mypy_cache/3.12/`) and `teyla storage` kept
  every finished Python worktree as holding "ignored files that are not build output". A cache
  counts only when its own `.gitignore` really ignores everything in it.
- **`teyla storage` finds Xcode DerivedData whose workspace is gone.** Agents build iOS apps in
  throwaway worktrees (`~/.worktrees/app-a/build-1/App.xcodeproj`); `storage clean` removed the
  worktree and left its `~/Library/Developer/Xcode/DerivedData/<Scheme>-<hash>` behind, hundreds of
  megabytes each, listed only as one REVIEW row for the whole directory. Now a folder whose
  `info.plist` names an absolute `WorkspacePath` that no longer exists, and which nothing has touched
  for a day, is its own SAFE row ("its workspace is gone: …") while no `xcodebuild`, Xcode build
  service or Xcode runs (a build writes deep inside, where no mtime the scan reads moves): counted
  in `safe`, listed in `--json` under `derived`, removed by `clean --apply` and `clean --auto` after
  the same facts are checked again. Folders without an `info.plist` (`ModuleCache.noindex`,
  `SDKStatCaches.noindex`, …) are shared caches and stay untouched, as does a workspace on a volume
  that is not mounted.
- **Compaction at ~300k, read from the machine.** Replaying real sessions showed that moving
  `"autoCompactWindow"` from 400000 to 335000 (compaction at ~300k instead of ~365k) and the handoff
  reminders of a context-budget hook to 240k/270k cut re-read context by roughly a tenth at the cost
  of more frequent compactions; 250k compacted mid-task too often. A3, A4 and W2 no longer print a
  fixed 400000/~365k: they read `autoCompactWindow` from `~/.claude/settings.json` (compaction ≈
  window − 35k) and, when it is absent, recommend 335000 (~300k). `teyla doctor` suggests 335000, and
  warns (`hooks:context-budget-late`) when `context_budget_first` is at or past the point the window
  compacts at, since the handoff would then come after the compaction it is for. The plugin's
  context-budget hook defaults to 240000 / 30000 and its reminder names where this machine compacts.
  The work-account prompt sets those thresholds explicitly (0.16.0's defaults are 300k/40k) and
  merges in 335000.
- **A10 counts writes to `~/.claude/CLAUDE.md`, not mentions of it.** A Bash call counted when
  it named the path anywhere and wrote anything anywhere, so a session that edited a hook, a PR
  body and a changelog naming the file was reported as six edits to it (A10 [high]) though the file
  had not changed since the ack. Now the path has to be the target: a redirect into it, the operand
  of `sed -i`/`tee`/`perl -i`, the last operand of `cp`/`mv`, or a literal (or
  `Path.home()/".claude/CLAUDE.md"`) that a script writes. Edits to a repo's own
  `.claude/CLAUDE.md` no longer count either. Replayed over weeks of transcripts, the hits that were
  dropped were reads and mentions.
- **A11 reads annotated ladder cells.** `Sonnet 5.5 (default worker), Opus 5.5 (hard sub-tasks,
  design, same-provider review)` was split at every comma, and the pieces — `design`,
  `` `codex exec` lanes `` — came back as LADDER-UNKNOWN for a ladder whose every model
  exists. Commas inside parentheses and backticks no longer split, text after ` — ` stays with
  its entry, and the annotation is stripped only for matching, so `--write-policy` keeps it.

## 0.16.0 — 2026-10-02 — a personal machine's habits, on a managed work laptop

Three practices lived only in the author's private scripts, so a managed work laptop (the
Claude Code desktop app, no `claude`/`gh`/`codex`, a self-hosted forge such as GitLab, safe mode,
plugin pinned to a tag) had none of them. They now ship in the plugin and arrive pinned with it. The
two hooks are opt-in, off by default: on a personal machine the private copies already run, and two
would double every note.

- **Context budget** (`[hooks] context_budget = true`). At 300k tokens of context
  (`context_budget_first`) and every 40k after (`context_budget_step`), the model writes a
  handoff — state, open work, decisions, next steps, file paths — to `~/.teyla/handoff/` (0700)
  and keeps working; after Claude Code compacts the session (`"autoCompactWindow": 400000` in
  `~/.claude/settings.json`: about 365k), the handoff is put back into the context once and
  renamed `.prev.md`. Wired on UserPromptSubmit, PostToolUse and SessionStart(compact). It runs
  after every tool call, so the wrapper decides on/off with one `awk` and starts no Python when
  off; when on, it uses the installed `teyla`'s interpreter (a GUI app has no shell PATH), else a
  `python3` that will not pop the developer-tools dialog. Ported from a private context-budget hook
  whose measurements were: a turn at 450k costs about 9x one at 50k, and in a heavy week that
  re-reading was a large share of the total cost.
- **Land check** (`[hooks] land_check = true`). A Stop hook, once per session: uncommitted files
  or commits on no remote (`git log HEAD --not --remotes` — without `HEAD` a never-pushed repo
  reads as pushed) are named with how to land them: one PR/MR per logical unit; "merge it —
  merge, not squash, never force-push" only when origin's slug (ssh or https, nested groups
  whole) is in the fenced `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md`, else "open the
  PR/MR and STOP". A bare `owner/repo` approves github.com only; another host's repo needs its
  host in the entry (`git.example.com/group/repo`). Never a block. Pure `sh` (a work laptop may have no
  Node). `teyla harness sync` wires it into Codex's `~/.codex/hooks.json` as a Stop hook
  (`land-check.sh --codex`, `{"systemMessage": …}`) while the key is on, and removes it when off.
- **`/teyla:review`**: POLICY §2 without any CLI. One pass on the branch's diff (or one fix
  commit in round two), P1/P2 only, `P1 path:line — defect — scenario` or exactly `No P1/P2`;
  a `codex-review` or `claude-review` script on PATH when present, else one fresh sub-agent given
  only the diff, labelled "same-provider review". At most two rounds. Synced to Cursor, Codex, Grok
  and Hermes as `teyla-review` (six skills per harness now).
- **`teyla doctor`**: one INFO line per hook that is on; with the context budget on and no
  `autoCompactWindow` in `~/.claude/settings.json`, a WARN naming `/config` or the key to add.
  Doctor never writes settings.json. `teyla policy init --force` keeps `[hooks]`.
- **Docs**: `docs/WORK.md` gains a section on the habits a personal machine already has;
  `prompts/work-account-update.md` targets 0.16.0 and adds the step that turns the hooks on,
  merges `autoCompactWindow` into `~/.claude/settings.json` (after a backup) and checks
  `/teyla:review` is listed.
- **Fast stays a per-session choice.** `teyla health --live` runs its Codex probe with
  `-c service_tier="default"`, so an interactive Fast setting (the 2.5x "priority" tier) never
  reaches automation; a `codex-review` script and a Codex lane wrapper should pin the same tier.

## 0.15.0 — 2026-10-02 — Codex reads the user's global rules, the work plugin follows the pin

- **Codex and Grok get the user's global rules, not only the policy.** `~/.claude/CLAUDE.md` — the
  merge-approved repos, shipping, releases, layout, git safety — reached Claude Code only:
  Codex has no `@path` imports (codex-cli 0.159.2), so a symlink to `POLICY.md` left every
  Codex session without the merge list. `teyla policy sync` now writes `~/.codex/AGENTS.md` and
  `~/.grok/AGENTS.md` as one generated file: `POLICY.md`, then CLAUDE.md under a heading for the
  user's own rules (the policy import dropped, other `@~/...` imports inlined one level, fenced ones
  left as examples), then where the shared project memory lives. The Cursor skill carries the same
  text, and the work policy gets the same treatment.
  - A CLAUDE.md with nothing but the import keeps the symlink, exactly as before.
  - The first line is a generated-by marker. Sync replaces a symlink or a marked file; a
    hand-written `AGENTS.md` is still skipped. An invisible character in CLAUDE.md or an
    imported file refuses the whole sync before any write. Over 32 KiB, sync prints a WARN.
  - `teyla doctor` says why a copy is stale ("~/.codex/AGENTS.md is older than
    ~/.claude/CLAUDE.md"); `teyla uninstall` removes a marked file as it removes the symlink.
- **The session-start hook keeps the copy fresh.** When CLAUDE.md or POLICY.md is newer than a
  generated `AGENTS.md`, it starts `teyla policy sync --quiet` (new flag: only SKIP/WARN lines)
  in the background, safe mode included: the sync is offline.
- **Codex sees Claude Code's project memory.** In `--codex` mode the hook prints the first 40
  lines (at most ~4 KB) of `~/.claude/projects/<key>/memory/MEMORY.md` for the session's repo,
  a worktree mapped to its main checkout, and the generated `AGENTS.md` says how to add a
  memory in the same format.
- **Safe mode pins the plugin to the CLI's release.** With `update.pin` set to a version, the
  plugin's marketplace is added as `zaitsew/teyla#v<pin>`, so the hooks that run at every
  session start and before every tool call are never newer than the pinned CLI. `teyla plugin
  install|refresh` and doctor's `plugin` FIX print `marketplace remove` + `add ...#v<pin>` +
  `install` instead of `marketplace update`, which pulls main. Doctor's new `plugin:pin` WARN
  fires when `known_marketplaces.json` shows the marketplace following another ref (or main), and
  when the pin is a commit sha: Claude Code pins a marketplace to a branch or tag, not a commit.
  No pin, or safe mode off: unchanged.
- **`docs/WORK.md`**: Teyla on a work laptop. What safe mode guarantees, the five steps to a new
  release, the daily commands, and what never happens. `prompts/work-account-update.md` now
  targets 0.15.0 and installs the plugin at `#v0.15.0`.

## 0.14.0 — 2026-10-01 — rules that live and die, health that tells the truth

- **`teyla spend`: the week's cost and the waste in it.** Claude Code cost is one
  usage per message, subagents included, with 1-hour cache writes at 2x. The Friday digest gets a
  spend section, and `teyla spend --alert` is a daily spike check. With admin keys in the macOS
  Keychain (`openai-admin-key`, `anthropic-admin-key`, read at call time, never written), it also
  reads what OpenAI and Anthropic actually billed for product API use. A day past 2x the
  previous week's median and at least $2 over is W7, reported apart from session waste. Safe mode
  skips the providers.
- **Harness health: the newest event wins.** `health:hermes` said "relogin required" after a
  successful re-login; a later success now clears an older auth error, and a later
  quota error (Hermes' 403 `spending-limit`, read from its request dumps) replaces it as what it is.
  Claude's errors are kept per entrypoint, and a live `claude auth status` clears the CLI's and
  `claude -p`'s auth errors, not the desktop app's. Hermes' failed-request stub rows no longer
  count as a success. An API-key Hermes setup is OK when a key exists, and FIX when one does not.
  Codex rate-limit-only `token_count` events no longer clear A18. Two YAML parser fixes cover
  `hooks_auto_accept` inside a flow mapping or after a block scalar, and a bare `-` hook entry.
- **The other review findings deferred from 0.13 are fixed** (the cloud and health ones are above and below):
  - A refused act no longer uses up the approval.
  - Old correction records no longer match by scrubbed path.
  - A10 compares dates in one timezone, and nothing is marked seen until stdout is written.
  - A "continue" reply with an appended system-reminder is still A15.
  - `policy refresh` reports a `git merge-file` crash as an error, not as conflicts.
  - A post-install commit check that cannot run rolls the update back.
  - An `@AGENTS.md` inside a code fence is not an import.
- **`teyla routine install --dry` is a dry run.** Before, it installed for real. A plist
  outside the real account's `~/Library/LaunchAgents` (a moved `$HOME`) is never bootstrapped:
  launchd's `gui/<uid>` is the real account's, and such a plist replaced the real daily and weekly
  jobs.
- **The test suite never reads the machine's real transcripts.** The adapters resolve their root
  when called, so the doctor tests stopped parsing the real `~/.claude/projects`. `./check.sh` went
  from 197 s to about 60 s, and one test from 184 s under load to under a second.
- **`teyla doctor`: a CLAUDE.md that is `@AGENTS.md` is consistent**, not "differ".
- **The work-laptop prompt targets 0.14.0 in safe mode.** The prompt is
  `teyla prompt work-account-update`, and its steps are:
  - `teyla policy init --work` and a pinned `update.pin`;
  - `teyla uninstall --dry` as the list of Teyla's files;
  - `teyla prompt onboard`, reading only its corporate notes;
  - a by-hand `teyla update --allow-network --wire`;
  - a redacted `teyla feedback` file that you carry out yourself.
- **The weekly routine moves from Monday 07:30 to Friday 20:45** (local time), so the waste digest
  lands at the end of the week. The whole weekly moves, so there is one digest, not two. The plist
  is now filled from `SCHEDULE`, and `teyla routine install --if-stale` (run by `teyla update`)
  rewrites an installed plist whose schedule differs, so an existing Monday install picks up the
  change on the next update. A weekly the Mac missed still runs from the daily wrapper, on Saturday.
- **Rules have a lifecycle, fed by human corrections only.** `teyla rules propose` prints a
  proposed diff of rule files from corrections a person made (`teyla correct`, inbox rejections
  with a note) and ignores the capture hook's regex guesses, now tagged `source: hook` — nearly all
  of them were not corrections. A correction matching an existing rule is a hit; new rule files carry
  `created`/`hits`/`last_hit`/`expires`, and `teyla rules stale` lists expired and never-hit rules
  as removal candidates (never deleted). `--write` is the only path that writes. `teyla rule` warns
  when a file it wrote is past ~200 lines, and `teyla doctor` lists every instruction file that is.
- **Hidden characters are refused in instruction files.** `teyla rule`, `teyla correct`,
  `teyla rules propose --write`, every `teyla policy` write and `teyla models --write-policy` exit 2
  and write nothing when the result would hold bidi controls, zero-width characters or Unicode tag
  characters — text an agent obeys and a reviewer cannot see. The message names line and column.
- **`teyla cloud prep` writes a stricter Stop hook and a truer Shipping section.** "Pushed" now
  means on this branch's own upstream (`@{u}` or `origin/<branch>`), not "in any remote branch";
  commits after a merged or closed PR ask for a new PR instead of counting as handled; the Actions
  line says what POLICY §10 says (no CI on push/PR, short ubuntu deploy jobs on push to main
  allowed); the setup script installs subdirectories (two levels down) that have their own
  lockfile; and a stale `merge-approved:` line anywhere in an instruction file, marked section or
  not, is refused. Re-run `teyla cloud prep` in repos already prepped to pick these up.
- **`teyla cloud check` fixes.** A cloud session is attributed to the `claude/*` branch whose
  tip is nearest its commit, not the alphabetical first; `if ! command -v x && …; else x` no longer
  counts as a guard; a symlink loop between CLAUDE.md and AGENTS.md is a BLOCK, not a crash on
  Python 3.11/3.12.

## 0.13.1 — 2026-09-30

- **Hermes hooks are recognised after Hermes rewrites its config.** After Hermes updated itself it
  rewrote `~/.hermes/config.yaml`, dropping Teyla's marker comments and the quotes but keeping the
  entries, so `harness sync` asked for all of them by hand and doctor said "hooks not wired".
  Teyla now reads the (event, command) pairs under `hooks:`, as it does for Codex, and names only
  what is missing.

## 0.13.0 — 2026-09-30 — safe at work, true in every harness, useful in the cloud

What the sprint was measured against, before it started:
- `teyla doctor` was dominated by one `git log -p` per worktree and took minutes; 0.12 brought it
  to 8.4 s, and `teyla monitor --days 3` from 21–29 s to about 2 s.
- The correction rate was overstated: batch prompts and retries were counted as human turns, and
  the capture hook filed mostly false positives. Almost all Codex sessions in the sample were
  `codex exec`.
- Weekly reports were written and never opened, and the session-start line showed the same
  "1 fix(es), 2 warning(s)" on every start for two weeks.
- The no-Actions rule was broken several times in product repos until the Actions quota ran out;
  the new scan flags workflow files across the repos it checks.
- One product drove hundreds of `grok -p` calls a day, and no repo in the sample was ready for a
  cloud session.

Every change below had one GPT-6.1 Sol review of its own diff at merge time, and one of each fix;
the P1s it found were fixed before merging.

### Safe at work

- **Safe mode.** `teyla config set safe.enabled=true`, `TEYLA_SAFE=1` or
  `teyla policy init --work`: no network unless the typed command says `--allow-network`, no
  self-update from the hook or the daily routine, `check.sh` only in `products.repos`, plugin
  changes printed as `claude plugin …` commands, no keychain query, `teyla run`, triggers and
  agent steps gated. A config that does not parse or cannot be read turns safe mode **on**, and
  is never rewritten. `templates/POLICY.work.md` lists approved providers only.
- **Updates install a published release, by commit, verified.** A draft release
  is not a release; every install forces a reinstall and checks the commit the installer
  recorded; a build that reports the wrong version or commit is rolled back to the commit that
  was running. `update.pin` (a version or a sha) and `update.channel=none`.
- **Corrections leave the repo**: `~/.teyla/corrections/<repo>-<hash>.jsonl`, 0600 in a
  0700 `~/.teyla`, secrets scrubbed (long tokens, `KEY=value` assignments, `.netrc`-style passwords), written
  in full or not at all. An older in-repo `.teyla/` gets an
  `info/exclude` line on first touch.
- **`teyla uninstall [--dry] [--keep-data]`** reverses every write Teyla makes —
  LaunchAgents, the policy import line, symlinks, Hermes sections, harness skills and hooks
  (Codex's included), the plugin, `~/.teyla` — touching only what carries Teyla's marker, label
  or symlink target. `prompts/onboard.md` lists every network call and every file with its undo.

### True in every harness

- **Codex hooks and Hermes orientation.** `teyla harness sync` wires Codex's SessionStart
  and UserPromptSubmit in `~/.codex/hooks.json`, keeping a user's handlers in a shared group;
  Hermes gets the orientation on its first turn. `codex exec` prompts are never corrections.
  `harness status` shows whether Codex and Hermes approved the hooks.
- **`teyla harness verify [--live]`**: can each harness do work now — version, auth shape
  and dates, the newest quota or auth error still unresolved, interactive vs batch sessions;
  `--live` sends one line through each and checks the policy reached it.
- **Numbers you can act on.** Batch sessions are never human turns (Hermes `oneshot`
  included), retries are not corrections, one matcher for the hook and the report; A9 no
  longer tops out on "Try again"; A10 compares the dates governance files were written with
  the ack date.
- **Headless spend**: calls a day per harness and project with their cost; **A17** when
  one project drives more than 200 a day or doubles week over week, **A18** for quota, balance
  or auth errors. Under `--share` advice is computed from redacted metrics.
- **Policy detectors**: a POLICY.md marker switches on a check that files or transcripts
  can prove broken — `no-actions` (workflows on push, pull_request or schedule, in the working
  tree and on `origin/HEAD`; doctor and **A16**) and `ask-permission` (turns ending on a
  permission question answered with a bare yes; **A15**).
- **A digest that gets read**: the session-start banner shows only what is new; the
  weekly routine writes a five-line digest (`teyla digest`) with the top three actions and
  their commands; `teyla check <product> <check> ok|broken` confirms a manual check in place.
- **Model generation**: prices and the POLICY ladder for opus-5-5, sonnet-5-5,
  haiku-4-5, fable-5-1, gpt-6.1-sol, gpt-6-luna, grok-4.7 and grok-4.7-build-fast.

### Useful in the cloud

- **`teyla cloud check`**: per repo, what a cloud session would lack — instructions that
  defer to a home-directory file (a symlink out of the repo blocks), `.claude/` ignored, no
  shipping rules or hooks, a `merge-approved:` line that drifts from the user's list, Mac-only
  gate steps with no skip, secrets with no manifest. `teyla cloud inbox` and **A19**: branches
  with `Claude-Session:` commits and no PR after 24 h, landed only when on the remote default.
- **`teyla cloud prep`** writes what a repo needs for that: an AGENTS.md shipping section
  with the `merge-approved` line, SessionStart/Stop hooks gated on the remote environment (the
  Stop hook fails closed on unpushed work), rules and a setup doc that labels every secret name
  by where it may live. Every write stays inside the repo; public repos get no private data.

## 0.12.0 — 2026-09-29

- **`teyla doctor` is much faster** (242 s → 8.4 s on a many-worktree machine): doctor counts
  finished worktrees without the reflog comparison (removal still runs it), the remote half is
  computed once per repository, and the harness lines count only the last 7 days of sessions.
- **Batch prompts are not human turns**: `claude -p`, `codex exec` and `grok -p` sessions
  are counted but their prompts are not; `--days` reads only the window (`monitor --days 3`:
  21–29 s → about 2 s).
- **`teyla grok-cost`** reports what Grok CLI sessions cost at list price. `--last --cwd <repo>`
  prints one line for the newest session under a path (cost, model calls, input with cached %,
  output, tool calls, context, effort, title) — what an orchestrator runs when a `grok -p` lane
  ends; `--session ID` does the same for one id. The default is the last 7 days by project,
  `--by session` the top 20, `--json` for either. Ranked by dollars (`costUsdTicks`, 1e10 ticks to
  the dollar), never raw tokens: cached reads are most of them. Worktrees and `~/repos/<repo>`
  collapse to `<repo>`, a `<repo>-grok-empty` temp directory to `<repo>`, other temp directories to
  `tmp`.
- **Reader.** `adapters/grok.session_costs` sums the usage of every `turn_completed` record in a
  session's `updates.jsonl`, streamed in bytes. It prunes by stat and directory name, opens
  `summary.json` only for sessions in the window, and never touches `chat_history.jsonl`: a week
  of a store with thousands of sessions reads in about a second, `--last` in well under a second.
- **A13, A14** in `teyla monitor` / `teyla advise`: one project over half of the week's Grok
  cost (once the week is over $10), or a single Grok session over $10.

## 0.11.0 — 2026-09-25 — the disk agent work leaves behind

What prompted it: dozens of subagent worktrees under `<repo>/.claude/worktrees` held tens of
gigabytes, nearly all clean and already pushed; more under `~/.worktrees` held several more; and
several iOS simulators were booted at once.

- **`teyla storage`** reports disk free, every linked worktree with a verdict, git-ignored
  build output, dependencies, caches with the command that clears each, booted simulators
  and RAM by process. **`teyla storage clean`** is a dry run; `--apply` removes the SAFE
  rows — worktrees with `git worktree remove` (no `--force`, branch kept), build dirs after
  a re-check — and logs each to `~/.teyla/storage.log`. Dependencies, caches, transcripts,
  simulators and Docker are reported, never removed.
- **SAFE is strict.** A worktree goes only when it is clean, on a remote, idle (1 day for
  a subagent's `agent-*`, 3 for a session's), unlocked, no process sits in it, no git
  operation is in progress, no worktree is nested inside, it holds no ignored file that is
  not build output, and its reflog holds no commit whose change no remote carries — all
  re-checked right before removal. `.teyla/corrections.jsonl` is appended to the main
  checkout's copy first. Two review rounds reproduced eight ways `git worktree remove`
  loses data without `--force`; each is a test.
- **`teyla config set storage.auto_clean=true`** lets the daily routine clean on its own;
  off by default. `doctor` warns under 15% / 25 GB free and at five finished worktrees.
- **No Actions on push, PR or tag** (POLICY §10). `./check.sh` is the gate;
  `scripts/release.sh` runs it and creates the GitHub release from the laptop.

## 0.10.2 — 2026-09-15

- **POLICY template §9 restored.** A later re-sync of the template from the trimmed live file
  dropped §9 minutes after it had been added; 0.10.1 shipped without it.
- **`~/.teyla/routines/<product>.line` is written by the `teyla routines` command only**, not
  by the library call the tests use — the suite had left two fixture products there.

## 0.10.1 — 2026-09-15 — the rollout's own two failures

Both seen while 0.10.0 installed itself on the machine it was written on.

- **`teyla update` never leaves the machine without a binary.** uv's cached checkout of the
  repo had lost objects ("unable to read sha1 file"); `uv tool install --force` had already
  removed the old tool, so the daily wrapper, the session-start hook and doctor all went quiet.
  A corrupt-cache failure now runs `uv cache clean teyla` and retries once; any other failure
  that left no binary reinstalls the version that was running; the session-start hook says
  "no teyla binary although ~/.teyla/config.toml exists" with the reinstall command.
- **A reinstall cannot hide a missed run.** `routine catch-up` said "on schedule" for the
  weekly that had just missed Monday, because `update` had rewritten the plist that night and
  its mtime read as a fresh schedule. `install()` records the first install once in
  `~/.teyla/<job>.installed`; an earlier start counts as evidence too.

## 0.10.0 — 2026-09-15 — works when it is needed

A review of three weeks of Claude Code sessions asked one question: did Teyla run whenever it
should have? Four findings, each with a fix here.

- **The weekly never ran.** Installed Friday, due Monday 07:30; the Mac was off until
  the afternoon, and launchd fires late only after *sleep*, never after a power-off — `launchctl
  print` showed `runs = 0` while `doctor` said "loaded". Each wrapper now stamps
  `~/.teyla/<job>.last` when it starts; **`teyla routine catch-up`** runs any job whose stamp
  is older than its last due minute; the daily wrapper and the plugin's session-start hook
  call it. `routine status` shows last started / last due; doctor says **MISSED** with the
  due time instead of OK.
- **"Did it run?" cost a session.** Several sessions in product repos asked whether a
  product ran and answered by reading code and git log; none ran `teyla routines`. Some products
  errored out of `teyla routines` anyway (a `script` routine without a label,
  a cadence of `5m`, a check whose status was a paragraph). Now: `teyla routines` writes one
  line per product to `~/.teyla/routines/<product>.line` and the session-start hook prints it
  when the cwd has a `teyla.toml`; POLICY **§9** says a status question is answered from the
  record before code is read; `script` routines need only a name; `every` accepts any
  `<n>m|h|d`; the status error names the allowed values.
- **Every captured correction was noise.** All the sampled records were
  `<task-notification>` blocks (a subagent finishing) that matched "again"/"don't";
  `teyla corrections --cluster` was dominated by a Grok batch brief repeated thousands of times.
  The capture hook skips harness-injected prompts (same list as `is_noise_turn`, which gains
  `<command-message>`, `[Request interrupted`, and the continued-session summary); batch
  sessions are never clustered; the headline says `grok (N, of which M batch calls)`.
  `tests/test_hooks.py` runs the hook through `sh` with the exact notification shape.
- **Only Claude had the loop.** Policy was wired into Codex, Grok and Hermes; skills, hooks
  and Cursor were not. **`teyla harness sync`** (run by `teyla update`) renders the plugin's
  skills plus `teyla-rule` and `teyla-correct` into `~/.cursor/skills`, `~/.codex/skills`,
  `~/.grok/skills`, `~/.hermes/skills/teyla`; wires the two hook scripts as Cursor's
  `sessionStart`/`beforeSubmitPrompt`, Grok's `SessionStart`/`UserPromptSubmit`, Hermes's
  `on_session_start`/`pre_llm_call`; `teyla policy sync` writes the policy as a Cursor user
  skill (Cursor has no global rules file). **`teyla rule`** and **`teyla correct`** are the
  slash commands as a CLI, so every harness's skill does the same write — a rule is mirrored
  into `AGENTS.md` and, when `.cursor/rules/` exists, into a `.mdc`. A **Cursor session
  adapter** reads `state.vscdb` (model, turns, tools, corrections; the store has no
  per-message tokens). The capture hook reads every harness's stdin shape and de-duplicates.
  `docs/HARNESSES.md` names the doc file each fact came from and what is not the same:
  session-start context injection is Claude-only.

## 0.9.0 — 2026-09-11 — self-maintenance that survives a managed laptop

Fixes from a second work-laptop feedback round: a managed machine behind a TLS-inspecting
corporate proxy, Claude Code as a desktop app only, `uv` from Homebrew.

- **`[env]` in `~/.teyla/config.toml`, and `teyla config show|set`.** The environment
  Teyla cannot inherit — `SSL_CERT_FILE`, a proxy — is applied by every `teyla` process at
  startup (setdefault: the shell wins) and written by `routine install` into both launchd
  plists and both wrappers. The weekly plist and wrapper now carry `PATH` too (they did
  not; Homebrew `uv` was invisible to them). Wrappers count as stale when their exported
  env differs from config, so `update`'s `routine install --if-stale` regenerates them
  with the adaptation instead of without it. `config.write(force=True)` keeps `[env]`.
- **`teyla update` pins the interpreter on every self-install** — `--python <X.Y>` for uv,
  `--python <exe>` for pipx — from `[update] python` in config if set, else the one it is
  running on. Before, uv rebuilt the tool on its default interpreter and an install moved
  to 3.12 (3.13's strict X.509 rejects a proxy root CA whose Basic Constraints are not
  critical) landed back on 3.13 after the very update it had enabled. The GitHub and
  models.dev calls verify through `truststore` when importable, else OpenSSL's default
  context (honours `SSL_CERT_FILE`, which may now come from `[env]`). `update-check.json`
  records interpreter, pin and trust source; an unreachable GitHub prints the fix for the
  two proxy failure shapes.
- **doctor `network`** — one line with the three facts that decide whether the update
  source is reachable: proxy in use (env or system), trust source (`truststore`,
  `SSL_CERT_FILE`, or OpenSSL's default bundle), interpreter and the version `update` pins.
  "GitHub unreachable" is now a **FIX** on that line, with the fix for the proxy failure
  shape it sees; `version` says "see network" as a WARN instead of an INFO filed next to
  "grok absent". A pin that differs from the running interpreter is a WARN of its own.
- **Failed update checks are cached 15 minutes, not 24 hours**, and every doctor line
  says "checked HH:MM" or "cached HH:MM, not retried" — so a fix is visible on the next
  run, and a stale failure is never mistaken for a fresh one.
- **A3 exempts one-human-turn sessions on size alone.** One turn is already one logical
  unit; a 20 MB autonomous run under an hour cannot be "split into one session per unit".
  Long active hours or repeated compactions still qualify it.
- **C2/C3 need 20 calls before computing a rate.** "100% of 1 calls" was a `[medium]` line
  in both `connectors` and the report; one call is not a rate. C1 (percentiles) and C4
  (explicitly about low volume) are unchanged.
- **`policy init --claude-md` acknowledges the file it writes** (`policy ack`, with a note),
  so A10 no longer fires for weeks on an edit Teyla itself made.
- **`policy init` seeds `code_root`/`ops_root` from the Layout section** of an existing
  `~/.agents/POLICY.md` or `~/.claude/CLAUDE.md` (`` `~/work/<repo>` ``) instead of the
  `~/repos` constant; `--code-root`/`--ops-root` still win.
- **Connector display names.** `teyla connectors` and the C1–C4 advice lines say
  `Airtable (<short id>)` instead of a truncated uuid, joined from the desktop app's own
  connector registry (`remoteMcpServersConfig` in its local-agent-mode-sessions files).
  Read-only; an unknown id is shown as before. `--json` carries `display` and `names`.
- **Review fixes (codex, GPT-5.6 Sol, cross-provider per POLICY §2):** `teyla update --force`
  reinstalls the *installed* version on the pinned interpreter when the release lookup itself
  fails on the current one (the pin could not bootstrap otherwise); an explicit
  `SSL_CERT_FILE`/`SSL_CERT_DIR` wins over `truststore`; a removed `[env]` entry makes the
  wrappers stale (the block is compared whole); `routine status` checks env too; a reachable
  repo with no release is a WARN, not "UNREACHABLE".
- **Session-start hook** finds `teyla` at `~/.local/bin/teyla` when the GUI app's PATH
  does not have it.

## 0.8.0 — 2026-09-11 — productization

The distance between "works for me" and "works for a few other people" is not a feature. It is
six pieces of plumbing — a shared key instead of accounts, no `user_id`, a backend on the
builder's laptop, no distribution path, an unmetered model key, no onboarding doc — each
locally correct for someone with no second user, each a wall the moment there is one.

- **`teyla platform`** — `~/.teyla/platform.toml` is the manifest of the resources bought
  once and reused by every product: server, domain, identity provider, mail sender, Apple
  API key, Play Console, model key, and one mode-0600 secrets file. It holds identifiers
  and env-var *names*; the command reports which names are present and never a value.
  Every missing resource prints the URL where it is created and the file and key where its
  value goes. `init`, `env-example`, `--json`, `--no-net`; exits 1 while anything is missing.
- **`teyla productize`** — a `[productize]` block in a repo's `teyla.toml` declares who it
  serves and who it should serve. Eight requirements are checked against the target:
  identity, tenancy, backend, distribution per platform, onboarding doc, secrets against
  `.env.example`, cost cap, and — for `public` only — a platform mail sender. A per-device
  app is exempt from the identity requirement; `family`/`testers` is deliberately an easier
  bar than `public`. `--owner-steps` merges every product's owner blockers with the
  platform's missing resources into one deduplicated numbered list, platform first.
- **`templates/platform/`** — the shared server, set up once: `provision-droplet.sh`,
  `setup-server.sh` (docker, ufw, unattended upgrades, a `deploy` user, one Caddy in front),
  a `Caddyfile` that imports each product's own site block, `add-product.sh <name> <port>`,
  and a ten-line runbook. A product is added by dropping a directory into `/srv`.
- **`teyla scaffold --kind app|service`** now writes the `[productize]` block, a
  `docs/GETTING-STARTED.md` addressed to a person who is not you, and `deploy/droplet/`
  fragments. Other kinds are untouched.
- **`docs/PRODUCTIZE.md`** — the method: why solo-built apps resist sharing, what to build
  for N users from day one, the platform cost table, how to productize an app that already
  exists, and what changes at twenty users.


## 0.6.2 — 2026-09-10 — second hardening pass

- Newlines split segments; `#` is not a comment mid-token; `shell:env` is an allowlist; the run cannot read `~/.teyla` or the HMAC key; interpreters, copy tools and network tools need an explicit `shell:*` (documented as full trust); receipts carry a grants hash and both `promote` and `inbox approve` require it unchanged; `fs.write:*` is the repo root only; `net:` is exact host or `*.domain`.

## 0.20.3 — 2026-10-12 — control plane hardened again

A second adversarial review, against the code 0.6.1 shipped. Every item has a test
carrying the input that worked against the hardened version, in
`tests/test_control.py` §12.

**Breaking.** `inbox approve` now refuses *any* manifest change since the draft —
a loosened cap and a narrowed capability list included, not only a widening — and
`promote` resets the streak when `capabilities` or `caps` change, not only `act`.
Interpreters, copiers and network clients (`python`, `sh`, `cp`, `tee`, `ln`,
`curl`, `git -c`, …) need `shell:*`; a grant naming one of them is refused. And
`shell:env` is an allowlist: `TEYLA_*`, `LANG`, `LC_*`, `TZ`, `NO_COLOR`,
`PAGER=cat`, nothing else.

- Newlines and carriage returns split Bash segments (`git push\ncurl evil` was one
  granted segment); `#` is literal mid-token (`main#;curl evil` lexed to a push).
- `shell:env` allowlisted, so `GIT_SSH_COMMAND=curl git push` and `HOME=runs git
  push` are refused; `shell:*` documented as full trust, equivalent to no grants.
- `Read`/`Grep`/`Glob`/`LS` refused on `~/.teyla/**` and on control basenames —
  `~/.teyla/hmac.key` signs the action log the receipt is built from — and a Bash
  command naming `.teyla` or `hmac` is refused case-insensitively, quotes stripped.
- Receipts carry a `grants_hash` (capabilities + caps); `promote` and `approve`
  both require it to match the current manifest.
- `fs.write:*` is the repo root, not the filesystem: no relative glob leaves the
  product repo, and reaching outside takes an absolute grant.
- A bare `tool:Skill` grants no skill; control basenames match case-insensitively;
  a `net:` grant is an exact host or `*.domain`, so a bare TLD matches nothing.

## 0.6.1 — 2026-09-10 — control plane hardened after an adversarial review

- Shell grants on a real tokenizer: `&` splits segments; env prefixes need `shell:env` (and never `PATH=`, `GIT_CONFIG*`, `LD_*`, `DYLD_*`); every redirection target is a write; process substitution refused.
- Control files live under `~/.teyla/runs/<id>/`, never in the product tree; the hook refuses writes to them; the action log is HMAC-signed and tampered lines are counted in the receipt.
- `inbox approve` recomputes grants from the current manifest and refuses widening; the kill switch is re-read before every act step; `command` steps are checked against their own capabilities (**breaking**: manifests need `shell:<verb>`).
- realpath before glob matching; `*` no longer crosses `/`; `Task`/`Skill` need grants; critic must answer exactly `PASS`; counters under flock; context hashes cover the tree; date keys use the trigger's timezone; promotion needs ten consecutive clean receipts bound to the act spec.

## 0.20.3 — 2026-10-12 — control-plane hardening

From an adversarial review of the 0.6.0 control plane. Every item below has a test
carrying the input that worked before the fix, in `tests/test_control.py` §11.

**Breaking.** A `command` step is now checked against the routine's own
`capabilities` before it runs — it never meets the PreToolUse hook, so this is the
only place it can be checked. An existing manifest whose steps run `echo` or
`./bin/x` needs `shell:echo` / `shell:./bin/x` declared, and `fs.write:` has to
cover anything a step redirects into. `teyla run --dry` shows what a routine has.

**Escapes closed in the shell checker.**
- `&` is a segment separator: `git push origin main & curl evil` no longer passes
  under `shell:git push`. Segments are cut with a real tokenizer, not a regex.
- An environment prefix needs `shell:env`, and `PATH=`, `GIT_CONFIG*`, `LD_*`,
  `DYLD_*` are refused even with it — the `GIT_CONFIG_KEY_0=alias.push` trick turned
  a `shell:git push` grant into arbitrary execution.
- Every redirection target is checked against `fs.write:`, and process substitution
  (`>(…)`, `<(…)`) is refused under every grant including `shell:*`.

**The run can no longer grade its own exam.** `grants.json`, `grants-state.json`,
`actions.jsonl`, `run.json` and the canonical `receipt.json` moved out of the
product's `runs/` (which `fs.write:runs/**` grants) into `~/.teyla/runs/<run-id>/`.
The hook refuses any write under `~/.teyla` and any write whose basename is a
control filename, regardless of grants. Each `actions.jsonl` line is HMAC-signed
(`~/.teyla/hmac.key`, 0600); unverifiable lines are dropped and the receipt says
`actions log tampered: N lines`. The repo keeps `draft.md`, `undo.md` and a receipt
copy.

**Other fixes.**
- `inbox approve` recomputes grants from the current `teyla.toml` instead of
  reloading the run's own `grants.json`, and refuses when the routine is gone or its
  capabilities have widened since the draft, printing the diff.
- The kill switch is re-read immediately before the act step, and before approve's.
- `fs.write:` globs resolve symlinks first, and `*` no longer crosses `/` — only
  `**` does, so `fs.write:*.md` stopped covering `.claude/rules/pwn.md`.
- `Task`/`Agent` need `tool:Agent`; `Skill` needs `tool:Skill:<name>` or
  `tool:Skill:*`; `SlashCommand` needs a `tool:` grant. None are read-only tools.
- The critic's first line must be exactly `PASS`; anything else is a FAIL.
- `max_writes`/`max_sends` are counted under `flock` across the whole
  read-decide-write, so parallel calls cannot both slip under a cap.
- `input-hash` expands context globs and hashes relative path + length-prefixed
  content, keyed by the routine ref; the `date` key uses the trigger's timezone.
- `promote` requires ten *consecutive* clean receipts and binds a hash of the act
  step into each receipt — editing `act` resets the streak.
- A session with no `TEYLA_GRANTS` while a run is in flight (`~/.teyla/active-runs/`)
  is refused rather than treated as an ordinary session. Residual: a nested
  `claude -p` inherits the environment, so the common case was already covered;
  an unrelated hand-started session during a run is refused too.

## 0.6.0 — 2026-09-10 — the control plane

- `teyla run <product:routine>`: the loop that runs a routine — capability grants, blast-radius caps, idempotency, gates A (needs you) / B (act and tell, with an undo note) / C (critic first), and a receipt per run naming the rules and grants it ran under.
- `teyla inbox`: the needs-you inbox; approve runs the act step under the same grants, reject files a correction candidate.
- `teyla kill on|off`: a global kill switch honoured by the run engine and by the hook on every tool call.
- `plugin/hooks/pre-tool-use.sh`: in a run, Claude Code may only use granted tools, shell verbs and write globs; every decision is logged to the receipt.
- `teyla triggers`: clock triggers become LaunchAgents. `teyla promote`: a gate is raised only on ten clean approvals. `teyla receipts`.
- Not built, and said so in docs/CONTROL-PLANE.md: event and webhook triggers, per-capability enforcement outside Claude Code, durable multi-step state; `shell:` grants can still write past `fs.write:` via redirection.

## 0.5.0 — 2026-09-09 — from the first corporate case study

- `teyla connectors`: per connector — read/write split, empty-or-error rate, median and p95 calls between your turns, rediscovery share; advice C1–C4. Skill reads (`SKILL.md`) counted beside invocations.
- `teyla plugins`: the skill / rule / fact quality pass over an installed plugin. `teyla plugin install|uninstall` for machines without the `claude` CLI.
- Advice: A3 uses active hours, not wall span; A8 skips absent harnesses; A10 respects `teyla policy ack`; A2/A4 suppressed for connector-heavy work in favour of A12.
- Fixes: `policy init --dry` is dry; `routines` exit 1 on unscheduled routines, 2 on untested checks, aligned columns; `sync-repo` refuses to collapse two differing files; `models --write-policy --drop-absent`.
- Docs: no-CLI second-opinion fallback in POLICY §2; three wiki review modes; kickoff prompt for no-CLI machines.

## 0.4.0 — 2026-09-09

- `teyla models [--days N] [--json] [--refresh]`: keeps the model ladder and prices current.
  Reads the models.dev catalogue (`~/.hermes/models_dev_cache.json`, opt-in `--refresh` network
  fetch only when stale/missing), the Grok and Codex CLI caches, Codex's configured model,
  models actually used in Claude Code in the last N days, and which providers have a credential
  present (presence only — never a value). Reports per provider and flags drift: LADDER-UNKNOWN,
  NEWER-AVAILABLE, NO-CREDENTIAL, UNLISTED-PROVIDER, PRICE-STALE; exits 1 on any flag.
- `teyla models --write-policy [--dry]`: rewrites the ladder table strictly between the
  `<!-- ladder:start -->`/`<!-- ladder:end -->` markers in `~/.agents/POLICY.md` — keeps every
  entry that still resolves, replaces one that doesn't with the newest of the same family, and
  appends a "reviewed `<date>` by teyla models" note. Prints the diff; touches nothing else in
  the file. `templates/POLICY.md` and `~/.agents/POLICY.md` both carry the markers now.
- `teyla models --write-prices`: writes `~/.teyla/prices.json` from the models.dev catalogue,
  tiered from the ladder. `pricing.py` now loads that file when present and falls back to its
  built-in `PRICES` table otherwise (`pricing.effective_prices()`).
- `advise.py` A11 "Model ladder drift": fires from the flags `monitor.metrics()` now folds in on
  every run (network-free — the embedded call never passes `--refresh`), action is
  `teyla models --write-policy`.
- `teyla routine install`'s weekly wrapper now also runs `teyla models`.

## 0.3.0 — 2026-09-09

- `teyla policy init --claude-md --ops-root-init`: global CLAUDE.md and an ops root from templates; `docs/HANDOVER.md` (the practices that travel to a second machine); kickoff prompt rewritten around them.

- Clean-install fixes: templates ship in the wheel; `policy init --owner`; `python -m teyla`.
- `teyla wiki init|status|lint|confirm` and the **wiki-pass** skill: the facts store as an LLM-maintained wiki (GitLab-Wiki compatible).
- `teyla feedback`: one redacted file for a second user to send back; GitHub issue templates.
- `teyla routines --issues`: a GitHub issue per broken manual check.
- `prompts/onboard.md`: paste-able setup prompt for an agent on a new machine.

## 0.2.0 — 2026-09-09

Routines and manual checks: the "does it actually run / does it actually
work" half.
- `teyla.toml`: a per-repo manifest of `[[routine]]` (launchd, cron, pg_cron,
  github-actions or script — the work that must run without a human) and
  `[[check]]` (the work a human tests by hand and confirms).
- `teyla routines [path...] [--json]`: one table per product — routine
  loaded/last-run/verdict (ok / NOT LOADED / STALE / unknown) and check
  status/confirmed/age/verdict (ok / BROKEN / UNTESTED / RE-TEST), a summary
  line, and exit code 1 when anything needs attention (so a cron can alert).
- `teyla routine install`: Teyla's own Monday 07:30 launchd weekly (monitor,
  routines, products, filed under the run-artifact layout). `teyla
  routine status` shows whether it is loaded and its last log lines.
- `teyla.toml` manifests written for several product repos from what was actually verified.

## 0.1.0 — 2026-09-09

First public cut.
- `teyla monitor` / `advise` / `sessions` / `corrections`: adoption report from local Claude Code, Codex, Grok and Hermes session logs, aggregates only, with advice rules A1–A10.
- `teyla policy`: one `~/.agents/POLICY.md` wired into Claude Code, Codex, Grok, Hermes and project `AGENTS.md`.
- `teyla harvest`: tool spines and corrections for the sessions that touched a path; feeds the harvest skill.
- `teyla scaffold`: a new repo born plug-and-play (AGENTS.md, check.sh, .env.example, LICENSE, CI, routines/).
- `teyla products`: real-usage counters across repos — the "built, not used" detector.
- Claude Code plugin: harvest and adoption-review skills, `/teyla:rule`, `/teyla:correct`, correction-capture hook.
- Portable prompts for machines where nothing can be installed (`prompts/`).
