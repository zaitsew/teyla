# Studio: design, copy and visuals that improve themselves

Status: concept and roadmap, 2026-10-30. Sprint 1 starts the same night. Decisions are
numbered S1–S14 so later docs can cite them.

Studio is the part of Teyla that owns how a product looks, what it says and what it shows
the world: the UX standard, the review loop from the owner's phone to a merged PR, the
checks that catch drift, the taste ledger that turns the owner's comments into rules, the
copy lane, and the brand kit every screenshot, mascot, video and post is cut from.

## 1. Why

The owner on 2026-10-30, translated from Russian:

- "After so many iterations the planner is still 3/10 in terms of design and texts."
- "Ideally I would tap through the product and comment in real time by voice. I spend a lot
  of time making a screenshot and typing a comment."
- "Elements often drift and work unstably, and Claude/Codex do not notice this during
  testing."
- "Make the system self-developing: constantly analysing the best products on the market,
  updates, trends, X posts. Give me the ability to quickly calibrate the voice, the
  guidelines and the design system, literally by speaking during a review."
- "Mascots, icons, screenshots, video, AI reels and posts for X, Instagram and TikTok. The
  visual and the voice must differ per product."

Earlier, 2026-10-16 (`teyla intent teyla`, ROADMAP row 4): "UX / UI is the weakest link; a
lot of noise and little logic". That row scored 3 then and still does.

## 2. What exists, and why it did not add up

| Piece | Where | What it does today |
|---|---|---|
| UX standard | `templates/design/STANDARD.md` | Screen rules, tokens rule, UI copy rules, the review process, a 10-point checklist |
| Per-product design file | `templates/design/DESIGN.md` | Tokens, voice, screen inventory, "deliberately absent" |
| Static audit | `teyla ux check` | Counts literals instead of tokens, crowded views, "Please", "!" and long buttons |
| Voice chart + check | `templates/voice/VOICE.md`, `teyla voice check` | Per-language limits and a ban list for marketing text; no product has a chart yet |
| Session video | `teyla reel` | A Claude/Codex session as a 1080×1920 "terminal story" |
| Owner's words | `teyla intent`, corrections, `teyla asks` | Verbatim capture, corrections scrubbed to a store, questions to the owner |
| Phone relay | `docs/RELAY.md`, `apps/ios` | iCloud Drive folder; the phone answers questions and sends tasks, by voice too |
| The planner | `Design/tokens/*.json` → Swift, CSS, Kotlin | DTCG tokens since 2026-10-24, generated for three platforms, checked by `check.sh` |
| The planner | `docs/DESIGN.md`, 312 lines | A decision history: paper (09-13), glass (09-24), Field Journal (10-25). Three restyles in six weeks |
| The planner | `docs/FEEDBACK-2026-10-*.md` | The owner's dictated comments, typed after screenshots, turned into D-numbers |
| The planner | `App/Localizable.xcstrings` | 3,681 strings × en/es/ru, written by the agent that wrote the code |
| The planner | `UITests/` (93 files) | Flows. No screenshot baseline, no visual diff, no audit of overlap or clipping |
| founder-os | `voice-ux-loop`, `ux-reviewer` | Serve a static HTML mock, tap-to-comment overlay, Wispr Flow transcript triage. Never run on the real app |

What the pieces miss, in five lines:

1. **The loop never closes on the real app.** Comments arrive as typed text after a
   screenshot, become a D-number in a Markdown file, and the next lane does not read it.
