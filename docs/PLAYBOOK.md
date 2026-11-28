# The playbook

Status: shipped (decisions P1 to P7 in [the decision](decisions/2026-11-28-playbook.md)). `teyla playbook` keeps
best practices as small Markdown cards, fills each card in stages, and hands a task at most five of them. It is part
of [Studio](STUDIO.md).

```
teyla playbook add --domain flow --job "turn a booking into a plan" --surface "import sheet" --mechanism "..." --refuse "..." \
    --evidence-product Example --evidence-url https://example.com/notes --evidence-what "Release notes describe a review step."
teyla playbook list --status candidate        # what is in play
teyla playbook brief --product myapp --surface "import sheet"     # at most 5 cards, or "none fit"
teyla playbook check                          # every card against the schema
```

Quick start: set `TEYLA_PLAYBOOK_ROOT` (or `playbook_root` in `~/.teyla/config.toml`; default `~/ops/playbook`), then
`teyla playbook add ...`, then `teyla playbook check`. Nothing leaves the Mac: the command reads and writes local
files only and calls no network.

## The card

One file per card: `<root>/cards/<domain>/<id>.md`. YAML front matter, then a body of at most 150 words (why it
works, when not to use it), in English and your own words. The id is `<domain>-<kebab-slug>`, at most 60 characters,
unique. The schema is [`templates/playbook/card.schema.json`](../templates/playbook/card.schema.json).

Domains: `interaction`, `flow`, `ai`, `visual`, `writing`, `listing`, `demand`. Kinds: `pattern`, `hook`. A hook
adds `line` (at most 20 words), `format`, `promise`, `proof` and `cta`.

## The stages

`check` refuses a field that belongs to a later stage, so an agent cannot invent a baseline to pass.

| Stage (`status`) | Fields it adds | Set by |
|---|---|---|
| `seen` | `id`, `domain`, `kind`, `job`, `surface`, `platform`, `mechanism`, `refuse`, `evidence[]`, `added_by`, `created` | the agent that saw it |
| `candidate` | `problem {product, text, pointer}`, `severity` 1 to 3, `confidence` low, medium or high | the orchestrator |
| `trial` | `trial {hypothesis, metric, baseline, threshold, direction, window_days, guardrails, review_by, variants[2], approved}` | the owner's yes |
| `adopted`, `rejected`, `inconclusive`, `parked` | `verdict {result, numbers, date, pr}`; a parked card adds `trigger`; a hook adds `results[]` | the lane that measured |
| `expired` | nothing | `teyla playbook expire` |

`updated` is optional. `set` and `expire` write it, and expiry counts from it (else from `created`).
Evidence media is `null` or an absolute path outside any git repo. `observed: unknown` marks what a public source
cannot show.

## Commands

| Command | What it does |
|---|---|
| `add` | scaffolds a `seen` card from flags; refuses a taken id or a card that fails `check` |
| `list [--domain D] [--status S] [--product P] [--kind K] [--json]` | one line per card |
| `show <id>` | prints the file; a unique prefix of the id works |
| `set <id> [status=S] [--from FILE]` | merges fields from a YAML or JSON map, then checks the card at its new stage. A step that skips a stage is refused: seen to candidate to trial to a verdict |
| `expire [--apply]` | `seen` after 90 days, `candidate` after 30: status becomes `expired`, the file stays. Without `--apply` it only lists |
| `brief --product P --surface S [--domain D] [--job J] [--max 5] [--tokens 1500] [--json]` | only `candidate`, `trial` and `adopted` cards. Exact matches on product, surface and job score first, then plain word overlap. At most 5 cards and 1,500 tokens (characters / 4). When nothing scores, it prints `none fit` |
| `check [PATH]` | validates every card; ids unique; body at most 150 words; folder and file name match the card |

The index is built in memory on every call. No index file is written into the root.

## Use

A design, copy or growth artifact names the card ids its `brief` returned, or `none fit`. Never paste the library
whole. A card becomes a `candidate` only when a product already shows the problem; "looks current" is not a problem.
