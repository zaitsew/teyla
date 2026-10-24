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

The first rule that matches wins.

1. `[assign]`: the session id, or the ask id, is listed.
2. The longest `repos` or `paths` entry that contains the session's directory. A worktree maps to
   its repo: `<repo>/.claude/worktrees/<x>` by path, `~/.worktrees/<repo>/<branch>` by the repo's
   directory name.
3. A git checkout directly under `code_root` that nobody registered: its directory name. This is a
   fact about the disk, not a guess.
4. Otherwise `unassigned`.

The old placeholders `(no repo)`, `(home)`, `(scratch)` and `unknown` no longer appear.

## Commands

| Command | What it does |
|---|---|
| `teyla product [list] [--json]` | One line per product: id, stage, focus star, primary platform, repos. |
| `teyla product init [--write]` | Proposes products from the git repos under `code_root`. No commit for 30 days proposes `parked`, else `building`. `--write` adds only products not yet present and never changes an existing one. |
| `teyla product add <id> [--repo PATH] [--name N] [--stage S]` | Registers one product. |
| `teyla product set <id> key=value...` | `name`, `stage`, `primary`, `focus`, `aliases` (comma list), `add-repo`, `add-path`. |
| `teyla product park <id>` / `wake <id>` | `park` sets the stage to `parked` and remembers the old one in `stage_before_park`; `wake` restores it. |
| `teyla product assign <ask-id-prefix\|session-id> <id> [--ask-only]` | Files the session behind an ask under a product and lists the asks that moved. `--ask-only` moves that one ask. |

`teyla products` (plural) is the usage table and is unchanged.

## In the state snapshot

`teyla state --json` takes the product names from this file. `products[]` keeps its fields and adds
`id` (the registry id, same as `name`), `display_name`, `stage`, `focus`, `primary` and `registered`
(false for a product that only exists because sessions ran in a repo). Every registered product is
listed, parked ones with stage `parked`; `unassigned` is listed last, and only when something waits
under it.

## For other commands

`registry.match_text(text)` returns the products whose id, name or alias appears in a text as a whole
word, ignoring case.
