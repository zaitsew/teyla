# Growth: the content factory

`teyla growth` runs content the way the dev factory runs products: a daily rhythm with slots, a queue, drafts,
a review step and a packet you post by hand. The owner films sometimes and approves in a batch. Everything else
is Teyla's job: ideas, drafts, checks, formats, packets.

Daily volume does not come from filming. It comes from what already happens every day: merged pull requests,
releases, agent sessions, the week's spend, corrections, the owner's notes tagged `#content` (or another format tag), the news in
Beyond Intelligence, and the stories the weekly miner finds in his own records. Filmed footage is a richer input a few times a week. A slot never waits for it.

## The formats

A note tag picks the format. A plain `#content` note stays a lesson. If a note carries several tags, the first in this
list wins. Each format has a drafting brief the model gets and a planner prior (how likely the editor passes a draft of
it before the editor's own history moves that number).

| Tag | Format | What it is | Prior |
|---|---|---|---|
| `#spec` | `spec-product` | "What if <product> was truly AI-native?" about another company's product, with a working prototype, marked unofficial. Never one of your own products. Ideas also come from `[[spec_target]]` in the config (`product`, `idea`, optional `founder` or `handle`, an `@name` for the first reply). | story rules |
| `#tvc` | `true-vibe-coding` | A filmed bet: agents get a named job and the owner asks whether it will finish before he is back. `teyla growth ride` and footage make it; a `#tvc` note adds one by hand. A merged PR is a worklog. | 0.4 |
| `#wow` | `wow-use-case` | One surprising real use of an AI product or agent, shown working. | 0.6 |
| `#case` | `case-study` | A business, a startup or a personal-productivity case, with the numbers the facts carry and no others. | 0.55 |
| `#week` | `week-results` | The week in counts Teyla gathered: merged pull requests, items published, calls and meetings you logged. See "Week results". | 0.6 |
| `#ainative` | `ai-native` | "How to become AI-native?", with receipts from the owner's own factory (the facts carry last week's counts too). | 0.5 |
| `#predict` | `prediction` | Where a technology goes, as a dated claim. The model also writes `claim`, one sentence a later post can check; `teyla growth published` stores it as a `prediction` row in the ledger with the day and the post URL. | 0.4 |
| `#viral` | `viral-remix` | Borrows the structure of a viral post, never its claims, numbers, names or wording. The note must carry the source URL; it stays on the item (`source_url`) and never enters the post. A `#viral` note with no URL makes no idea. | 0.35 |
| `#inadviser` | `inadviser-verdict` | A value-for-money verdict on one product, from an `inadviser.com` page the note links (a note with no such URL makes no idea). A verdict on value, never financial advice. | 0.5 |
| `#research` | `research-note` | A research note about a problem or a product before it is built. The product may be one that is in no registry (a planned product): the note names it, the draft says "researching" and never that the product exists, launched, ships or can be tried. A checked claim word fails the draft. | 0.45 |
| `#content` | `lesson` | One thing learned the hard way, and the rule that came after it. | story rules |

**Worklog, Reaction and Product spotlight** fill the other slots from the daily sources (merged PRs, trends, the
14-day product rotation). The number and artifact rules of "The planner" apply to lessons and spec products; the new
formats use their prior and the editor's history.

Ideas tagged `#spec`, `#tvc`, `#wow` are clips (shown on screen); the rest are text first. A note's product is set only
when it is a `public_products` entry (its own product, or the one public product its text names). A note that names a
product you did not list as public is blocked like any other idea.

### Week results

`week-results` uses only counts Teyla gathered, for the last completed ISO week (Monday to Sunday): merged pull
requests (from the portfolio cache; no line when the cache is empty, never a zero), content items published (the
ledger), and calls and meetings you logged yourself (`teyla growth log`; a row an agent only claimed counts for
nothing). The brief says so, and the guard refuses every other number: revenue, MRR, conversion and user counts stay
blocked in drafts, and a `#week` note's own numbers are dropped, so its text gives the angle and the counts give the
facts. One idea is made per completed week by harvest; a `#week` note adds another.

## Calls to action

One call to action (CTA) per post, chosen by format. The model writes the words; the code builds every link and every
tag, so a model cannot invent a link or tag a stranger.

