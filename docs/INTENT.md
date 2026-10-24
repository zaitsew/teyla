# Intent: your own words, kept as you wrote them

You describe a goal in a long prompt. An agent turns it into a plan. A later session works from the
plan, and the detail is gone: a summary has replaced the source. `teyla intent` keeps the source.
It uses no model and writes no summary.

## Quick start
```sh
teyla intent backfill --days 30 --dry   # count what is in your transcripts, write nothing
teyla intent backfill --days 30         # keep it
teyla intent [product] [--grep TEXT]    # no product: one line each; else one line per entry
cat "$(teyla intent path <product>)"    # the words themselves
teyla intent cover docs/ROADMAP.md      # which of your sentences does this plan leave out?
teyla intent clean --dry                # entries you did not type, under today's rules; writes nothing
```

The `UserPromptSubmit` hook `plugin/hooks/capture-intent.sh` keeps new prompts. `teyla harness sync`
wires the same script into Codex, Grok, Cursor and Hermes. Codex asks you to trust it once (`/hooks`).

## What is kept

- A prompt of 400 characters or more (`[intent] min_chars`). `[intent] enabled = false` turns it off.
- It goes to `~/.teyla/intent/<product>.md`, outside every repo, mode 0600, append-only.
- The product is the repo name of the prompt's cwd. A worktree maps to its repo. A cwd outside a repo
  goes to `general`.
- Briefs one agent session writes for another (they open with "Background (from the session that
  started this one)") and harness events are not the owner's words and are skipped.
- Secrets become `[redacted]` (the scrubber `teyla correct` uses) before anything is written.
- The same words on the same lines are kept once per product: spaces within a line, line endings and
  the blank lines around the text do not count, but a different line structure is a different prompt.
  `.index.json` holds the hashes and is rebuilt if lost, or if it comes from an older version.

```
## 2026-10-16 18:40 · claude · session 1a2b3c4d
<the prompt, verbatim, secrets scrubbed>
```

## What is not kept

- Prompts a script or another agent wrote: `claude -p`, `codex exec`, `grok -p`, review and subagent
  briefs, injected AGENTS.md text, scheduled-task prompts.
- Turns the harness injects (system reminders, task notifications, slash commands) and images. That
  includes a subagent's final report, which the Claude desktop app files as a user turn: it is wrapped
  in `<agent-message from="...">` and opens with `[Subagent hand-back]`.
- A Grok prompt from a headless run. Grok's hook gets a `grok -p` brief unwrapped, like a typed
  prompt, and documents no flag for it. The hook looks the session up in Grok's own store:
  `$GROK_HOME/sessions/<cwd>/<id>/summary.json` says `"session_kind": "headless"` (and
  `prompt_context.json` says `"is_non_interactive": true`) for `grok -p`, `--prompt-file` and
  `--prompt-json`. If the store has no answer yet, the prompt is kept, and `clean` removes it later.
- Text you paste into a prompt arrives inline and cannot be told from typing, so it is kept. A prompt
  over 50,000 characters keeps its first 50,000 and says how many were left out. The hash covers the
  kept part, so a cut prompt is still recognised after the index is rebuilt.

## Repairing the store: `teyla intent clean`

Entries stored before a rule existed stay in the files. `teyla intent clean` checks every entry in every
product file against today's rules (the text rules above, and for `grok` entries the session store's
headless flag) and removes the ones you did not type.

```sh
teyla intent clean --dry   # one line per entry it would remove (product, date, harness, session, first 60 characters)
teyla intent clean         # remove them
```

It copies each file it changes to `<product>.md.bak-<UTC time>` (mode 0600) first, then replaces the
file and `.index.json` atomically under the store lock. Entries it keeps are not rewritten: they stay
byte for byte as they were. To undo a clean, copy the backup over the product file and delete `.index.json`
(it is rebuilt from the files).

## Check a plan against your words

```sh
teyla intent cover <plan.md> [--product P] [--since YYYY-MM-DD] [--last N] [--model] [--json]
```

The source is your entries for the product (default: the repo the plan sits in). `--since` and `--last`
narrow them. Each entry is cut into sentences and list items, in Russian and English. A sentence under
six words is dropped, and so is chatter ("proceed", "ok, do it") and a question about the agent's own
state ("are you done?"). Requirements, goals, constraints, complaints and examples stay. Pasted code
blocks and quoted lines are skipped. A sentence that repeats in a later entry counts once.

A sentence is served when the plan

- **quotes it**: all of it, or a run of at least 60% of its words, ignoring case, punctuation and spacing;
- **covers its words**: one plan sentence, or two next to each other, holds at least 55% of its content
  words and at least three of them (a suffix strip stands in for stemming, in English and Russian);
- **sets it aside**: the match sits under a heading such as "Out of scope", "Non-goals" or "Deferred", or in
  a line that opens with one of those phrases and a colon.

The output starts with `served 23 of 31`, then the unserved sentences, grouped by the entry they came
from, with its date and session. A Russian sentence cannot match an English plan by words. Those are
listed apart as "needs --model", not as unserved.

`--model` sends the unresolved sentences and the plan to one Claude Haiku 5.5 call per 80 sentences (about
$0.002) and takes its verdict: served only when the plan has a step, decision or target for that point, or
lists it as out of scope. It is off by default. In safe mode it does not run, because the prompts would
leave the machine. A failed call leaves the word-based verdicts as they were.

Exit 0: every sentence is served or still waits for `--model`. Exit 1: something is unserved. Exit 2: no
plan, no entries, or no intent for the product. A hook or a reviewer can gate on it. The check finds a
sentence the plan does not mention. It cannot tell whether a mention does the sentence justice: read what
it reports as served by words once.

## In a session

`session-start.sh` prints one line when the file exists for the session's repo: the path, the entry
count, the latest date, and "Read them before planning; quote the sentences a plan serves." The shipped
policy adds the rule: before a plan or a spec, read the file, quote the source sentences each part of
the plan serves, and never replace them with a summary.

One `flock` covers read index, append, write index. A hook that cannot get the lock in a second skips
the prompt, and the next `backfill` finds it. The hook prints nothing and always exits 0.
`teyla uninstall` removes the directory with `~/.teyla`; `--keep-data` keeps it. Backfill reads Claude
Code and Codex transcripts only: the other harnesses do not keep whole prompts.
