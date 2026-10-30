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

**Rejections are never proposed again.** Every later prompt carries the product's rejections, and a proposal whose
rule or comment is at least 90% the same text as an earlier rejection is turned into a `reject` by the code, whatever
the model answered.

**The brief.** `teyla review open <ids...>` takes the leases and prints one brief per product and screen: the
captures with the element, tap, context and picture path; each decision; the screen's job, states and string keys; the
rules that apply; the checks to run. `--out FILE` writes it to a file instead.

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

The inventory entry of one screen; the file name is the screen id.

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
  <!-- teyla:rules:start -->
  ## Rules from review
  - `screen:recipe.list` Every tap target is at least 44 by 44 points. (2026-10-30)
  <!-- teyla:rules:end -->
  <!-- teyla:screens:start -->
  ## Screens
  - **recipe.list** — Browse saved recipes and start a new one. Primary: Add recipe. States: empty, loaded, error. 3 string keys.
  <!-- teyla:screens:end -->
  ```

  Only the text between a marker pair changes. A missing pair is appended at the end of the file with its heading.
  Only confirmed rules are rendered. If the file would pass 100 lines, nothing is written and the output says how many
  lines each part takes and which rules are the oldest, so you can retire one (delete its file) or trim by hand.

### Files that do not read

The YAML files use a small subset: scalars, lists, lists of maps, one nested map, and `#` comment lines. A block scalar
(`|`, `>`), an anchor or a tab in the indentation is an error that names the file; the command skips that file and
carries on.
