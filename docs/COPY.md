# Copy: strings from a brief, per language

Status: shipped in Sprint 1 of [Studio](STUDIO.md) (decision S8, section 5.4). The code lane writes the view. The
words come from a writer, one screen at a time, from a brief, in three languages that are each written, never
translated from one another.

```
teyla copy brief recipes recipe.list --out brief.md   # the writer's brief; no network
teyla copy write brief.md                             # en, es, ru: one model call each -> copy.md + copy.json
teyla copy judge copy.json --model                    # code checks, then a second model family
teyla copy apply copy.json recipes --pr               # kept rows into the catalogs, a PR, no merge
teyla voice chart recipes                             # the product's voice chart in three languages
```

Quick start: a product needs `design/screens/<screen>.yaml` with `string_keys` (see [TASTE](TASTE.md)) and `claude` on the
PATH for `write`. `write --dry` prints the prompts and calls nothing. Every file the lane writes sits next to the brief,
or in `--out`.

## `teyla copy brief <repo> <screen>`

Reads `design/screens/<screen>.yaml`, `DESIGN.md` (the glossary table and the voice section), the voice charts and the
strings the screen shows today. It prints a Markdown brief and, between `<!-- teyla:copy-spec -->` fences at the end,
the same facts as JSON for `write`. Spanish is es-ES, and the brief says so.

The brief holds: the screen's job and primary action; its states; the glossary; the voice charts and what each lacks;
the rules; and one row per key with the control, the state, the budget and the current text per language. A key that is
in no catalog gets a note, and the writer still writes it.

**Controls and budgets** (from `templates/design/STANDARD.md`):

| control | budget |
|---|---|
| button | 3 words |
| title | 5 words |
| empty | 2 sentences |
| error | 2 sentences |
| step (onboarding) | 25 words |
| tab, header, label, text | 20 words a sentence |

The control is inferred from the key (`...error`, `...empty`, `...title`, `...button`, `...tab`, `...step`) or from the
text equalling the primary action (then a button). To override, add `controls:` to the screen file.

**Optional fields of the screen file.** Everything is optional; the Taste commands ignore what they do not know.

```yaml
kind: voice                     # or a state named "listening": the six voice states
controls:                       # key: control, where the key does not say it
  recipe.list.saved: label
key_states:                     # key: the state it is shown in, where the key does not say it
  recipe.list.saved: loaded
state_notes:                    # voice screens: what the user hears and reads in a state
  listening:
    hears: a soft tone
    reads: Listening
catalog:                        # where the strings live; default: every catalog that holds one of the keys
  - App/Localizable.xcstrings
  - android/res
i18n: web/i18n.ts               # a web catalog; locales/{lang}.json also works
```

A **voice screen** has the states ready, listening, processing, responding, interrupted, failed. The brief shows a table of
what the user hears and reads in each; a state without a note says `(write it)`.

## `teyla copy write <brief>`

One call per language to Sonnet 5.5 (`claude -p`, no tools, nothing saved; [PRIVACY](PRIVACY.md) row 29). Each call holds
the screen, that language's glossary term, that language's voice chart and that language's current strings. It never
holds another language's text. `--lang en,es` writes some; the others stay as they were. `--dry` prints each system
prompt and payload and calls nothing. Safe mode refuses `write` without `--dry`.

A reply that misses a key is refused and nothing is written. A `copy.json` with `keep` marks is not overwritten without
`--force`.

**`copy.json`**: `screen`, `repo`, `repo_path`, `written` (the languages), `glossary`, `charts`, and `rows`. A row has
`key`, `control`, `state`, `budget`, `en`, `es`, `ru`, and `was` (the text in the catalog before). `copy.md` is the same
table for reading, with a verdict and a reason column after `judge`.

## `teyla copy judge <copy.json>`

Code checks run for every row and language. Each row is marked `pass` or `fail`, with one reason (the first finding; the
rest are in `findings`). Exit 1 when a row fails, 2 on a usage error.

