# Growth: the content factory

`teyla growth` runs content the way the dev factory runs products: a daily rhythm with slots, a queue, drafts,
a review step and a packet you post by hand. The owner films sometimes and approves in a batch. Everything else
is Teyla's job: ideas, drafts, checks, formats, packets.

Daily volume does not come from filming. It comes from what already happens every day: merged pull requests,
releases, agent sessions, the week's spend, corrections, the owner's notes tagged `#content`, and the news in
Beyond Intelligence. Filmed footage is a richer input a few times a week. A slot never waits for it.

## The formats

- **True Vibe Coding** is a filmed bet: agents get a named job, and the owner asks whether it will finish before he is
  back from a ride or a trip. Only `teyla growth ride` and footage make this format. A merged PR is a worklog.
- **Spec Product** works like a spec ad, about another company's product: "What if <product> was truly AI-native?", with
  a working prototype, marked unofficial. It never targets one of your own products. Ideas come from `[[spec_target]]`
  in the config (`product`, `idea`) and from notes tagged `#spec`.
- **Worklog, Lesson, Reaction and Product spotlight** fill the other slots from the daily sources.

## The daily loop

```
teyla growth harvest      new ideas from the sources above (nothing confidential: every idea is scanned)
teyla growth trends       trend ideas scored against your audience (relevance x2, demonstrability x2, novelty, momentum; keep 20/30)
teyla growth plan         fill today's slot of every enabled channel; an empty slot shows as a gap with its reason
teyla growth draft        write the planned items through your `claude -p`, check voice and leaks, then an editor scores the hook
teyla growth review       what waits for you, best editor score first; approve, reject (with a reason) or edit
teyla growth packets      one folder per approved item: caption, first comment, media, the platform's upload page
teyla growth published ID URL    paste the post's URL after you posted it
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

On a day with no clip, the video step of `growth daily` makes one:

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

## Store

Everything lives in `~/.teyla/growth/` (folders mode 0700, files 0600), never in a repo:

| Path | What |
|---|---|
| `config.toml` | channels (platform, language, enabled, posts per day), public products, models, `footage_folder`, `whisper_model` |
| `items/<id>.json` | one idea or post: kind, format, idea, hook, body, facts, sources, score, checks, status |
| `ledger.jsonl` | append-only events: assign, draft, approve, reject (with the reason), packet, published, attempt, ride, ingest, cut, video, daily |
| `episodes/<id>/` | an episode's transcript, the cut video and its captions file |
| `packets/<day>/<platform>-<language>/` | `caption.txt`, `first-comment.txt`, the media, `upload.url` |

Item status runs `idea`, `draft`, `checked`, `review`, `approved`, `ready`, `published`; `failed` and `rejected`
end an item. Only an approved item gets a packet or a published mark.

## Guardrails

- A draft names only products you list as `public_products` in the config. Everything else is "unreleased".
- Every draft and every idea is scanned by the leak scanner and your private terms file. A hit blocks the item and
  names the kind of the term, never its value.
- A draft never mentions a job search or an employer, revenue or user counts, money advice, politics, health
  or family, and every number in it must appear in the facts Teyla gathered.
- The voice chart of the language decides the voice. A draft is written in its language, never translated. It
  passes `teyla voice check` or it fails, after one retry.
- Teyla publishes nothing by itself. The only publisher is the manual one: you post, then record the URL.
  It never likes, follows, sends a DM or a cold email, and it never scrapes.
- AI-dubbed audio is labelled in the caption.
- Model calls go through one function, with a timeout and a per-run budget (`draft_budget`, default 30).

## Sale attempts

`teyla growth sale-attempts` counts, per product, posts, marketing and ICP meetings from the ledger. A product with
zero attempts reads "not tried yet" and gets the next slots. No view proposes closing a product that nobody tried
to sell. Log what happens outside Teyla with `teyla growth log --product P --kind icp-meeting|ad|post|outreach`.

## Outreach

`teyla growth outreach` is read-only. It shows counts from BaTrack (a count only; the job search never appears in
content) and any product listed in `outreach_repos` in the config, when their cached usage probes carry them, and says "not connected" otherwise. Teyla drafts and
never sends. A draft row has a copy action and a profile URL; you send it yourself.

## Setup

```
teyla growth init --public teyla        # writes ~/.teyla/growth/config.toml
teyla growth doctor                     # what is missing, one line each
```

`doctor` checks the voice chart, ffmpeg, filmare, whisper, Beyond Intelligence, grok, claude and the private terms
file. For speech to text it prints `brew install whisper-cpp` and the model size; it downloads nothing.
Platform credentials are not needed: the manual packet works with none.

## The console

`teyla console growth` carries today's posts per channel, the queue depth in days, the pipeline counts, the top five
trends, the outreach counts and the qualified conversations this week. The phone's compact form has counts only.
See [CONSOLE.md](CONSOLE.md).

## Limits

- One channel gets at most `posts_per_day` items a day. The default is one per channel.
- One idea feeds at most `fanout` channels (default 3).
- A language other than English needs its voice chart. Without one the item fails its check.
- Privacy: five calls leave the machine, all listed in [PRIVACY.md](PRIVACY.md) (rows 37 to 41). Transcription and video work stay on your Mac.
