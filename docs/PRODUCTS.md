# Products: which sessions belong to which product

Teyla files every question, running session and finished task under a product. It used to guess the
product from the session's working directory. That filed a third of one owner's open questions
wrongly: sessions run outside any repo landed under "(no repo)", one product's questions sat under
another product because the session ran in that repo, and a scratch folder became a product named
after the folder. Now the owner writes the map down once, and anything not on the map is
`unassigned`. Nothing is guessed.

## Quick start
```sh
teyla product init                     # propose one product per git repo under code_root (prints, writes nothing)
teyla product init --write             # add the proposed products that are not registered yet
teyla product set app-a aliases=appa,a-app primary=ios focus=true stage=beta
teyla product assign 4dba3b64 app-b    # a question is filed wrongly: move its session
teyla product                          # one line per product
```

## The file: `~/.teyla/products.toml`

```toml
[product.app-a]
name = "App A"                 # display name
repos = ["~/repos/app-a"]      # checkouts; worktrees of these map automatically
paths = []                     # extra directories that belong here (a scratch folder)
aliases = ["appa"]             # words that name it in text, lowercase
stage = "beta"                 # idea | building | beta | live | parked
primary = "ios"                # free text: ios, web, macos...
focus = false

[assign]                       # corrections: session id (or ask id) -> product
"019a2b3c-0000-4000-8000-000000000001" = "app-b"
```

`teyla product` rewrites the file and keeps every key, including ones you add, but not comments.
A file that does not parse reads as empty for `teyla asks` and `teyla state`; the commands that
write refuse to touch it until you fix it.

## How a session finds its product

The first rule that matches wins. `registry.attribute()` returns the product and which rule chose it:
`assign`, `title`, `pr`, `path`, `text`, `checkout` or `unassigned`. `teyla asks --why <id>` prints it.

1. `[assign]` (`assign`): the ask id, else the session id, is listed.
   Example: `"019a2b3c-..." = "app-b"` files that session under `app-b`.
2. The session title (`title`). `registry.match_text` over the title finds exactly one registered
   product; a title that names two makes no match. The title is the subject of the session, so it
   beats the PR link and the directory. Example: a session in `app-a`'s directory titled "Bee Hive
   checkout flow" is `app-b`.
3. The PR link (`pr`). The repo of a `github.com/<owner>/<repo>/pull/<n>` link the session produced
   names a registered product: one whose `repos` entry has that directory name, else one whose id or
   alias is `<repo>`. Two products at the same level make no match. Example: an untitled session in
   `app-a`'s directory ends with a link to `.../app-b/pull/7`; the ask is about `app-b`.
4. The longest `repos` or `paths` entry that contains the session's directory (`path`). A worktree
   maps to its repo: `<repo>/.claude/worktrees/<x>` by path, `~/.worktrees/<repo>/<branch>` by the
   repo's directory name. Example: `~/repos/app-a/ios` is `app-a`.
5. The question text (`text`): `match_text` over the question finds exactly one registered product,
   used only when rule 4 found none. Question text never replaces a registered directory. Example:
   a session run in a scratch folder asks "should Bee Hive get a dark mode?": `app-b`.
6. A git checkout directly under `code_root` that nobody registered (`checkout`): its directory name.
   This is a fact about the disk, not a guess.
7. Otherwise `unassigned`.

The old placeholders `(no repo)`, `(home)`, `(scratch)` and `unknown` no longer appear.

## Commands

| Command | What it does |
|---|---|
| `teyla product [list] [--json]` | One line per product: id, stage, focus star, primary platform, repos. |
| `teyla product show <id> [--json] [--quick]` | One product's page: the header (stage, focus, primary platform, repos, aliases), the questions waiting on you, the open notes, the last 10 sessions and the spend over 7 and 30 days. An unknown id prints one line and exits 2. |
| `teyla product init [--write]` | Proposes products from the git repos under `code_root`. No commit for 30 days proposes `parked`, else `building`. `--write` adds only products not yet present and never changes an existing one. |
| `teyla product add <id> [--repo PATH] [--name N] [--stage S]` | Registers one product. |
| `teyla product set <id> key=value...` | `name`, `stage`, `primary`, `focus`, `aliases` (comma list), `add-repo`, `add-path`. |
| `teyla product park <id>` / `wake <id>` | `park` sets the stage to `parked` and remembers the old one in `stage_before_park`; `wake` restores it. |
| `teyla product core [<id>...] [--clear]` | The core products the home screen leads with. No arguments: the list and where it comes from. With ids: sets `focus` on exactly those and clears it on every other product. `--clear`: clears every focus. Prints each change, the old starred products, and the command that restores them (`undo: ...`). An unknown id changes nothing. See "Core products" below. |
| `teyla product assign <ask-id-prefix\|session-id> <id> [--ask-only]` | Files the session behind an ask under a product and lists the asks that moved. `--ask-only` moves that one ask. |

