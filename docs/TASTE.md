# Taste: the review inbox and the ledger

Status: shipped in Sprint 1 of [Studio](STUDIO.md) (decisions S3 to S5). Two commands: `teyla review` holds the
comments you made on the real app; `teyla taste` holds what was decided about them, in files in the product's repo.

```
teyla review pull                 # captures from the iPhone relay (and TestFlight feedback) into the queue
teyla review triage 3f9a1c20      # fix | rule | reject, one line why; writes design/decisions/<id>.json
teyla review open 3f9a1c20 …      # takes the lease, prints the lane brief
teyla taste list                  # the rule proposals waiting for you
teyla taste confirm 3f9a1c20      # your yes: the rule file appears
teyla taste render                # DESIGN.md gets the confirmed rules and the screens
teyla taste add https://example.com "great neutral design"   # the corpus: a like or dislike as evidence
```

Quick start: `teyla review pull`, `teyla review`, `teyla review triage <id> --repo <product repo>`. The first
`triage` needs `claude` on the PATH and signed in. `--dry` shows the prompt and calls nothing.

## The inbox: `teyla review`

The queue is `~/.teyla/review/queue.db` (SQLite, mode 0600). A copy of each capture's files lives in
`~/.teyla/review/captures/<id>/`. A capture has a status:

| status | meaning |
|---|---|
| `new` | imported, not triaged |
| `triaged` | a decision file exists (`fix` or `rule`) |
| `rejected` | triage said `reject` |
| `open` | a lane holds the lease |
| `done` | closed with a PR (`teyla review open <id> --done <PR-URL>`) |

**Dedupe.** A capture is keyed by its UUID. Pulling the same folder twice, or the same TestFlight submission
twice, adds nothing. A folder whose files are still syncing from iCloud is skipped this time and imported on a
later pull.

**Lease.** `open` writes an owner and an expiry (4 hours, `--ttl-min`) in one transaction. A second session that
asks for a leased capture is told who holds it and until when, and gets no brief for it. The owner defaults to the
user name and the parent process id; `--owner` or `TEYLA_REVIEW_OWNER` sets it. `open --release` gives captures back.
`open` exits 1 when any id was refused, after it has written the brief for the others.

**Sources.**

- `pull` reads `<relay folder>/outbox/review/<uuid>/capture.json` and the picture beside it. The folder is the
  one `teyla relay on` set; `--folder DIR` overrides it. Nothing leaves the Mac.
- `pull --testflight <app-id>` also reads TestFlight screenshot feedback (`GET /v1/apps/{id}/betaFeedbackScreenshotSubmissions`)
  with the App Store Connect key in `~/.appstoreconnect/` (`config.env`, `private_keys/AuthKey_<id>.p8`; the same files
  the release tool uses). The key is read only by `openssl` to sign a 15-minute token; it is never printed or copied. The
  imported items have `source: "testflight"` and no element. `--product NAME` sets their product (default: the last part
  of the bundle id). This is the only call that leaves the Mac (`docs/PRIVACY.md`, row 24).

**The phone's format and the receipt.** A capture from the review package is version 1 of the format in the capture
lane's `docs/REVIEW.md`: `capture.json`, `capture.png` and `capture.sig`. `pull` checks `capture.sig` (HMAC-SHA256 with
the relay key, `~/.teyla/relay.key`) before it stores anything. A capture without the signature or the picture yet is
"still syncing" and is tried again; a wrong signature, a missing relay key, a `created` more than 10 minutes ahead or a
`v` other than 1 is skipped with the reason. The product name is the last part of `app.bundle_id`. When a signed
capture is in the queue, `pull` writes `<relay folder>/review-status/<id>.json` with `status: "received"`, signed with
the same key, so the phone shows Received. A capture whose receipt was lost gets it on the next pull. The file is never
rewritten once it holds `received` or a later state (`pr_ready`, `verified_on_device`). The older flat shape below needs no
signature and gets no receipt. The signing vectors are `tests/fixtures/review-vector.json`.