| Format | CTA | Where |
|---|---|---|
| `spec-product` | a question to the founder; the company or founder is tagged **only in the first reply**, never "let's meet" in the post body | first comment |
| `true-vibe-coding`, `wow-use-case`, `inadviser-verdict` | early access | link in the first comment |
| `case-study`, `ai-native` | "tell me about your team, let's talk" | last line of the body |
| `week-results`, `prediction` | follow for the next one | last line of the body |
| `research-note` | "join the research" | form link in the first comment |
| the rest | none | |

- **The early-access link** is `https://accounts.fabriquefutur.com/early/<product>?ref=<platform>`. The product must be
  public and have a form at the accounts hub; a form is named without hyphens (`some-app` is `someapp`). Teyla reads
  which forms exist from the hub's cockpit source (`~/.teyla/gtm/sources/accounts-early-access.json`), so a new form is used
  from the next run; `early_products` in the config replaces that list (an empty list means none). Without a form the
  post carries no early-access CTA, and `teyla growth doctor` says so. The link goes in the first comment on every network, never in the
  post body (a link in the body fails the draft).
- **The research link** is `research_form` in the config (an `https://` address) with `?ref=<platform>`. Without it a
  `#research` draft is held before any model call, with the reason.
- **No comment-gating.** "Comment X to get access", "reply with X to join" and the like fail the leak check
  (`engagement-bait`), and the editor scores them 0.
- **A public CTA never mentions hiring, a job search or an employer** (POLICY section 19; the kinds `hiring`,
  `job-search` and `employer` block a draft). Whether someone can hire the owner is decided in a private conversation.
- The owner's own `edit` is not held to these rules; the factory's drafts are.

## The daily loop

```
teyla growth harvest      new ideas from the sources above (nothing confidential: every idea is scanned)
teyla growth trends       trend ideas scored against your audience (relevance x2, demonstrability x2, novelty, momentum; keep 20/30)
teyla growth plan         fill today's slot of every enabled channel; an empty slot shows as a gap with its reason
teyla growth draft        write the planned items through your `claude -p`, check voice and leaks, then an editor scores the hook
teyla growth review       what waits for you, best editor score first; approve, reject (with a reason) or edit
teyla growth tag ID... --goal GOAL|none   link drafts to a GTM goal (docs/GTM.md, "Drafts and goals"); `none` means no goal
teyla growth packets      one folder per approved item: caption, first comment, media, the platform's upload page
teyla growth publish ID   post an approved item where its network is connected; a packet for the rest
teyla growth published ID URL    paste the post's URL after you posted it by hand
teyla growth engage       today's posts worth a reply, each with an angle; you write the reply
```

A slot balances formats and rotates products. What the editor passes goes first, then the product with the fewest sale
attempts (see "The planner").

## The planner: what passes goes first

The editor passes a draft that has a number and an artifact a reader can open. A fixed score once gave slots to product
spotlights and worklogs the editor then held back, while stories with numbers waited: on 2026-11-04 six of eight
attempts went to weak ideas and the budget ran out. Now `plan` ranks by what passes:

- A **story** is a `lesson` or `spec-product` idea with a number and an artifact (a link, a PR number or a command in
  backticks). It starts at 0.85. A lesson with one of the two starts at 0.55, a bare lesson at 0.35, a reaction at 0.45,
  a worklog at 0.3, a spotlight at 0.1.
- The editor's history moves that number. For each source and format (a PR worklog, a note lesson, a trend reaction)
  Teyla counts the drafts the editor passed and the drafts it held back, and pulls the prior toward the observed pass
  rate: with 9 judged drafts the history carries 75%.
- A product with few sale attempts adds its bonus only to an idea whose quality is 0.25 or more. A product that was never
  sold still gets the next slot (POLICY section 19), but through a story or a real demo fact, not through its summary.
- A **bare product summary** (a spotlight whose only fact is the registry line) cannot make a post. The planner skips
  it, and a draft that reaches the model step fails with `thin: a bare product summary` before any call, so it costs
  nothing.
- When the editor's critique says the facts are too thin, the rewrite is skipped (it may only use the same facts and may
  not add a number), the idea is marked `thin_facts`, and the planner does not give that idea another channel.
  `teyla growth retry` clears the mark.
- `plan` and the slot report of `growth daily` end with the number of unused stories still waiting.