`teyla products` (plural) is the usage table. Since it also keeps the counters in `~/.teyla/products-cache.json`
(0600; a repo whose probe failed keeps its last good row), the portfolio can show users without running any repo's code.

### Core products

`teyla state --json` carries `portfolio.core`, up to 6 product ids, and `portfolio.core_source`:

- `star`: some product has `focus = true`. The core is exactly the starred products, ranked by spend over 7 days,
  at most 6 (a parked product that you starred stays in).
- `rule`: no product is starred. The core is every product that is not parked and has a weekly user (`wau=` in
  its usage probe) or at least $40 of spend over 7 days, ranked by spend, at most 6.

`teyla product core` prints the list and its source. `teyla product core app-a app-b` pins your own list:

```
app-a: focus false -> true
app-c: focus true -> false
focus was on: app-c
focus is on: app-a, app-b
undo: teyla product core app-c
```

Spend comes from the portfolio cache (`teyla portfolio --refresh`), so a product the cache has not seen counts as $0.

### `teyla product show`

The id is a registered product, or `unassigned` (the sessions nobody filed). Nothing on the page is a new
figure: the product is its registry entry, the questions are `teyla asks` for it (a parked product's muted
asks left out, critical ones first, then the oldest), the notes are `teyla notes` for it, and the sessions and
the spend are the session rows `teyla spend` reads, filed under the product the same way a question is.
Spend is the price at the API list, like everywhere else in Teyla.

Reading the sessions of the last 30 days can take a minute on a large machine. `--quick` leaves out the
sessions and the spend (both are `null`); the Mac app asks for the quick form first, so the page shows at
once, then for the full one. `--json`, version 1:

```json
{"version": 1, "generated": "2026-10-25T09:00:00Z",
 "product": {"id": "sample-app", "name": "Sample App", "stage": "beta", "focus": true, "primary": "ios",
             "repos": ["~/repos/sample-app"], "aliases": ["sampleapp"], "registered": true},
 "asks":     [{"id": "809c2dbd", "age_s": 165983, "severity": "normal|critical", "question": "...", "link": "..."}],
 "notes":    [{"id": "nvju3ja", "text": "...", "created": "2026-10-25T09:15:49Z", "age_s": 60}],
 "sessions": [{"id": "...", "at": "2026-10-23T11:01:37Z", "harness": "claude-code", "model": "claude-opus-5-5",
               "cost_usd": 8.78, "title": "..."}],
 "spend":    {"days_7": 17.57, "days_30": 17.57}}
```

Unknown fields are ignored by the Mac app, so the shape can grow without a new version.

## What parking does

A parked product is quiet. `teyla asks` leaves its asks out of the list and out of the session-start
count, and ends with one line that names the products and how many asks it hid. Critical asks (a
`blocked` session, or security, money and release-failure words) still show, marked `parked`. `teyla
asks --all` or `--product <id>` shows the rest, and `teyla product wake <id>` ends the muting. In the
state snapshot the product's `waiting` counts only unmuted asks and `muted` counts the others. See
[ASKS.md](ASKS.md).

## In the state snapshot

`teyla state --json` takes the product names from this file. `products[]` keeps its fields and adds
`id` (the registry id, same as `name`), `display_name`, `stage`, `focus`, `primary` and `registered`
(false for a product that only exists because sessions ran in a repo). `waiting` counts the asks that
are not muted and `muted` the asks hidden by parking. Every registered product is
listed, parked ones with stage `parked`; `unassigned` is listed last, and only when something waits
under it.

## For other commands

`registry.match_text(text)` returns the products whose id, display name (`name`) or alias appears in a
text as a whole word, ignoring case. A space, hyphen or underscore in the term matches any run of
those, so the id `tool-c` finds "Tool C" and "tool_c".

`registry.attribute(cwd, session=, ask_id=, pr=, texts=)` returns `(product, how)`; `registry.resolve()`
is the same decision by directory alone, and returns the product.
