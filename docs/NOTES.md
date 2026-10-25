# Notes: ideas kept as you typed them

You have an idea while working on something else. `teyla note` keeps it in one command, files it under
the right product, and passes it on as one of your own words. No model reads or rewrites it.

## Quick start
```sh
teyla note "Weekly digest should list parked products too"   # product: from the text, the directory, else inbox
teyla note "Try a dark icon" --product app-a                 # you choose; an id or an alias
echo "a longer thought" | teyla note -                        # text from stdin
teyla notes [--product P | --inbox] [--all] [--json]          # newest first; --all adds dropped notes
teyla note link <id> <product>                                # file an inbox note, or move one
```

## Which product

Without `--product`, in this order:

1. The text names exactly one registered product (its id, name or an alias, as a whole word). Linked by `text`.
2. The current directory belongs to a registered product (`teyla product`). Linked by `cwd`.
3. Otherwise `inbox`.

A text that names two products is no match, so the directory decides; a directory nobody registered (an
unregistered checkout under your code root included) means `inbox`. A name is never invented.
`--product` takes a registered id or alias in any case, or `inbox`; anything else is refused with the closest names. The product registry is [PRODUCTS.md](PRODUCTS.md).

## What is stored

`~/.teyla/notes/notes.jsonl` (0600, in a 0700 directory) holds one JSON event per line and is only ever
appended to, under a flock, so two shells can add at once. `add`, `link`, `drop` and `undrop` are events; the
reader folds them into notes:

| field | meaning |
|---|---|
| `id` | `n` and six base32 characters; a unique prefix is enough on the command line |
| `text` | what you typed, trimmed only of outer whitespace; line breaks and accents stay |
| `product` | a registry id or `inbox` |
| `source` | `owner` for everything typed at the CLI; the field keeps agent notes apart later |
| `created`, `updated` | UTC times |
| `linked_by` | `owner` (`--product`, `link`), `text`, `cwd`, or "" for the inbox |
| `dropped` | true after `drop`, false after `undrop` |

A line that does not parse is skipped. Nothing is deleted: `drop` sets a note aside, `undrop` brings it back.

## Your words

A note linked to a registered product is appended, as typed, to that product's [intent](INTENT.md) file with
harness `note` and the note id as session. Short notes count. `teyla note link <id> <product>` adds it under the
new product; the old entry stays, because the intent store only appends. Inbox notes reach it once they are
linked. The intent store scrubs secret-shaped text on the way in; the notes file keeps what you typed.

## In the snapshot

`teyla state --json` carries `notes: {"inbox": n, "by_product": {id: n}}`, open notes only ([APP.md](APP.md)).

## In the Mac app

The Mac app is a second way to write and file notes; it keeps no copy. See [APP.md](APP.md#notes-quick-note-and-the-notes-section).

- A global shortcut (⌥Space by default; recorded or cleared in Settings, never push-to-talk's ⌥⌘Space)
  opens a quick-note panel. The text goes to `teyla note - --product <id> --json` on stdin.
- While you type, the panel calls `teyla note --suggest - --json` and pre-selects the product. It prints
  `{"product", "linked_by", "candidates"}` and writes nothing; `candidates` are the registered ids, focus
  products first and parked ones last, for the picker. The choice is the one `add` would make.
- The window's Notes section lists the Inbox count and the newest five open notes, with Link… and Drop.
- `--json` on `teyla note` (also `link`, `drop`, `undrop`) prints the note instead of a line.
  `--cwd DIR` sets the directory that decides when the text names no product.