| rule | fails when |
|---|---|
| budget | over the control's budget, or any sentence over 20 words |
| oops | "oops", "whoops", "uh-oh", and the Spanish and Russian interjections |
| we | "we", "our", `nosotros`, the Russian equivalents, in an error |
| your | "Your", `tu`, `su`, the Russian equivalents, before a noun at the start of a label (3 words or fewer) |
| verb | a button that starts with no verb, or is "OK", "Submit", "Yes", "No" |
| please | "please" and its translations |
| bang | an exclamation mark |
| placeholders | a `%@`, `%lld` or `{name}` that differs from the English row, or from the string now in the catalog (the row's `was`) |
| chart | a banned phrase, or a sentence limit, of the language's voice chart |
| hidden | a zero-width or bidi character |
| empty | no text |

Placeholders compare by argument position and type: `%1$@ %2$d` and `%2$@ %1$d` differ, `%2$d %1$@` equals `%@ %d`.
An unpositioned `%@` takes the next position in order. Named ones (`{name}`) have no position. The new text must also match
the string the catalog holds now, so a writer that turns `%d` into `%@` in all three languages still fails.

The verb check is a heuristic: a small word list per language (`src/teyla/copy_lexicon.py`) plus the infinitive endings.
A fail is a reason to read the row, and an override is `keep: true` on the row.

`--model` adds the second family: GPT-6.1 Sol through `~/ops/bin/codex-lane`, read-only, once, for the rows that passed
the code checks, against the chart, the glossary and the budgets ([PRIVACY](PRIVACY.md) row 30). It can turn a pass into a
fail. It never turns a fail into a pass. If the lane fails, the code verdicts stay and the exit is 3. Safe mode refuses it.

A row the model gave no verdict for (an empty `rows`, a missing key, a verdict other than pass or fail) is **not
assessed**: it is marked `unjudged`, listed as `NOT ASSESSED`, the exit is 3, and `apply` does not pick it. Fix the
lane and judge again, or pass `--allow-unjudged` to keep the code's pass for such rows.

## `teyla copy apply <copy.json> <repo>`

Writes rows into the catalogs the screen file names (or every catalog that holds the keys):

| catalog | how |
|---|---|
| `*.xcstrings` | updates `en`, `es`, `ru` of an existing key; the file stays in Xcode's layout, key order unchanged |
| Android `strings.xml` | edits the entry in `values/`, `values-es/`, `values-ru/`; appends to a file that lacks it |
| `i18n.ts`, `i18n.json`, `locales/{lang}.json` | only when the file is a JSON-like object literal; any code in it is refused |

It never adds, removes or reorders a key, and never touches a language that no row names. A key in no catalog, a string
with plural or device variations, a placeholder that differs from English and a hidden character are each skipped with a
line that says why. A key found in several catalogs is written to every one of them, each checked against its own
current string: a placeholder that differs from the string now in a catalog is skipped for that catalog.

**Which rows:** `--keys k1,k2` wins; else the rows with `keep: true`; else the rows that passed `judge`; else it stops with
"no row is kept". Only the languages the table marks as `written` are
applied; `--lang es` narrows that set, and a language the table did not write is refused (an unwritten language holds
the catalog's own text, so there is nothing to apply). `--dry` lists what would change and writes nothing. A second apply
changes nothing and leaves the file byte-identical.

**`--pr`** works in a new worktree under `~/.worktrees/<repo>/<branch>` cut from the default branch, so the checkout you
use stays as it is. It commits, pushes the branch (never with force), opens the PR with `gh` ([PRIVACY](PRIVACY.md) row 31),
and removes the worktree. It never merges. With nothing changed it opens nothing. Each git and `gh` step runs only after
the one before it succeeded; the first failure stops the run and prints the end of its output (the worktree stays). A bad
`--keys` or `--lang` is refused before any worktree exists.

## `teyla voice chart <repo>`

Scaffolds `brand/voice/en.md`, `es.md`, `ru.md` (or the directory `[voice] chart` names in `brand/kit.toml`; `--out DIR`
chooses another; `--lang` limits). It takes the voice section and the glossary from `DESIGN.md`, and the traits, banned
and preferred words from `brand/kit.toml` when it exists. An existing chart is kept unless `--force`. The file is a valid
chart for `teyla voice check`; blanks are `{{placeholders}}`.

**A chart is complete** when it has 10 accepted and 5 rejected example lines: bullets under a heading that starts with
"Accepted" or "Rejected". A line with `{{` is a blank and does not count. `teyla voice check` adds a warning (not a
failure) while a chart is incomplete, and `--json` carries `chart_status`.

**Lines from the ledger.** A decision in `design/decisions/<id>.json` may carry
`"copy": {"lang": "es", "accepted": "<line>", "rejected": "<line>"}`; the scaffold puts those lines in the matching chart,
oldest first, without duplicates. Without `lang` it is English.

## Assumptions

- `brand/kit.toml` is read best-effort: `product` (or `name`), and `[voice]` with `traits`, `banned`, `preferred`, `chart`. The kit
  lane may fix the schema; a missing key is not an error.
- Russian and Spanish word lists are small by design. A missing verb makes a button fail with a reason a person can
  read, not pass silently.
- The phone review of a screen's strings is the owner's step. This lane produces the table and the PR; it does not render the
  screen.