2. **Rules are prose and never harvested.** Nothing turns an accepted comment into a rule, so
   each lane rediscovers taste, and the style is rebuilt from scratch every two weeks.
   Atlassian measured the same failure: a prose design file alone gave agents about 30 %
   of the design-system context and cost 92 % more tokens than a component catalog plus
   lint ([Atlassian, 2026-06-15](https://www.atlassian.com/blog/how-we-build/atlassians-design-md-is-here-what-we-learned-testing-portable-design-context-in-practice)).
3. **Nothing measures the result.** No screenshot baseline, so drift is invisible to the
   agent and visible only to the owner, on the phone, later.
4. **Copy is a side effect of code.** The agent that writes the view writes the string, in
   the same lane, checked only for "Please" and "!". Spanish and Russian are translations.
5. **Visuals are one-offs.** Twelve mascot PNGs, a screenshot script, no brand kit a model
   can be pointed at, no way to cut the same asset for three languages and five channels.

## 3. The research behind the decisions

Three sources on 2026-10-30: a Codex consult (GPT-6 Astra, high effort, web search), two
web research passes (Claude Sonnet 5.5, ~100 fetched pages), and a Grok 4.7 consult that
returned one fact before hitting the account's usage limit (X API: $0.005 per post read,
$0.015 per post written, [docs.x.com](https://docs.x.com/x-api/getting-started/pricing)).
The findings that shaped the design:

- **Native iOS "tap and talk" does not exist as a product.** The web side is solved (Vercel
  Toolbar comments and Marker.io expose MCP; Vibe Annotations and Agentation pin elements
  for agents). For iOS the one durable path is TestFlight's screenshot feedback, readable
  through `GET /v1/apps/{id}/betaFeedbackScreenshotSubmissions` with signed webhooks
  ([Apple](https://developer.apple.com/documentation/appstoreconnectapi/beta-feedback-screenshot-submissions)).
  AnnotateKit (v0.3.0, 3 stars) is the only in-app package and is a prototype. So Studio
  ships its own small capture package and uses TestFlight feedback as the no-code fallback.
- **Claude Design is not a building block.** It annotates its own prototypes, has no API or
  MCP, and the standalone product closes on 2026-12-14
  ([admin guide](https://support.claude.com/en/articles/14604406-claude-design-admin-guide-for-team-and-enterprise-plans)).
- **Figma round-trip from SwiftUI is dead weight for one maker.** The documented
  code-to-canvas flow is web only; practitioners report two diverging sources of truth;
  write-to-canvas pricing "will eventually be usage-based"
  ([Figma MCP guide](https://github.com/figma/mcp-server-guide)). Truth stays in code,
  DTCG tokens (stable spec since 2025-10-28) and rendered screenshots.
- **A vision model is a judge only in pairs.** Absolute 1–10 scores of a lone screenshot
  have no supporting evidence; pairwise comparison against a reference does (GPT–human
  agreement 80.9 % vs human–human 68.7 % on page pairs, [arXiv 2510.23272](https://arxiv.org/abs/2510.23272);
  WebDevJudge warns ties are the weak spot). Studio judges A vs B and before vs after,
  and the owner breaks ties.
- **Drift is caught deterministically, not by a model.** A fixed matrix (device × Dynamic
  Type × light/dark × locale × state) snapshotted with swift-snapshot-testing (1.19.x), diffed
  against an accepted baseline, plus `performAccessibilityAudit` for clipping, contrast and
  Dynamic Type. Liquid Glass does not render in view-level snapshots, so screen-level
  simulator captures stay in the matrix.
- **Reference libraries have APIs now.** Mobbin MCP (621k screens, paid, 60 req/min) and
  Refero MCP (web + iOS, paid, 8,000 calls/month). Both are §11 charges; Studio starts
  with free sources (Apple Design Awards, App Store editorial, release notes, RSS) and
  asks before buying.
- **Copy enforcement that works is a style guide the agent reads first plus a lint.** Ditto's
  MCP does exactly that for teams. No sourced readability target for mobile UI exists, so
  Studio keeps the policy's limits (20 words a sentence, 3 words a button) and adds
  per-control budgets.
- **Visual pipeline prices (2026-10):** Nano Banana 2.1 $0.0336 per image, Nano Banana Pro
  $0.134 ([Google](https://ai.google.dev/gemini-api/docs/pricing)); gpt-image-2 $30 per 1M
  output tokens ([OpenAI](https://developers.openai.com/api/docs/pricing)); ElevenLabs
  dubbing $0.33–0.50 per minute per language ([ElevenLabs](https://elevenlabs.io/pricing/api));
  Remotion free for individuals; Sora's API shut down 2026-09-24; Instagram, TikTok and
  YouTube posting APIs need an app audit before public posts, X does not.
- **Nobody reviews a native app by tapping and talking yet.** The closest tool, Agentation
  (click an element, copy markdown with selectors), is React-only and desktop-only
  ([GitHub](https://github.com/benjitaylor/agentation)); a 2025 post asking for exactly this
  loop is still a wish ([@CasJam](https://x.com/CasJam/status/1950911461049405619)). Studio
  builds it.
- **Snapshot libraries miss the surfaces that drift.** swift-snapshot-testing renders
  synchronously and does not composite blur or material layers, so Liquid Glass bars and
  sheets diff unreliably ([Forasoft](https://www.forasoft.com/blog/article/testing-automation-in-ios-228)).
  The matrix therefore screenshots a running simulator, not a view.
- **Apple's writing rules are free as JSON** and match the standard: fewer words, a verb on a
  button, no "oops", no "we" in errors, "Favorites" not "Your Favorites", an empty state that
  gives a next step ([HIG Writing](https://developer.apple.com/design/human-interface-guidelines/writing);
  machine-readable at `developer.apple.com/tutorials/data/design/human-interface-guidelines/<slug>.json`).
- **Feeds that answer (checked 2026-10-30):** Apple Developer News, Apple Releases, Apple
  Newsroom (Design Awards), MacStories, Daring Fireball, Nielsen Norman Group, Smashing,
  uxdesign.cc, iOS Dev Weekly, SwiftLee, Swift with Majid, Sarunw, Lenny's Newsletter. Dribbble
  sits behind a bot wall; Growth.Design has no feed; Mobbin's MCP needs a Pro plan.
- **iOS 27 (September 2026) reversed parts of iOS 26:** search returned to the tab bar and
  toolbars changed; a custom tab bar or toolbar gets none of it and must be retested
  ([MacStories](https://www.macstories.net/stories/ios-and-ipados-27-review/2/)). Rules copied
  from one WWDC age within a year, which is why the standard keeps few rules, dates them, and
  retests every rule copied from a WWDC session after each iOS release.
- **The reference set** the second report returns: Things (the Plus button dragged to where the
  task goes; colour reserved for meaning), Flighty (one departure-board line per flight, about
  fifteen time-and-place states, a status colour always paired with a text badge, "Leave for
  airport by…"), Structured and Tiimo (one timeline for tasks, events and habits; Tiimo was
  iPhone App of the Year 2025), Sunsama (copy the planning ritual, not the phone UI), ChatGPT
  voice (one pulsing orb, interrupt by speaking, a transcript drawer), Finch (a companion
  character that people keep opening). Nobody found does trip + day + family + companion in
  one app; one HN comment answers "planning travel isn't that hard", so the white space is
  unproven.
- **Codex (GPT-6 Astra) on the architecture:** the diagnosis holds; the missing visual tests
  explain undetected change, not bad design; an automatic rule promoter would preserve
  misunderstandings; the empty voice charts are the real copy gap; a judge can flag a
  regression and cannot certify good UX. Its estimate for the system: 11–17 agent-days over
  two nights per sprint. Its amendments are folded into §4–§6 below.
- **Grok on X (2026-10-30, after the owner's subscription; $2.74).** Builders on X say the
  same thing the diagnosis says, with numbers: agents "walk right past the ugliest UI" and a
  screenshot does not say whether a gesture feels good
  ([@kunchenguid](https://x.com/kunchenguid/status/2094609213532332528), 1,106 likes); agents
  "nail the first screen then drift on spacing and state variants"
  ([@DnuLkjkjh](https://x.com/DnuLkjkjh/status/2045236091784237093)); a screen "looked finished
  in the sim and moved once it was on the device", from two independent iOS makers
  ([@iamvishal16_ios](https://x.com/iamvishal16_ios/status/2116198411691290881)), which is why
  S3 reviews on the phone; Mobbin and Refero on an agent still fail because "just because an
  app is successful doesn't mean the UI is great"
  ([@drbarnard](https://x.com/drbarnard/status/2115918787241554097)), which is why references
  are named screens, not libraries. The closest pin-and-comment tool is Cursor's Design Mode
  Annotate (2026-10-27, 337,702 views), a web browser inside Cursor
  ([@cursor_ai](https://x.com/cursor_ai/status/2115159585548021814)); no post shows a vision
  judge whose score rose in a later build, and a weekly X scrape "will learn listicles and
  prompt art", so the scout's caps stand. Accounts worth a weekly read: @viticci (what the
  system UI just did, with screenshots), @Dimillian (UI a strong indie shipped), @drbarnard
  (when a design skill or a library fails, by name), and the Apple Design Awards page (2026:
  Moonlitt for interaction, grug for delight, Structured a finalist whose model pre-fills a
  simple timeline). Planner complaints: a Tiimo user left because the companion "is all over
  the app" and wanted a switch to remove it
  ([@ascottishbean](https://x.com/ascottishbean/status/2112292021939392959)), while another
  copies how Tiimo centres the character; Flighty "occasionally, randomly deletes flights"
  ([@patk](https://x.com/patk/status/2114538198508667070)); Wanderlog's praised features are
  distances and walk or transit time between stops, a forwarding address for bookings, and
  inviting friends to plan (861,148 views). Nobody on X ships trip + day + family + companion
  in one app. For the pilot this means: the companion is one tap away and never on every
  screen, and nothing the user planned is ever lost silently.

## 4. Decisions

- **S1. Studio is part of Teyla, one system, three lanes.** Not a separate product and not
  two. One tap on one screen carries a layout comment and a copy comment; splitting them
  splits the ledger. Teyla already holds the standard, the checks, the owner's words, the
  phone relay and the session video, and Teyla's users are solo builders with agents, the
  people who need this most. The lanes: **look** (UX/UI), **say** (copy and voice) and
  **show** (brand kit, screenshots, video, posts). A product's own files stay in its repo;
  Teyla holds the standard, the tools and the shared reference library.
- **S2. Truth lives in code, tokens and rendered screenshots.** No Figma round trip. DTCG
  tokens per product, generated to every platform (the planner's `Design/tokens` is the model).
  Figma stays a read-only reference if a designer ever joins.
- **S3. The owner reviews the real app on the phone, by tapping and talking.** Not a mock,
  not a screenshot in a chat. Every capture carries the screen, the element, the picture,
  the build and the transcript, and lands in one inbox on the Mac.
- **S4. Every comment becomes a decision; only owner-confirmed decisions become rules.**
  The agent triages a comment into fix, rule or reject and says why. A rule is proposed, never
  promoted on its own: automatic promotion would preserve misunderstandings. The owner
  confirms from the phone in one tap. A decision is scoped (one screen, one component, or the
  product) and dated; a scoped decision never widens on its own.
- **S5. A product's design file is short, current and executable.** `DESIGN.md` holds what an
  agent needs before touching a screen: tokens, the component list with file paths, the
  glossary, the screen inventory, what is absent. History goes to `docs/decisions/`, taste to
  the ledger. `teyla ux check` fails a `DESIGN.md` over 100 lines and a standard with more
  than 20 active rules; a lane is given the rules that match the screen it touches, not the
  whole file. Shipped in sprint 1: the template has the sections Tokens, Components, Glossary
  (one word per concept, columns en/es/ru), Voice, Screens and Rules from review (the last two
  between `<!-- teyla:screens -->` and `<!-- teyla:rules -->` markers that `teyla taste render`
  fills) and What is absent. In the standard an active rule is a `### R<n>.` heading with a
  `Since <date> · Scope: ... · Check: ...` line; rules cut to make room go under "Retired or
  advisory". "More than four tap targets" is a WARN and "more than three type sizes" a review
  warning, never a FIX.
- **S6. Drift is caught by a fixed matrix, not by a model's glance.** Screen captures in
  light, dark and the largest Dynamic Type, in every shipped language, diffed against an
  accepted baseline, plus the accessibility audit for clipping and contrast. A UI PR carries
  the diff; the owner accepts a new baseline or the lane explains.
- **S7. A vision model judges in pairs and never alone.** Before vs after, A vs B, ours vs a
  reference screen, with the rubric from the standard. Ties and "feels native" go to the
  owner. The score reported per product is the share of screens that beat their reference,
  not a 1–10 feeling. The judge is calibrated against the owner before it is trusted: it must
  agree with him on 16 of 20 pairs he has already decided. The rubric is Part 5 of the
  standard: five items scored 0, 1 or 2 with a written meaning for each score, and "not
  assessed" where the picture cannot show the item.
- **S8. Copy is written by a writer lane from a brief, not by the code lane.** The brief is
  the screen's job, its primary action, the glossary and the product's voice chart. English,
  Spanish and Russian are each written from the brief, never translated. The unit of review
  is a screen's strings as one table on the phone.
- **S9. Taste is mined weekly, proposed as PRs, never applied silently.** Free sources first
  (Apple Design Awards, App Store editorial, iOS release notes, RSS of named designers,
  Reddit threads); X and paid libraries (Mobbin, Refero) only after a §11 price and a yes.
- **S10. Visuals are cut from a brand kit that is a folder, not a mood.** Per product:
  tokens, mascot reference sheet and locked model settings, icon source, voice chart,
  three sample posts, a banned list. Screenshots come from the real app in the capture matrix,
  framed per language by a script. Video comes from screen recordings and `teyla reel`,
  dubbed per language. Posting goes through a queue the owner approves.
- **S11. The machine is a budget.** Nothing in Studio starts an Xcode build or a simulator
  without `teyla load`; the capture matrix is one simulator, one app, one run, and it stops
  the simulator it booted.

## 5. How it works

### 5.1 The loop (lanes "look" and "say" share it)

```
phone                         Mac (Teyla)                              repo
──────────────────────────    ───────────────────────────────────────  ──────────────────────
real app, TestFlight build    teyla review pull                         one PR per screen
  shake → capture overlay       ├ relay outbox (iCloud Drive)             before/after shots
  tap the element               ├ TestFlight screenshot feedback (ASC)    cut list
  speak (on-device dictation)   └ web overlay POSTs                       decisions appended
  → capture.json + png        teyla review triage  ──► fix | rule | reject
                              teyla review open    ──► lane brief ──► agent ──► PR
                              teyla taste confirm  ◄── owner, one tap, from the phone
```

**Capture.** `TeylaReview`, a Swift package in `packages/review-ios/` (SwiftUI, iOS 17+):
a debug overlay that any product adds behind a build flag `TEYLA_REVIEW` (on in TestFlight
Internal, off in App Store builds). An explicit "Review" button in the product's debug menu
starts review mode; shake is a shortcut to the same thing, never the only way in. Review mode
freezes the screen and shows the picture; the owner taps the element and talks. The product
marks its screens and elements with `.reviewAnchor("trip.timeline.addButton")`, which
registers the element id, the screen id, the parent id, the bounds, the role, the string keys
it shows, and the source file and line; the package also records the tap point, the
accessibility identifier and label under the tap, the build number and commit SHA, the
locale, the Dynamic Type size and the appearance. It does not promise the full accessibility
tree: a TestFlight process cannot read it, and the anchors are enough. Dictation uses the
keyboard's own microphone key first (one tap, works in every language the owner types in);
on-device `SFSpeechRecognizer` with the audio kept comes second. If the product was using the
microphone (the planner's voice mode), the package records that state before it takes the mic and
hands it back after. One capture is one `capture.json` plus one PNG, saved on the phone first
and then copied to the relay outbox (`iCloud Drive/Teyla/outbox/review/<id>/`), signed like
every relay action. The phone shows the capture's status as it moves: Saved on phone →
Received → PR ready → Verified on device. Nothing leaves the owner's devices.

**Fallbacks.** TestFlight's own "share feedback" screenshot with a typed or dictated note:
`teyla review pull` reads `GET /v1/apps/{id}/betaFeedbackScreenshotSubmissions` with the key
in `~/.appstoreconnect/` (the one `~/ops/bin/testflight` uses) and files each one as a
capture without element data; it also serves family testers who have no overlay. Web: a
20-line overlay script, included only when `?review=1`, that posts the same capture shape to
`teyla review serve` on the Mac (Tailscale or cloudflared for the phone).

**Inbox and triage.** `teyla review` lists captures newest first, per product, from a SQLite
queue in `~/.teyla/review/`; captures are keyed by their UUID so a folder synced twice is
one capture, and a lane that takes one holds a lease, so two sessions never work the same
capture. `teyla review triage <id>` runs Sonnet 5.5 with the capture, the product's
`DESIGN.md`, the rules that match the screen, and the last 20 ledger entries, and writes one
decision: `fix` (one line of what changes, the
file from the identifier path, an effort guess), `rule` (a proposed rule in the standard's
wording, with the capture as its example), or `reject` (why, in one line). Several captures
of one screen become one brief. `teyla review open <ids>` writes the lane brief (captures,
decisions, the screen's strings, the checks to run) and starts the lane, or prints the brief
for a running session. The lane ends with a PR that carries before/after captures from the
matrix (5.2), the cut list, and `decisions.jsonl` lines for the ledger.

**The taste ledger.** `design/decisions/<id>.json` in the product's repo, one file per
decision: `{date, screen, element, comment, decision, scope, rule?, capture, pr, confirmed}`.
Beside it: `design/screens/<screen>.yaml` (the inventory entry: job, primary action, states,
string keys), `design/rules/<rule>.yaml` (one active rule: wording, scope, the capture that
started it, the date, the owner's confirmation) and `design/references/<screen-type>.yaml`
(the reference screens it is judged against). `DESIGN.md` is rendered from these files, which
is how it stays under 100 lines. `teyla taste` shows the open rules; `teyla taste confirm
<id>` (from the Mac, or from the phone's question list) sets `confirmed` and writes the rule
file. A rule that holds for every product is moved to `templates/design/STANDARD.md` by hand,
in a Teyla PR, and the standard never carries more than 20 active rules. Rejections stay in
the ledger so the next lane does not propose them again.

### 5.2 The matrix (drift)

`teyla ux shots <repo>` builds the app once (behind the machine guard), boots one simulator,
runs the product's screenshot tour and shuts the simulator down. The tour is an XCUITest
driven by a manifest, `design/tour.yaml`: a list of routes and the states to show on each
(empty, loaded, error, listening), with fixed dates, seeded data and a stubbed network so two
runs of one build look the same. The one product that already has a screenshot tour is the template; the planner
starts with three flows, not every screen: plan today, add or change an activity, start and
stop voice. Each screen is captured in light, dark and the largest accessibility text size,
for every shipped language, to `design/shots/<variant>/<screen>.png`; the run also calls
`performAccessibilityAudit` and walks the accessibility elements for frames that overlap,
leave the screen, carry truncated text, or offer a tap target under 44 × 44 pt. A flow is run
three times; a screen that differs between runs of the same build is reported as unstable,
which is the "works unstably" the owner sees. The warm budget is nine minutes on the laptop;
a tour that runs longer is cut, not tolerated. `teyla ux diff` compares the run with
`design/shots/baseline/` (pixel diff with a threshold per screen, masks for clocks and maps)
and prints the screens that changed, with a side-by-side image per screen. `teyla ux accept`
makes the run the baseline, and only the owner runs it. Web products get the same through
Playwright `toHaveScreenshot`; Compose through the same tour on an emulator, later. A UI PR
without a diff in its body is refused by the review gate the way an unreviewed PR is. The PR
says "no diff on the manifest's screens", never "no drift": a screen the manifest does not
list was not checked.

### 5.3 The judge

`teyla ux judge A.png B.png` asks Sonnet 5.5 which of two screens is better on five items,
each scored 0, 1 or 2 for each screen: task hierarchy (is the primary action obvious), native
conventions (does it use the platform's own controls and placements), readability (type
sizes, contrast, truncation), layout coherence (spacing, alignment, one grid), and copy and
brand fit (the voice chart, the glossary). An item the picture cannot show is marked "not
assessed", never guessed. It returns the winner with one line per item. It runs on every
before/after pair of a UI PR and on "ours vs reference" pairs from the reference library
(5.5). Before it is used on a product, it is calibrated on 20 pairs the owner has decided and
must agree on 16; the calibration set lives in `design/references/calibration/`. A product's
score is the share of its screens that beat their reference; the owner's tie-breaks are
ledger entries. The judge never gates a merge on its own; the diff and the owner do.

### 5.4 Copy (lane "say")

`teyla copy brief <repo> <screen>` writes the writer's brief from the screen's inventory
file: the screen's job and primary action, its states (a voice screen has ready → listening →
processing → responding → interrupted → failed, and each state names what the user hears and
reads), the glossary, the voice chart, the strings the screen shows today with their controls
and length budgets (button 3 words, title 5, empty state 2 sentences, error 2 sentences,
onboarding step 25 words). `teyla copy write` runs the writer (Sonnet 5.5, one call per
language from the same brief, never from another language; Spanish is es-ES, said so in the
brief) and produces one table: key · control · state · budget · en · es · ru. `teyla copy
judge` runs a second model family (GPT-6.1 Sol through `codex-lane`, POLICY §2) against the
chart, the budgets and Apple's writing rules (no "oops", no "we" in an error, no "Your" before
a noun, a verb on every button) and marks every row pass or fail with one reason. The owner
reviews one screen-state at a time on the phone, rendered by the real app in the TestFlight
build, not as a table alone; he taps the rows to keep, and `teyla copy apply` writes the
catalog (`xcstrings`, `strings.xml`, `i18n.ts`) and opens the PR. `teyla voice chart <repo>`
scaffolds the product's chart in three languages from its `DESIGN.md` voice section and the
brand kit; a chart is not complete until it carries ten accepted and five rejected lines per
language, taken from the ledger, because a chart without examples is the gap the survey found
in every product.

### 5.5 Taste mining (lane "look", weekly)

`teyla scout design` runs weekly as a routine. Sources in `templates/design/SOURCES.md`, seeded
with the feeds that answered on 2026-10-30 (§3): Apple Developer News and Releases, Apple
Newsroom, the HIG pages as JSON, MacStories, Daring Fireball, Nielsen Norman Group, Smashing,
uxdesign.cc, iOS Dev Weekly, SwiftLee, Swift with Majid, Sarunw, Lenny's Newsletter, and the
owner's intent file. It writes `~/.teyla/scout/design/<week>.md` with at most 20 items (what
changed, with URLs). A finding becomes a proposal only when it meets an observed product
problem: a ledger entry, a capture, or a failed check in the last 30 days. It opens at most
two proposals a week, as PRs against `templates/design/` or a product's `design/rules/` with
the quote, the source and the proposed wording; a proposal nobody confirms in 30 days is
closed. Trends never change a rule on their own. X and the paid libraries (Mobbin, Refero)
sit behind `scout.sources` in `config.toml` and a §11 yes. The reference library,
`templates/design/REFERENCE.md`, holds per screen type (onboarding, list, detail, settings,
chat, voice) three named reference screens with what to copy and a link; the first entries
are the §3 set (Things, Flighty, Structured, Tiimo, ChatGPT voice, Finch).

### 5.6 Brand kit and visuals (lane "show")

`brand/kit.toml` per product, scaffolded by `teyla kit init`: name, one-line promise, tagline
per language, token file path, mascot (name, a 60-word character sheet, `mascot/ref-*.png`
reference images, the image model and its locked settings), icon source, voice chart path,
channels and their formats, a banned list, and provenance for every asset (who or which
model made it, from which prompt and references, on which date). A product has one canonical
character: the planner's is the hat, and the navigator images become the hat's scenes or go. No
image model has been shown to keep a character consistent across fifty images, so before a
model is locked the lane runs one bounded comparison (ten poses, two models, the owner picks)
and records the result in the kit. `teyla kit check` fails a kit with missing pieces. Then:

- `teyla kit shots <repo>`: store screenshots from the matrix captures (5.2), framed with
  captions from `docs/store/captions.json` per language by a Pillow script, in every
  required size; uploaded by the product's own store script.
- `teyla kit image <repo> "<scene>"`: one image of the mascot in a scene, from the reference
  images and the locked model (Nano Banana 2.1 by default, $0.0336 an image; gpt-image-2 as
  the alternative), saved under `brand/out/` with the prompt beside it.
- `teyla reel product <repo>`: a product demo cut from a simulator recording of the
  screenshot tour (or a recording the owner made), captions from the copy table, voice-over
  from a script (OpenAI TTS by default, ElevenLabs when a cloned voice is wanted), vertical
  and square, per language.
- `teyla post draft <repo> --channel x|instagram|tiktok|threads|youtube`: a post from the
  product's chart and a ship event, checked by `teyla voice check`, into `brand/posts/queue/`.
  The unit of work is one flagship pack a week per product that shipped something: one reel,
  one screenshot set, three posts. Publishing is by hand from the queue first; the first
  adapter is YouTube (the only channel whose API needs no audit for a personal channel), the
  rest after their audits.

## 6. Roadmap

Three sprints. Each is two nights of autonomous lanes (Sonnet 5.5 builds, Codex reviews
every PR; Codex's estimate is 11–17 agent-days for the system), one PR per logical unit,
merged into `zaitsew/teyla` and the planner's repo (both merge-approved). Exit criteria
are things the owner can see, and every sprint that touches a product ends with a build he
can install.

### Sprint 1 — the system (2026-10-30 → 11-01), in Teyla

| Lane | Ships | Exit criterion |
|---|---|---|
| A. Capture | `packages/review-ios/` (TeylaReview: review button, shake shortcut, `.reviewAnchor`, keyboard dictation, save-then-upload, status chain), capture schema `docs/REVIEW.md`, relay outbox `review/` | A SwiftUI sample app in the package captures review → tap → dictation into a signed outbox folder; `swift build` and tests pass |
| B. Inbox | `teyla review` (SQLite queue, pull from relay and TestFlight, triage, open), `teyla taste` (decision, rule, screen and reference files; confirm; `DESIGN.md` rendered from them) | A fixture capture becomes a `fix` decision and a lane brief; a `rule` file appears in a fixture repo only after confirm |
| C. Matrix | `teyla ux shots`, `diff`, `accept`, the manifest format `design/tour.yaml`, the a11y walk with the 44 pt check, the 3× stability run, the XCUITest tour template in `templates/design/ScreenshotTour.swift` | On the one product that already has a tour: a run, a baseline, a diff that shows a changed screen; the simulator it booted is shut down |
| D. Judge + library | `teyla ux judge` (five items, 0–2, "not assessed", calibration set), `templates/design/REFERENCE.md` seeded, `SOURCES.md` seeded, `teyla scout design` as a routine with its caps | A pair of fixture screens gets a winner with five lines; a scout run writes the weekly file and opens at most two PRs |
| E. Copy | `teyla copy brief / write / judge / apply` (states in the brief, es-ES, Apple's writing rules in the judge), `teyla voice chart` with the example quota, per-control budgets in the standard | The planner's onboarding strings go through the table and back into `xcstrings` without losing keys |
| F. Kit | `teyla kit init / check / shots / image` with provenance, `brand/kit.toml` template, `teyla reel product`, `teyla post draft` with the weekly pack | The planner's kit passes `check`; one mascot image from the reference sheet; store screenshots for three languages from fixture captures |
| G. Standard | `DESIGN.md` template cut to the executable shape (≤100 lines, rendered from `design/`), `ux check` fails a long one and a standard over 20 active rules, "4 tap targets" and "3 type sizes" become warnings, `docs/STUDIO.md` (this), `COMMANDS.md`, `ROADMAP.md` row 4 | `teyla ux check --all` reports the new findings; docs pass `teyla docs check` |

No lane in sprint 1 starts an Xcode build or a simulator while the machine is CRITICAL;
lane C proves itself on the product with a tour only when `teyla load` allows a build.

### Sprint 2 — the planner pilot (first night the machine allows builds)

The concept changed: the planner is a trip planner and a daily planner with a companion. Everything
public still says "Trip Planner". The pilot uses sprint 1 end to end:

0. The baseline first, before anything changes: the three flows (plan today, add or change
   an activity, start and stop voice) in the matrix, the a11y walk's findings listed, and the
   owner's own score per flow written down. The pilot's target is two points above it.
1. `DESIGN.md` rewritten to the executable shape; the 312-line history moves to
   `docs/decisions/design-history.md`. `design/screens/` for the Today, Trip, Chat/Voice,
   Settings and First-run screens; what is absent.
2. TeylaReview in the TestFlight Internal build; the owner reviews five screens by tapping
   and talking; every capture goes through the loop; the ledger starts.
3. The baseline accepted; the a11y walk's findings fixed; the custom tab bar and toolbars
   retested on iOS 27, where search and the bars changed.
4. Two structural variants per screen for Today, Trip, First run and Voice, judged in pairs,
   the owner picks on the phone. Voice: a pulsing listen state, an icon to end, mute, as
   asked on 2026-10-15. The companion: present on Today and in voice, one tap away elsewhere,
   with a switch to hide it (a Tiimo user left over a companion that was everywhere).
5. Onboarding: three steps or fewer, 25 words a step, the example trip reachable without an
   account.
6. Copy: every string the five screens show through the copy table; glossary settled
   (trip, day, plan, place, moment; one word each) in three languages.
7. Kit: mascot reference sheet from the existing hat and navigator images; icon; store
   screenshots and captions per language; a 30-second product reel; the listing text for
   App Store and Play ("<name>: Trip & Day Planner" as the working shape); README and the
   web front door rewritten from the kit; six posts in the queue.
8. Domain: the current domain stays; a separate domain is the owner's call with a
   price (§11), proposed in the pilot's report.

Exit: the five screens beat their references in the judge, the three flows show no diff and
no instability, the owner's own score per flow is two points above the baseline, and the
build is installed on his phone; the store listing and the README say what the planner is in one
sentence.

### Sprint 3 — every product, weekly

Studio on the other iPhone apps in one train (kit, DESIGN.md shape,
tour, baseline); `teyla scout design` weekly; `teyla ux shots` on every UI PR; a Studio
section in `teyla today` (captures waiting, rules to confirm, screens that drifted).

## 7. What is deliberately not built

- No Figma files, no Code Connect. A designer who joins gets read access to code and shots.
- No absolute design score. Pairs only.
- No automatic rule promotion, no trend-driven rule changes, no automatic posting, no paid
  library or X ingestion before a priced yes.
- No view-level snapshot library for glass surfaces; the matrix is the simulator's picture.
- No new product, no new repo, no new name beyond "Studio" as a section of Teyla.
- No Android or web capture package in sprint 1; the web overlay and the Compose tour come
  with the first product that needs them.

## 8. Risks

1. The capture package cannot map a tap to a SwiftUI view reliably. Mitigation: identifiers
   on every screen (the planner has them in 205 files); the screenshot and the route name are
   enough for a fix even when the element is unknown.
2. The owner still types. Mitigation: the overlay is one shake away in the build he uses;
   TestFlight's own feedback is the second path; both land in the same inbox.
3. Baselines rot and every PR shows a diff. Mitigation: masks, one owner-run `accept`,
   screens listed in the inventory only.
4. The judge flatters. Mitigation: pairs against named reference screens, a second model
   family for copy, the owner's tie-breaks recorded.
5. The machine. Mitigation: one simulator per run, the guard on every build, lanes that
   write Python and Swift packages without opening Xcode.
6. Taste converges on the same files everyone installs. Mitigation: the ledger is the owner's
   picks, the scout proposes only against observed problems, and the reference library names
   screens, not trends.
7. The platform moves under the rules (iOS 27 undid parts of iOS 26 within a year).
   Mitigation: few rules, each dated and scoped; the pilot retests custom bars on iOS 27.
