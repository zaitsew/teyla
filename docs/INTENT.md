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
- The same text is kept once per product. `.index.json` holds the hashes and is rebuilt if lost.

```
## 2026-10-16 18:40 · claude · session 1a2b3c4d
<the prompt, verbatim, secrets scrubbed>
```

## What is not kept

- Prompts a script or another agent wrote: `claude -p`, `codex exec`, review and subagent briefs,
  injected AGENTS.md text, scheduled-task prompts.
- Turns the harness injects (system reminders, task notifications, slash commands) and images.
- Text you paste into a prompt arrives inline and cannot be told from typing, so it is kept. A prompt
  over 50,000 characters keeps its first 50,000 and says how many were left out.

## In a session

`session-start.sh` prints one line when the file exists for the session's repo: the path, the entry
count, the latest date, and "Read them before planning; quote the sentences a plan serves." The shipped
policy adds the rule: before a plan or a spec, read the file, quote the source sentences each part of
the plan serves, and never replace them with a summary.

One `flock` covers read index, append, write index. A hook that cannot get the lock in a second skips
the prompt, and the next `backfill` finds it. The hook prints nothing and always exits 0.
`teyla uninstall` removes the directory with `~/.teyla`; `--keep-data` keeps it. Backfill reads Claude
Code and Codex transcripts only: the other harnesses do not keep whole prompts.