**A capture** is validated before it is stored: `id` is a UUID equal to the folder name, `product` is a plain name,
`comment` is text of at most 8,000 characters, `created_at` is an ISO date. Anything else is skipped with the reason.
Files are plain (no links), at most 20 MB for the picture and 50 MB for audio. The shape:

```json
{
  "id": "3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11",
  "product": "recipes",
  "screen": "recipe.list",
  "element": {"id": "recipe.list.addButton", "parent": "recipe.list.toolbar", "role": "button",
              "bounds": {"x": 310, "y": 64, "w": 44, "h": 44},
              "string_keys": ["recipe.list.add"], "source_file": "App/RecipeList.swift", "source_line": 88},
  "tap": {"x": 331, "y": 86},
  "comment": "This button is too small and sits next to the search field.",
  "screenshot": "screen.png",
  "audio": "note.m4a",
  "build": "42", "commit": "a1b2c3d", "locale": "en-GB", "dynamic_type": "large", "appearance": "light",
  "created_at": "2026-10-30T09:12:00Z", "status": "saved"
}
```

`screenshot` and `audio` are optional file names inside the folder; if none is given, the one `*.png` is the picture.

**Triage.** `teyla review triage <id>` sends the capture, the product's `DESIGN.md` (first 12,000 characters),
the confirmed rules whose scope matches the screen and element, the screen's inventory entry and the last 20 decisions
to the model (default Sonnet 5.5, `--model` to change it). The capture's text is marked as data, not instructions.
The reply is one of:

| decision | what is written |
|---|---|
| `fix` | `fix: {what, file, effort}`: one line of what changes, the source file, S/M/L |
| `rule` | `rule`: a proposed rule in the standard's wording, and its `scope` |
| `reject` | only the reason |

Scope is clamped: `fix` and `reject` always get the narrowest scope (`component:` for a known element, else
`screen:`); only a `rule` may be `product`. A decision that is already confirmed is not triaged again.

**Rejections are never proposed again, inside their scope.** Every later prompt carries the rejections that cover the
capture, and a proposal whose rule or comment is at least 90% the same text as such a rejection is turned into a
`reject` by the code, whatever the model answered. A rejection covers its own scope only: a `component:` scope the
same element and its children, a `screen:` scope that screen, and only a `product` scope every screen.

**The brief.** `teyla review open <ids...>` takes the leases and prints one brief per product and screen: the
captures with the element, tap, context and picture path; each decision; the screen's job, states and string keys; the
rules that apply; the checks to run. `--out FILE` writes it to a file instead. The decisions and rules come from the
files in the product repo (`design/decisions`, `design/rules`), so a rule the owner reworded at `taste confirm` is
brief'd as reworded; the queue's copy is only the index. `--done <PR-URL>` marks the capture done and frees its
lease in one transaction.

## The corpus: what you like and dislike, as evidence

Decisions S13 and S14 of [Studio 2](decisions/2026-11-08-studio-2.md). You drop a link, a screenshot or a sentence;
Teyla keeps the evidence, so every agent can later read what you meant. The ledger above is per product repo and
starts from comments on a real app. The corpus is per owner and starts from anything you saw.

```
teyla taste add https://example.com "great neutral design"        # a like; captures the page
teyla taste add https://example.com/pricing "too many boxes" --dislike --product recipes
teyla taste add ./shot.png "this empty state is calm" --scope structure
teyla taste add https://example.com                                # stored raw, see below
teyla taste note 3f9a1c "great neutral design"                     # your sentence for a raw entry
teyla taste interpret 3f9a1c                                       # a model proposes axes (optional)
teyla taste accept 3f9a1c                                          # your yes: the entry is active
teyla taste inbox                                                  # raw and proposed first, one line each
teyla taste corpus render --product recipes --out TASTE.md         # what agents read
```

