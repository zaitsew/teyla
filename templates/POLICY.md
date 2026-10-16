# How to run a session — shared policy for every AI harness

Read by Claude Code, Codex, Hermes, Grok CLI, Cursor and Zed. One file, one policy.
Owner: {{owner}}. Edit here, never in a copy.

## 1. The model ladder — expensive model orchestrates, cheap models do volume

The top model of your provider plans, decides, reviews and does the genuinely hard
parts. Everything else — repo surveys, transcript mining, boilerplate, tests, docs,
first drafts, bulk edits — goes to a cheaper model of the same provider, as a
subagent or a separate run. Say in the recap which model did what.

<!-- Example ladder: replace these rows with the models you actually use. -->
<!-- ladder:start — maintained by `teyla models --write-policy`; edit rows by hand if you must, keep the markers -->
| provider | orchestrate / hardest tasks | volume work | throwaway / triage | note |
|---|---|---|---|---|
| Anthropic | Claude Fable 5.1 | Opus 5.5, Sonnet 5.5 | Haiku 4.5 | Fable inherits by default in subagents — always pass model: |
| OpenAI | GPT-6 Astra | GPT-6.1 Sol | GPT-6 Luna | Astra only as the interactive orchestrator |
| xAI | Grok 4.7 | Grok 4.7, grok-4.7-build-fast | — | on subscription: a cheap volume worker for ANY orchestrator via `grok -p` (research, summaries, bulk drafts) |
<!-- ladder:end -->

- In Claude Code, pass `model:` explicitly on every `Agent` call; "inherit" means Fable.
- In Codex, `model = "gpt-6-astra"` is for the interactive orchestrator only; run
  `codex exec` fan-outs with a cheaper `-m`.
- When a provider ships a new tier, update the row here, nowhere else.

## 2. Second opinions across providers

Before committing to a non-trivial design, and before landing anything that touches
money, credentials, or another person's data, get a review from a different provider:
`/codex review` or `/grok review` from Claude; `claude -p` from Codex. One pass, P1/P2
findings, then move on. Do not loop reviews. A review covers only the diff it saw: a
commit after the review means review again, or merge what was reviewed and put the
rest in its own PR.

If no second provider's CLI exists on this machine, open a fresh session of the same
harness with only the diff and the question, and label the result a same-provider
review. It catches less; a skipped review catches nothing.

## 3. Use the tool ladder, top down

Connector / MCP → CLI / API → browser extension (Claude-in-Chrome) → computer use.
Fall to the next rung only when the one above cannot do it, and say when you fell.
Prefer gstack skills when the task shape matches: `/autoplan` before a non-trivial
build, `/review` before a PR, `/qa` after a UI ships, `/spec` when intent is vague.

## 4. Ask about product decisions, not about permission

Bring the question with a proposed answer and a default. Do everything that does not
depend on the answer first, then ask — batched, at a natural checkpoint. Never ask
"shall I proceed?".
<!-- teyla:detect ask-permission — `teyla monitor` counts turns that end by asking to proceed -->

## 5. Stop only at a real blocker or the finished goal

A blocker is something only {{owner}} can do: create an API key, approve a payment, sign
in, accept terms. When you hit one: do every step around it first; open the exact
page at the exact step; name the exact file and line the value goes into; hand over
a one-line instruction, then continue the moment it is in.

## 6. Deliver plug-and-play

"Done" means {{owner}} can open it and start using it: README with a 5-line quick start,
setup script, `.env.example`, first-run check that prints what is missing. A feature
nobody can start is not shipped.

## 7. Merging

Merge without asking only into repos on your merge-approved list (Claude: the
list in `~/.claude/CLAUDE.md`). A repo you were asked to create in a kickoff is
approved from creation; record it with the kickoff sentence quoted verbatim.
Everywhere else: open the PR, stop, say what it changes. Merge, never squash. Never
force-push.

## 8. Report honestly

If you could not verify something, say so in the same sentence as the claim. If a
subagent reports a fact a command could check, check it. Corrections to your own
earlier claims go in plainly and once.

## 9. "Did it run?" is answered from the record, not from the code

When asked whether a product ran, works, or is up ("did it run this morning?",
"why is there no build?"), start from `teyla routines <repo>` — the routine rows
(loaded, last run, stale) and the manual checks — and the logs its `teyla.toml`
names. Read code and git history only once the record shows something wrong and
the cause is needed. Answered from the record it costs one command; answered by
reading code it costs a session. For scheduled tasks outside a repo — launchd jobs, Claude desktop
scheduled tasks, cloud routines, GitHub schedules — `teyla schedules` is the record: what exists,
when it last ran, and what vanished.

## 10. One machine, a budget — the guard decides, not the agent

Every agent on a laptop shares one CPU, one RAM and one swap file, and none of them
sees the others. Ten sessions that each boot "just one" simulator and run "just one"
build exhaust memory together: swap fills, load climbs into the hundreds, and the
kernel panics. So:

- **Check before heavy work.** `teyla load` gives the verdict (OK / BUSY / CRITICAL)
  with the numbers. On CRITICAL, start nothing heavy — no build, no simulator, no
  headless lane — and finish or stop what you started.
- **Wait, do not retry.** When the machine guard refuses a command, run it as
  `teyla load --wait --kind <build|sim|lane> && <command>`. It blocks until a slot is
  free; a retry loop is the same overload with extra steps.
