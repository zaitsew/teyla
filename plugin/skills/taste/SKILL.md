---
name: taste
description: Save a design or text the owner likes or dislikes into the taste corpus with `teyla taste add`. Use when the owner shares a link or screenshot with a reaction in any language, for example a line that starts with the word taste, a colon, a link and a comment, or "I like this" or "I dislike this" with a link. Needs the `teyla` CLI.
argument-hint: "<url or image file> — <comment>"
---

# Taste

The owner drops designs and texts he reacts to. Each one becomes evidence in the taste corpus. Never write the
files by hand.

## 1. Check the CLI

```sh
{ command -v teyla || ls "$HOME/.local/bin/teyla"; } >/dev/null 2>&1 && echo "teyla: found" || echo "teyla: MISSING"
```

If it prints `teyla: MISSING`, say only this one line and stop; do not run anything else:

> This needs the Teyla CLI. Install it, then ask again: `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla` (or `pipx install git+https://github.com/zaitsew/teyla`). Python 3.11 or newer.

If the CLI is found only at `~/.local/bin/teyla` (not on PATH), use that full path wherever a command below says `teyla`.

## 2. Add it

- The first word is the link or the image file. Everything after it (minus a leading dash) is the owner's sentence, verbatim.
- Verdict: a dislike (in any language: "dislike", "hate", "too much", "ugly") adds `--dislike`; a mix ("some of it", "half") adds `--mixed`; else a like needs no flag.
- A product named in the message adds `--product <name>`; "for all my products" adds nothing.
- Pass the sentence in quotes, flags before it.

```sh
teyla taste add --dislike --product recipes "<link>" "too many boxes"
teyla taste add "<link>" "great neutral design"
```

Safe mode refuses the page capture (the command says so): the entry is still saved. Tell the owner and offer the same command with `--allow-network`.

## 3. Show the result

Print the inbox line the command ends with. A `raw` entry (no sentence): ask for one sentence and run `teyla taste note <id> "..."`.
Do not accept an entry for the owner; `teyla taste accept <id>` is his yes.