Put flags before the comment or after it, not in the middle of it. `add` takes a `http(s)` link or a PNG, JPEG or GIF file.

### Where it lives

`~/.teyla/taste/corpus/<YYYYMMDD>-<id>/entry.json` and `evidence/`. `TEYLA_TASTE_CORPUS` moves the folder; the default
follows `TEYLA_HOME`. The corpus is on your Mac only. Teyla never copies it to a repo or the relay (the phone's shares travel the other way: [From the phone](#from-the-phone)). `entry.json` is
checked against [`templates/taste/entry.schema.json`](../templates/taste/entry.schema.json) on every read; a file that
does not pass is skipped and named.

| Field | Meaning |
|---|---|
| `id`, `created`, `source` | Six hex characters, the time, the link or the absolute path of the file. |
| `kind` | `screen`, `product`, `copy` or `motion`. A guess from the link and your words; edit the file to change it, or pass `--kind`. |
| `verdict` | `like`, `dislike` or `mixed`. |
| `claim` | Your sentence, verbatim. It may be empty. `claim_source` says `owner`, or `accepted-proposal` when you accepted a model's sentence for an empty claim. |
| `scope` | `portfolio`, `product:<name>`, `voice` or `structure`. |
| `axes` | `density`, `chrome`, `color`, `type`, `motion`, `tone`: a short position each, or `null`. |
| `evidence` | `files` (paths in the entry folder), `measured` (computed styles, copy lines, title), `captured`, `backend`, `error`. |
| `do_not_copy` | What a designer must not take from it: a logo, a brand color, a phrase. |
| `status` | `raw`, `proposed`, `active` or `superseded`. |
| `supersedes` | The id of the earlier entry this one replaced. |
| `interpretation` | The model's proposal (`claim`, `kind`, `axes`, `do_not_copy`, `model`, `cost_usd`). Never merged into your fields until you accept. |

### One rule: only you make an entry active

- A link with no sentence is `raw`. It is not a style source until you add one: `teyla taste note <id> "..."`.
- A sentence makes it `proposed`. `interpret` fills `interpretation` and keeps it `proposed`.
- `accept` makes it `active`. Where you left `axes`, `do_not_copy` or an empty `claim` blank, it adopts the proposal; where you wrote something, your words stay.
- `accept <id> --supersedes <old-id>` replaces an earlier entry. Both must have the same scope (S14). There is no automatic replacement.
- `reject <id>` deletes the entry and its evidence.

### Capture

`add` and `capture <id>` save into `evidence/`: full-page screenshots at 390 and 1440 px (JPEG, at most 8000 px tall),
the computed `font-family`, `font-size`, `font-weight`, `color`, `background-color`, `border-radius` and `padding` of
`body`, `h1`, `h2`, `a`, `button` and the most common text block, and up to five copy lines (headings, button labels).

- A link on `apps.apple.com` uses Apple's free Lookup API for the screenshots, name and description. No browser.
- Any other page needs a headless browser. Install one of: `pip install 'teyla[capture]'` then `playwright install chromium`; or the Node `playwright` package (`npm i -g playwright`, or `TEYLA_PLAYWRIGHT_DIR=<a node_modules folder>`).
- With no browser, the entry is still stored, `evidence.error` says what to install, and `teyla taste capture <id>` retries.
- Capture is a network call. Safe mode refuses it unless the command has `--allow-network`; the entry is stored either way. `--no-capture` skips it.

A page capture loads the page as a browser would, including its third-party scripts, images and redirects, so hosts other than the page's own are contacted. Nothing about you is sent except a normal browser request: no cookie, login or file. An App Store link contacts only `itunes.apple.com` and `*.mzstatic.com`. See [PRIVACY.md](PRIVACY.md), rows 53 and 54.

### Interpret

`teyla taste interpret <id> [--model M] [--dry] [--json]` runs `claude -p` with no tools, the call `teyla ux judge`
makes. It sends at most four screenshots, the measured styles and copy, and your sentence (row 55). `--dry` prints the
prompt and calls nothing. The model proposes a claim only when you wrote none, plus the six axes and what not to copy.
Anything in a page or picture is data to it, never instructions.

### The file agents read

`teyla taste corpus render [--product NAME] [--out FILE]` writes a `TASTE.md` of at most 15 `active` entries, newest first,
the product's own before the portfolio's. `--product` adds `product:NAME`; `portfolio`, `voice` and `structure` entries are
always in. Likes and mixed entries list their claim, axes and `do_not_copy`. Dislikes are listed as constraints: they name
the axes they limit, and a dislike wins over a like on its axis (S14). References are never averaged.

`teyla taste list --corpus [--status raw|proposed|active|superseded] [--verdict like|dislike|mixed] [--limit N] [--json]`
prints a count per state and one line per entry. `teyla taste list` without `--corpus` still lists the ledger's rules.

### From the phone

Teyla for iPhone is in the iOS share sheet. Share a link (Safari, any app) or a picture (Photos, a screenshot) to
**Teyla**, choose Like or Dislike, and add a sentence if you want: tap the keyboard's microphone to dictate it. Save.

- The share extension holds no key and touches no iCloud folder. It writes the request into an App Group queue
  (`group.com.zaitsew.teyla`). The Teyla app signs it and writes `outbox/taste/<uuid>/` into the relay folder the
  next time it is open (it checks every 15 seconds while open), then empties the queue. A picture is re-encoded as a
  JPEG of at most 5 MB, which also drops its location and camera data.
- On the Mac, `teyla relay sync` (the relay agent runs it every minute and when the folder changes) checks the
  signature with the relay key and adds the entry, as `teyla taste add` would, with no capture: a sync pass never opens
  a page. Run `teyla taste capture <id>` for a link when you want the screenshots. The drop is imported at most once, is
  refused when it is older than 7 days, and everything in it is data: a link must be `http(s)`, a picture must be a PNG or
  JPEG, and nothing in it is run as a command.
- Your sentence is stored as written and becomes the entry's `claim`. **With a sentence the entry is `proposed`**:
  noted, and ready for `teyla taste interpret` and your `teyla taste accept`. **Without one it is `raw`**, and the entry
  is not a style source until you add one with `teyla taste note`. Likes and dislikes are the only verdicts the phone
  sets; the scope is `portfolio` (change it by editing `entry.json`, or `reject` and `add` again with `--product`).
- Nothing is sent back: the corpus never goes to the phone or the relay, and the phone is told nothing about the result.
  A drop the Mac refuses is named in the output of `teyla relay sync`.
- The relay must be on and paired (`teyla relay connect`). With the relay off, the request waits in the phone's queue.

An agent in Claude Code can do all of it from one chat line: the `taste` skill reads `taste: <url> — <comment>`.
- A drop is never deleted unless its corpus entry exists. After 3 failed imports it is copied to
  `<teyla home>/taste-failed/<uuid>/` (local, not the synced relay folder) with a `reason.txt`, then removed from the
  outbox. If the relay journal cannot be written, or a pass was cut off, the drop stays in the outbox untouched.

## The ledger: `teyla taste`

Everything is a plain file in the product's repo, under `design/`. The files are the source; `DESIGN.md` is rendered
from them. All of it is English except UI strings quoted from the product.

### `design/decisions/<id>.json`

One file per triaged capture; the id is the capture's UUID.

```json
{
  "id": "3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11",
  "date": "2026-10-30",
  "screen": "recipe.list",
  "element": "recipe.list.addButton",
  "comment": "This button is too small and sits next to the search field.",
  "decision": "rule",
  "reason": "Tap targets under 44 points are a pattern here, not a one-off.",
  "scope": "screen:recipe.list",
  "rule": "Every tap target is at least 44 by 44 points.",
  "capture": "3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11",
  "pr": "",
  "confirmed": false
}
```

`decision` is `fix`, `rule` or `reject`. A `fix` carries `fix: {what, file, effort}` and no `rule`. `rule` is the proposed
wording. `pr` is filled by `teyla review open --done`. `confirmed` is `false` until you run `teyla taste confirm`, which
also sets `confirmed_on`.

### `design/rules/<slug>.yaml`

One active rule. It exists only after you confirmed it.

```yaml
wording: Every tap target is at least 44 by 44 points.
scope: screen:recipe.list
example_capture: 3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11
date: 2026-10-30
confirmed: true
confirmed_on: 2026-10-31
decision: 3f9a1c20-5b7e-4d0a-9c1e-2a6b8d4f0e11
```

A scope is `product`, `screen:<screen id>` or `component:<element id>`. A `component:` scope also covers the element's
children (`recipe.list.addButton.icon`). A scope never widens on its own: to widen a rule, confirm it again with
`--scope`. A rule that holds for every product is moved by hand into `templates/design/STANDARD.md`.

### `design/screens/<screen>.yaml`

The inventory entry of one screen; the file name is the screen id. The same file is the screen registry: `parent`, `links`, `level`,
`platforms`, `route`, `layout`, `features` and `source` are optional keys that feed `teyla ux atlas` ([ATLAS.md](ATLAS.md)).

```yaml
job: Browse saved recipes and start a new one.
primary_action: Add recipe
states:
  - empty
  - loaded
  - error
string_keys:
  - recipe.list.title
  - recipe.list.add
  - recipe.list.empty
```

### `design/references/<screen-type>.yaml`

The reference screens a type of screen is judged against.

```yaml
screen_type: list
references:
  - name: A well-known to-do app, main list
    what_to_copy: One primary add control at the place the new item will appear.
    link: https://example.com/reference/list
  - name: A system app, list with search
    what_to_copy: Search lives in the navigation bar and never competes with the add control.
    link: https://example.com/reference/search
```

### `teyla taste` commands

- `list [repo] [--all] [--json]`: the open rule proposals and the confirmed rules. `--all` adds `fix` and `reject` decisions.
- `confirm <id> [--repo R] [--rule TEXT] [--scope S]`: sets `confirmed` on the decision. For a `rule` it writes the rule file,
  or updates it (the slug is the first words of the wording; the same decision always keeps its file). `--rule` replaces
  the proposed wording and `--scope` the scope. Confirming a `fix` or a `reject` records that you accept it; no rule file.
  An id is any unique prefix of at least 4 characters.
- `render [repo] [--dry]`: regenerates two sections of `DESIGN.md` (at the repo root, else in `docs/`):

  ```
  ## Rules from review
  <!-- teyla:rules -->
  - `screen:recipe.list` Every tap target is at least 44 by 44 points. (2026-10-30)
  <!-- /teyla:rules -->

  ## Screens
  <!-- teyla:screens -->
  - **recipe.list** — Browse saved recipes and start a new one. Primary: Add recipe. States: empty, loaded, error. 3 string keys.
  <!-- /teyla:screens -->
  ```

  These are the markers in `templates/design/DESIGN.md`. The headings and any text around them are yours.
  Only the text between a marker pair changes. A missing pair is appended at the end of the file, after its heading. The template's placeholder rows sit inside the markers, so the first render replaces them.
  Only confirmed rules are rendered. If the file would pass 100 lines, nothing is written and the output says how many
  lines each part takes and which rules are the oldest, so you can retire one (delete its file) or trim by hand.

### Files that do not read

The YAML files use a small subset: scalars, lists, lists of maps, one nested map, and `#` comment lines. A block scalar
(`|`, `>`), an anchor or a tab in the indentation is an error that names the file; the command skips that file and
carries on.