- **Reuse a booted simulator.** Boot one only when none of the booted ones fits; shut
  down every simulator your lane booted when the lane ends (`xcrun simctl shutdown <udid>`).
- **Stop your daemons.** A lane that ran Gradle ends with `./gradlew --stop`.
- **Parallel lanes cost memory, not only tokens.** Fan out only as wide as
  `guard.max_builds` and `guard.max_sims` allow; queue the rest.
- After a crash, `teyla crash` says what the machine looked like before it; read it
  before starting the next sprint.

## 11. Platforms and releases — one primary, ports in trains, builds that reach a person

Every platform multiplies every later feature: each one is built, reviewed, tested and
released through its own store. Building them all at once means porting features that
are still changing, then a parity sprint to catch up with a moving target. So:

- **One primary platform per product**, the one the owner actually uses it on (by
  default, the owner's phone). Declare it in `teyla.toml` (`[productize] primary`).
  Features are designed, built and accepted there first. A Mac tool, a web service or a
  watch app names its own primary.
- **A second platform needs a trigger, written down** in `teyla.toml` under
  `[productize.triggers]`, with the date: a named person who cannot use the primary, the
  owner asking for that platform for that product, or a `public` target once the primary
  is public. Completeness, spare
  capacity and a scaffold that listed it are not triggers. Start with the cheapest form
  that serves the trigger: a PWA before a native Android app, the same SwiftUI target
  before a separate Mac app. A Mac build is still adapted to the Mac (pointer-sized
  controls, windows, menus), never a stretched phone screen.
- **Ports run in trains, not per feature.** Feature PRs touch the primary only. A
  secondary platform catches up in one parity train when the primary ships a store
  version, or when the owner asks. Port only settled features: in a primary build and
  unchanged for a week. `docs/PARITY.md` keeps, per secondary, `synced-to: <commit>` and
  what is deliberately left out; the train's brief is the primary's diff since that
  commit, not the whole tree, and it runs on the volume model. Same day on every
  platform: security and data-loss fixes, and backend changes that would break a shipped
  client.
- **A secondary nobody opened in 30 days is frozen**: no parity trains until a trigger
  revives it. It stays installed as it is.
- **A build is done when it reaches a person**, not when it is uploaded. A session that
  merged a user-visible change on the primary ends with one internal upload (TestFlight
  internal, Play internal) — at most one per app per day unless it fixes a broken build —
  and says the build number once it is installable from the owner's tester account.
  `teyla testflight` checks it.
  Secondaries upload at the end of their train.
- **External testing starts when someone else uses it.** Start Play's closed test (14
  days for a personal account) the day the Android trigger fires: that clock is the
  longest pole.
- **Store submission.** The first public release of a product is the owner's call, asked
  with a proposal (§4). After that, keep one version in review; when it is approved,
  release it and in the same session submit the newest build the owner has used for a
  day without a blocking report, after the pre-release review (§2). The store version is
  never more than two weeks behind the build the owner uses. A rejection is fixed and
  resubmitted in the same session unless it needs the owner's account.

## 12. Store review — pass the first time

A rejection costs a review round (one to six days) and usually a renamed version, and almost
every one is of a kind a checklist catches. Before every store or beta-review submission:

- **China mainland is off, from the first submission.** Generative AI in the China
  storefront needs a Chinese permit (MIIT / CAC) that the usual model providers do not hold,
  and any app there also needs an ICP filing, which needs a Chinese entity. Exclude `CHN` in
  App Store availability app-wide, with the reason beside the setting in the repo's store
  script. Re-including it is the owner's call. Google Play does not distribute in China.
- **Model providers stay out of the store listing.** No provider or model name in the app
  name, subtitle, description, keywords, What's New or screenshots: a listing that names one
  reads as "associated with" it, which is what the China rejection cites. The privacy policy
  and the in-app AI consent still name every provider that receives data.
- **The reviewer can reach every feature.** Any build with sign-in carries a working demo
  account in the review information (App Store, beta review, Play app access), on a plan that
  unlocks everything. A capability declared to the store — a background mode, HealthKit,
  Health Connect, location, microphone — works for that reviewer in the first minute; if it
  needs content, the app bundles sample content that works signed out and offline. No
  paywall, waitlist, region lock or bring-your-own-key in the way.
- **Health data: name it, and ask only for what a screen shows.** HealthKit is named in the
  UI where it is used. Each Health Connect type is requested only with a screen that displays
  it, and its declaration says purpose · screen · benefit. Dropping a type beats defending it.
- **The Mac app behaves like a Mac app.** Closing the main window never strands the user: a
  Window-menu item and the File/View items reopen it. `LSApplicationCategoryType` is set.
- **The listing is complete before submit.** Screenshots for every device class the build
  supports, age rating and App Privacy filled, export compliance in Info.plist, support and
  privacy URLs live.
- **Play's moving floor.** Before an upload: `targetSdk` at the level Play currently requires
  (read the Console's warning, not memory), a `versionCode` above every one used on any track,
  the Data safety form matching the manifest, and in-app reporting of offensive output for any
  generative-AI feature.
- **The review notes say what a reviewer would otherwise ask:** the demo account, where each
  declared capability is seen, that AI output is generated and how to report it, and why China
  is excluded.
- **A rejection is recorded and generalised.** The reason text is only on the App Store
  Connect App Review page (the email and the API carry none). Log guideline, verbatim reason,
  cause and fix in the repo's store doc, and when it is a new class, add a bullet here in the
  same session so no other product meets it.