`teyla growth daily` runs harvest, trends, plan, video and draft in that order, each step failing on its own (exit 1 if
one did). Plan sits before draft because draft writes the planned slots. Video sits between them (see "The daily
video"). Set `[growth] daily = true` in Teyla's config
(`teyla config set growth.daily=true`) and `teyla routine install` writes a launchd agent that runs it at 06:30
(`~/Library/Logs/teyla-growth.log`). It is off by default. Nothing is published, and in safe mode the draft step is
skipped.

## Stories: the factory finds its own

A post passes when it has a number and an artifact. Those stories used to exist only when the owner wrote a `#content`
note by hand. The harvest step now finds them itself, at most once a week, in what is already on the Mac:

| Material | What is read |
|---|---|
| `policy` | the rules file (`stories_policy`, default `~/.agents/POLICY.md`), read-only |
| `you` | insights and chore counts of the last `teyla you` report. Never his prompts or quotes |
| `crash`, `load` | `teyla crash` events of 30 days and the load recorder's counts of 14 days |
| `money` | AI spend at API list price from the cached `teyla console money` usage. No subscriptions |
| `pr:<owner/repo>#N` | up to eight merged pull requests of public products from the last 21 days whose title promises a fix and whose description tells what failed |
| `changelog` | the newest entries of the CHANGELOG next to this install (`stories_changelog` points elsewhere) |

One model call (`claude -p`, no tools, two turns at most; PRIVACY row 44) reads that material and returns candidates:
`{claim, numbers, date, artifact, source, source_excerpt}`. The reply is data, and the check that follows is mechanical:

- The excerpt must exist in the material (whitespace-normalised). Every number in the claim, and every number the model
  lists, must appear in the excerpt, and the claim needs at least one.
- The date must be a past day that the material names.
- The artifact must be a GitHub URL of a public product or a `teyla` command that `teyla --help` knows. Otherwise the
  story still enters, marked `artifact_missing`, with a fact that says no public artifact exists. The planner ranks it as a
  partial lesson and the editor decides.
- The leak scan, the private terms and the never-post list run on the claim, the excerpt and the artifact. A story that names
  an employer, a job search, another person or a store-review dispute is dropped.
- A story is told once: its id comes from its excerpt, and a story whose numbers an earlier idea already carries is a repeat.

A candidate that fails a check is dropped and counted by reason (`number-not-in-excerpt`, `excerpt-not-in-source`,
`no-number`, `bad-date`, `future-date`, `date-not-in-source`, `excluded:*`, `leak:*`, `repeat`). The harvest line reads
`7 stories from 9 candidates (2 dropped by the checks: ...)`.

Before anything leaves the machine, each line of the material is scanned. A line that hits the leak scan, a private term, the
never-post list, an unreleased product or an excluded kind becomes `[line withheld]`, and an excerpt cannot span it. A file whose
path looks like a secret store (`.env`, a token, a key, `credentials`, `private_keys`) is never opened. The material is data:
the system prompt says so, and the reply is parsed, never executed.

The gate is `growth_stories.due`: one good run blocks the next for seven days, a failed call retries after one day. Safe mode and
`--no-net` skip the miner. The ledger event is `stories-run`; `config.toml` keys are `stories_policy` and `stories_changelog`.

## Quality: a post worth reading

A full slot is not the goal. A post a builder who does not know you would stop for is. Four steps keep weak drafts out
of your review.

**Chores are not content.** `harvest` skips merged pull requests that are records, docs, bumps, renames, config,
landing-variant decisions or edits to a profile README. They stay in the store as `rejected` with `chore: <reason>`.
A user-visible change, a real failure or a real number passes.

**A PR idea gets its facts at draft time.** Before the model writes, Teyla reads `gh pr view` for the PR (a timeout, one
row in [PRIVACY.md](PRIVACY.md)): the description as quoted data, the diff size, the largest files, labels and the
issue it closes. Every line is scanned and dropped on a hit. A PR with no description and a tweak-sized diff, or a
docs-only diff, becomes `failed` with `thin: ...` and its slot goes to another idea. If `gh` fails the item is held
with a retry hint, never drafted from a title.

**An editor scores every draft.** One more call through the same model function rates four things from 0 to 5: the
hook (would a builder who does not know you stop scrolling), a concrete artifact, a number or a surprise, and a claim
a reader can check. The score is their mean. A draft passes at 3.5 or more with a hook of 3 or more. Below the bar it
gets one rewrite on `[models] rewrite` (Sonnet) with the critique, and the rewrite passes the same checks, including
the rule that every number comes from the facts. Still below the bar, the item stays `draft` with `hold_reason`: it
is not in `growth review`, it does not fill a slot, and `review --all` shows why. The editor never adds a number.
The voice check also refuses meta talk about the post ("the title is the artifact") and hedging ("I make no claim").
`draft_budget` (default 30 calls) covers drafts, retries, editor and rewrites. A spent budget holds the rest.

**Trends are scored by a model, with a reason.** The mechanical score cannot tell whether a builder can try the news
in a day. In the first real run 0 of 8 X candidates survived: a rule killed any candidate whose demo needed more than
a day, though a reaction needs only a test, and the old kills were never looked at again. Now one batch call scores
each candidate for your audience and returns a one-line reason, the test you would run (`what_i_will_try`, up to
8 hours) and, when a real product of another company could be prototyped in a day, a spec-product idea. The bar stays
20/30. A candidate is dropped when it repeats a queued reaction, has nothing concrete to try or needs more than a
working day. Kept reactions carry the reason and the test as facts; kills are logged with the scorer. Rows killed by
the old scorer are scored once more. If the call fails or safe mode is on, the mechanical score runs and says so.

`teyla growth daily` drafts in up to two rounds: if a slot is still empty after the first, it plans again and drafts
the next idea. It ends with a slot report: how many drafts wait, how many the editor held back, which channel has a
gap and why, the cost and the budget left. Prefer one strong post to a filled slot, but the gap stays visible.

## Episodes: ride, ingest, cut

The owner films the ride and the trip; Teyla does the rest.

```
teyla growth ride "<the stakes question>" [--job "<named job>"]   start an episode; prints blockers, refuses nothing
teyla growth ride --end                                           close it and stamp the end time
teyla growth ingest [--folder PATH]                               footage from the iCloud folder into episodes
teyla growth cut ID [--session SID] [--no-footage]                a vertical cut, captions burned in, items in review
```

- `ride` records the question, the job, the start time and the agent sessions active in the last 30 minutes. It
  reports blockers (machine load from `teyla load`, under 5 GB of disk, no ffmpeg, a ride that is still open).
- `ingest` reads `footage_folder` in `config.toml` (or `--folder`), keeps `.mov`, `.mp4` and `.m4v` files, and
  skips what it saw before (name, size, time). A file joins the ride whose window holds its time, else it starts an
  episode. It transcribes with `whisper-cli` only if that is installed and `whisper_model` points to a ggml file you
  downloaded. Otherwise it prints the install line. Teyla downloads nothing.
- `cut` sends the question, the transcript and the outline of the session (`teyla reel`'s redacted story) to
  `claude -p` for an edit script: hook, caption and up to eight segments of 1 to 15 seconds, 60 seconds at most.
  ffmpeg trims, joins and scales to 1080x1920, and caption pictures are laid over each segment. A transcript, an
  outline or a caption that hits the guard stops the cut before anything is sent or rendered. With no footage
  (`--no-footage`, or an episode with none), the vertical comes from `teyla reel` alone, so a screen cut can fill a
  daily slot. One clip item per enabled English video channel (YouTube, Instagram, TikTok) lands in `review`, never
  published. An unfilled slot of the day is taken over instead of doubled.
- An episode is not an idea in the queue and never appears in `review`. The console section shows it under
  `episodes` (stage `filming`, `cutting` or `cut`) and in the `pipeline` counts.

## The daily video

YouTube, Instagram and TikTok take video and nothing else. `plan` never fills their slots with a text post: a slot
holds a clip with a rendered video, or it shows as a gap with the reason (`gap: no recent session ...`). A clip item
with no video file is held at draft time without a model call.

A day with a clip you filmed and cut needs no render: the filmed clip always wins. On a day with none, the video step of
`growth daily` makes one, in this order: the **story vertical** (below), then a **session reel**.

### The story vertical

The best lesson the editor passed becomes a silent 16 to 28 second video: your own words, line by line, big white text
on a plain dark card, the hook in amber from the first frame, a progress bar at the bottom and the artifact (a public
link or a `teyla` command) on the last card. No voice, no stock footage, no model call.

- **Which lesson.** A `lesson` draft of today or yesterday that the editor passed (score and hook at or above the
  bar, which this does not change), not held, not filmed before. A lesson with a number and an artifact goes first,
  then the higher editor score.
- **Which lines.** The lines come from the approved draft, not from a new rewrite. The hook is the first card. The
  body follows one whole sentence at a time, at most 8 words on screen at once, and stops at a sentence end when the
  video would pass 28 seconds. A draft too short for 16 seconds is skipped.
- **Which channels.** One video feeds the three video channels, each with the caption of the draft. The `lesson`
  draft stays a text post for X and LinkedIn.
- **The same gate.** The finished video is read back as below (`frame_gate`). A leak deletes it; any doubt holds the
  clips as drafts.
- **The machine.** The render waits for the machine (`teyla load --wait --kind build`).
- **The reel extra.** Drawing needs Pillow, which ships in the `reel` extra, and ffmpeg. Without Pillow the slot
  says `the reel extra (Pillow) is missing` with the command below, and `teyla growth doctor` shows a `reel extra`
  row. `teyla update` keeps the extra on a Mac that has a growth config.

```
uv tool install --force --python 3.12 'teyla[reel] @ git+https://github.com/zaitsew/teyla'
```

Lessons are drafted after the video step, so a lesson written this morning is filmed tomorrow. When the video step
finds no lesson and no session, `growth daily` tries the story vertical once more after the draft step (a step named
`reel` in its output).

### The session reel

When no lesson qualifies, the video step falls back to a session:

1. It picks a real session from the last two days that was not filmed before (Claude Code or Codex; sessions that
   opened a PR first), finished at least 30 minutes ago, where every repo it touched is a public product. A session
   that touched a private repo is never filmed. It builds the redacted story with `teyla reel`. A story with fewer than three beats, or with
   no commit, passing test run or PR, is skipped. Up to six sessions are tried.
2. It waits for the machine (`teyla load --wait --kind build`), renders a 1080x1920 screen video of about 24 seconds
   with Pillow and ffmpeg on your Mac, and asks `growth cut` for the hook and the caption (up to two repair calls when the caption breaks the voice chart). One file feeds all three
   channels, each with its own caption. Every string the video draws is scanned before the render.
3. It reads the finished video back before you see it: length 10 to 30 s, size 1080x1920, one frame per second taken
   out and read as text with the OCR helper that Filmare installs (`~/.local/share/filmare/bin/ocr`), and the text
   scanned for secrets, e-mails, home paths, your private terms and products you have not released. A leak deletes the
   video. A missing helper, a wrong length or any other doubt keeps the clips as drafts with `hold_reason`: not in
   `review`, and the slot stays a gap. Three frames (first, middle, last) stay next to the video in
   `~/.teyla/growth/episodes/<id>/frames-reel/` so you can look.

Filmare's own `render` is not used here: its first run downloads a 170 MB browser, which needs your yes. `growth cut`
by hand has no frame gate: you watch the clip in `review`. A day with footage you filmed and cut needs no render.

## Publishing

Approving marks a draft. Publishing is a second, separate step, and only for an approved item:

```
teyla growth connect linkedin            # once per network, in your own terminal; the token goes to the macOS Keychain
teyla growth connect --status            # which networks are connected, and for how many more days
teyla growth publish g1107-ab12          # post one approved item (or its approved children, for a master idea)
teyla growth publish --day 2026-11-07    # every approved item planned for that day
```

| Network | API | What goes out | Connect |
|---|---|---|---|
| LinkedIn | Posts API, as you (a member post) | the approved text | a LinkedIn app with "Share on LinkedIn" and "Sign In with LinkedIn using OpenID Connect"; redirect `http://127.0.0.1:8765/callback` |
| Threads | Threads API | the approved text, 500 characters at most | a Meta app with the Threads use case. Meta needs an https redirect: register one, pass it with `--redirect-uri` (or `[publish.redirect]` in the config), and paste the address the browser lands on |
| Instagram | Instagram API with Instagram Login, a professional account | the attached video as a Reel, with the caption | a Meta app; an https redirect, as for Threads |
| YouTube | Data API v3, resumable upload | the attached vertical video as a Short | a Google OAuth client of type Desktop app; redirect `http://127.0.0.1:8765/callback`. An app Google has not audited can upload only private videos: Teyla says so and uploads private until the audit passes |
| X | none | a packet, always | X stays manual. Its API is paid; `x_paid = true` in `[publish]` would need your two yeses, and no X adapter is built |

- `connect` runs only in your own terminal: it asks for the app's client id and secret (hidden), opens the consent page
  in your browser and stores one Keychain item per network (`teyla-growth-<network>`). No token is ever written to a file
  or a log, and the agent never reads one. `teyla growth connect <network> --forget` removes it.
- `publish` is idempotent. Each item and network has a key. A second run of a published item does nothing. A run that started and
  never finished stops with a line that says how to check, and `--retry` posts again only when you say so.
- A refusal (4xx) means nothing went live. A 5xx or a timeout on the last call may have gone live: the item is marked
  `unknown` until you check.
- A network that is not connected, an item with no adapter (X), or safe mode gets today's packet instead, and the line says why.
- Every post lands in the ledger as `published`, with its URL, `by: owner-approved` and `via: api`.
- The Mac admin shows approved items under "Ready to publish" with one button, "Publish to connected networks". It runs
  `teyla growth publish <id> --json` after a confirmation and shows the result per network.

`teyla growth publish --json` prints `{version, results: [{id, network, status, url, message, warning}], published,
already, packets, failed}`. `status` is `published`, `already`, `packet`, `failed`, `unknown` or `refused`. With
`--json` the exit code is 0 and `failed` counts what needs you; without it, a failure exits 1. Two runs of the same item
and network at once cannot both post: the second one is told the first is running.
LinkedIn and Threads send text only: an item with media attached goes out from its packet.

## Engage

`teyla growth engage` lists today's posts worth a reply from the people you follow on purpose. The goal is 20 a day.
Each row has the post, the author, why the group matters and one angle for a reply. It never gives a ready reply: you
write every reply yourself, on the network, then mark it done.

```
teyla growth engage init      # writes ~/.teyla/growth/targets.toml with placeholder handles; replace them
teyla growth engage           # today's list (one cached X scan a day, plus your feeds)
teyla growth engage open 3    # open row 3 in the browser
teyla growth engage done 3 5  # you replied to rows 3 and 5: one activity row, kind reply, by you
teyla growth engage done 3 --url https://x.com/...   # the same, refused if row 3 is another post now
```

- `targets.toml` has four groups: `founders`, `c-level`, `investors`, `builders`. Each takes `x` (handles) and `rss`
  (feed URLs, Substack included). A placeholder handle is skipped.
- The X scan is one `grok -p` call a day with a small turn cap, cached in `engage/<day>.json`. `--refresh` runs it once
  more; the second refresh of a day reads the cache. `--no-scan` reads the cache only.
- A row keeps only an `x.com` status link by a handle in your targets file, and only an angle short enough to be an angle.
  A post you replied to in the last 14 days does not come back.
- `done` from an agent session is logged as a claim (`by: agent`), and the activity graph shows it apart. The
  owner marking the same row afterwards is logged too, as the confirmation.
- A refresh keeps the rows you already marked done, and keeps the X rows when it cannot scan again today.
- The Mac admin's Growth page has an "Engage" section: ↑ and ↓ move, Return opens the post, D marks it done. The iPhone
  shows the count as "Replies today".

`teyla growth engage --json` prints `{version, day, generated_at, goal, total, done, rows: [{n, url, author, group, why,
angle, source, date, text, done}], sources: {x, rss}, notes, targets: {exists, x, rss, placeholders, errors}}`.
`teyla console growth` carries `engage {day, scanned, total, done, goal}`.

## Store

Everything lives in `~/.teyla/growth/` (folders mode 0700, files 0600), never in a repo:

| Path | What |
|---|---|
| `config.toml` | channels (platform, language, enabled, posts per day), public products, models, `footage_folder`, `whisper_model` |
| `items/<id>.json` | one idea or post: kind, format, idea, hook, body, facts, sources, score, checks, status |
| `ledger.jsonl` | append-only events: assign, draft, approve, reject (with the reason), packet, published, attempt, ride, ingest, cut, video, daily |
| `episodes/<id>/` | an episode's transcript, the cut video and its captions file |
| `packets/<day>/<platform>-<language>/` | `caption.txt`, `first-comment.txt`, the media, `upload.url` |
| `targets.toml` | the people and feeds `engage` reads, in four groups |
| `engage/<day>.json` | the day's engage list, cached |

Item status runs `idea`, `draft`, `checked`, `review`, `approved`, `ready`, `published`; `failed` and `rejected`
end an item. Only an approved item gets a packet or a published mark.

## Guardrails

- A draft names only products you list as `public_products` in the config. Everything else is "unreleased".
- Every draft and every idea is scanned by the leak scanner and your private terms file. A hit blocks the item and
  names the kind of the term, never its value.
- A draft never mentions a job search, hiring or an employer, revenue, MRR, conversion or user counts, money advice,
  politics, health or family, never gates something behind a comment, and every number in it must appear in the facts
  Teyla gathered.
- The voice chart of the language decides the voice. A draft is written in its language, never translated. It
  passes `teyla voice check` or it fails, after one retry.
- Teyla publishes nothing by itself. An item goes out only after you approved it and then ran `teyla growth publish`
  (or clicked "Publish to connected networks"), and only through a network's official API that you connected.
  It never replies, likes, follows, sends a DM or a cold email, and it never scrapes.
- AI-dubbed audio is labelled in the caption.
- Model calls go through one function, with a timeout and a per-run budget (`draft_budget`, default 30).

## Sale attempts

`teyla growth sale-attempts` counts, per product, posts, marketing and ICP meetings from the ledger. A product with
zero attempts reads "not tried yet" and gets the next slots. No view proposes closing a product that nobody tried
to sell. Log what happens outside Teyla with `teyla growth log [--product P] --kind KIND [--count N] [--day YYYY-MM-DD]`,
where KIND is `post`, `comment`, `reply`, `email`, `dm`, `call`, `meeting`, `icp-meeting`, `ad`, `outreach` or `response`.
A post counts as a post; an ad, outreach, comment, reply, e-mail, DM, call or meeting as marketing; an ICP meeting as an
ICP meeting. A `response` (someone answered you) is an outcome, not an attempt. `--product` is optional (a comment is
often not about one product); a row without a product stays out of the per-product counts. `--count` (1..50) logs several
at once; `--day` backdates a row by up to 7 days.
Run from an agent session, the row carries `by: agent`: it is *claimed*, shown as a count beside the product, and counts
for nothing until you log it yourself. A product with `type = personal` is not for sale, so it is never "not tried yet".

## Activity

`teyla growth activity [--weeks N] [--json]` draws a GitHub-style graph of your marketing and sales activity: any post,
comment, reply, e-mail, DM, call, meeting, ad or outreach is +1 (`--count` adds more). Weeks are ISO weeks, Monday first,
the window ends today (local date). Levels 1..4 come from the quartiles of the non-zero days. The streak is the run of
days with at least one +1 that ends today, or yesterday when today has none. Published posts count too. A row logged
from an agent session is a claim: it is counted in `claimed` and in no day. `response` rows are not +1; they show as
an outcome beside the meetings held (`meeting`, `icp-meeting`, `call`).

JSON (`version` 1): `today`, `weeks`, `start`, `days` (every day from `start` to `today`, oldest first, each
`{day, count, level, kinds}` with non-zero kinds only), `total`, `today_count`, `week_count`, `streak`, `longest`,
`by_kind` (non-zero kinds), `outcomes` (`meetings`, `responses`), `claimed`, and `kinds` (the list an app builds its +1
menu from).

## Outreach

`teyla growth outreach` is read-only. It shows counts from BaTrack (a count only; the job search never appears in
content) and any product listed in `outreach_repos` in the config, when their cached usage probes carry them, and says "not connected" otherwise. Teyla drafts and
never sends. A draft row has a copy action and a profile URL; you send it yourself.

## Setup

```
teyla growth init --public teyla        # writes ~/.teyla/growth/config.toml
teyla growth doctor                     # what is missing, one line each
```

`doctor` checks the voice chart, ffmpeg, filmare, whisper, Beyond Intelligence, grok, claude, the private terms
file, the research form link and the early-access forms of your public products. For speech to text it prints `brew install whisper-cpp` and the model size; it downloads nothing.
Platform credentials are not needed: the manual packet works with none. `teyla growth connect` adds them, network by network.

## The console

`teyla console growth` carries today's posts per channel, the queue depth in days, the pipeline counts, the top five
trends, the outreach counts and the qualified conversations this week. The phone's compact form has counts only.
See [CONSOLE.md](CONSOLE.md).

## Limits

- One channel gets at most `posts_per_day` items a day. The default is one per channel.
- One idea feeds at most `fanout` channels (default 3).
- A language other than English needs its voice chart. Without one the item fails its check.
- Privacy: the calls that leave the machine are listed in [PRIVACY.md](PRIVACY.md): rows 37 to 41 and 44, publishing
  (rows 46 to 49, only for a network you connected) and engage (rows 50 and 51). Transcription and video work stay on your Mac.
