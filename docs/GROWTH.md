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
teyla growth trends       scored trend ideas (customer relevance x2, demonstrability x2, novelty, momentum; keep 20/30)
teyla growth plan         fill today's slot of every enabled channel; an empty slot shows as a gap
teyla growth draft        write the planned items through your `claude -p`, then check voice and leaks
teyla growth review       what waits for you; approve, reject (with a reason) or edit
teyla growth packets      one folder per approved item: caption, first comment, media, the platform's upload page
teyla growth published ID URL    paste the post's URL after you posted it
```

A slot balances formats and rotates products. The product with the fewest sale attempts goes first.

`teyla growth daily` runs harvest, trends, plan and draft in that order, each step failing on its own (exit 1 if one
did). Plan sits before draft because draft writes the planned slots. Set `[growth] daily = true` in Teyla's config
(`teyla config set growth.daily=true`) and `teyla routine install` writes a launchd agent that runs it at 06:30
(`~/Library/Logs/teyla-growth.log`). It is off by default. Nothing is published, and in safe mode the draft step is
skipped.

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

## Store

Everything lives in `~/.teyla/growth/` (folders mode 0700, files 0600), never in a repo:

| Path | What |
|---|---|
| `config.toml` | channels (platform, language, enabled, posts per day), public products, models, `footage_folder`, `whisper_model` |
| `items/<id>.json` | one idea or post: kind, format, idea, hook, body, facts, sources, score, checks, status |
| `ledger.jsonl` | append-only events: assign, draft, approve, reject (with the reason), packet, published, attempt, ride, ingest, cut, daily |
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
- Model calls go through one function, with a timeout and a per-run budget (`draft_budget`).

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
- Privacy: three calls leave the machine, all listed in [PRIVACY.md](PRIVACY.md) (rows 37 to 39). Transcription and video work stay on your Mac.
