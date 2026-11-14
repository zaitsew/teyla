---
name: intent-audit
description: Audit the owner's own words for one product against what shipped, and record a status per request with `teyla intent mark` or `teyla intent load`. Use when asked to "audit my prompts", "what did I ask for that was not done", "what was missed", or when a session-start line says entries are not audited. Needs the `teyla` CLI.
argument-hint: "<product>"
---

# Intent audit

The owner's long prompts are kept word for word by the Teyla CLI. This skill finds which of his requests were
delivered and records it. The CLI is the record; you do the reading and the judging. Never write the status
files by hand, and never paraphrase a request: every request is a verbatim quote of his text.

## 1. Check the CLI

```sh
{ command -v teyla || ls "$HOME/.local/bin/teyla"; } >/dev/null 2>&1 && echo "teyla: found" || echo "teyla: MISSING"
```

If it prints `teyla: MISSING`, say only this one line and stop; do not run anything else:

> This needs the Teyla CLI. Install it, then ask again: `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla` (or `pipx install git+https://github.com/zaitsew/teyla`). Python 3.11 or newer.

If the CLI is found only at `~/.local/bin/teyla` (not on PATH), use that full path wherever a command below says `teyla`.

## 2. See what is owed

```sh
teyla intent audit <product> --open      # open and partial requests, then entries not audited or partly audited
teyla intent <product> --json            # every entry with its id, date and full text
```

The orchestrating session plans and checks; the reading is volume work. Hand batches of 10 to 20 entries
to a cheaper model (a subagent or a child session), each with the entry ids, the texts and the evidence
sources below, and ask for the JSON in step 4 back.

## 3. Judge each entry

For each entry not audited:

1. Split it into requests: one thing the owner asked to be built, changed, fixed or decided. A complaint
   that implies a fix is a request. Chatter ("ok, go on"), questions about the agent's state and pasted logs
   are not.
2. Quote each request: a run of his exact words, at most 600 characters. Case and punctuation must match;
   line breaks and runs of spaces count as one space. The CLI refuses a quote that is not in the entry.
3. Find the evidence, newest first: merged PRs (`gh pr list --state merged --search "<words>" --limit 20`
   in the product's repo), the README's feature list, the code, the release notes.
4. Give a status:
   - `done`: the request shipped as asked. `--evidence` is the PR URL, a file, or a README anchor.
   - `partial`: some of it shipped. `--evidence` plus `--note` saying what is still missing.
   - `open`: nothing shipped. No evidence needed.
   - `superseded`: a later request or decision replaced it. `--evidence` or `--note` names it; use the
     other request's id when there is one.
   - `not-a-request`: the whole entry asks for nothing (mark the bare entry id).
5. Close the entry: `split` on the bare entry id says every request in it is recorded. Without it the
   entry counts as "partly audited". A one-request entry can take its status on the bare id instead.

A PR whose title matches is not proof. Open it and check that it does what the quote asks; when it does
part, say `partial`.

## 4. Record it

One request at a time:

```sh
teyla intent mark 4f2a9c1e open --quote "<his exact words>"
teyla intent mark 4f2a9c1e.2 done --evidence <PR URL>
teyla intent mark 4f2a9c1e split
```

Many at once (all or nothing; `--dry` checks first). A replay updates the same requests, it never
duplicates them:

```json
{"product": "<product>", "records": [
  {"entry": "4f2a9c1e", "quote": "<his exact words>", "status": "partial",
   "evidence": "<PR URL>", "note": "the month view is still missing"},
  {"entry": "4f2a9c1e", "status": "split"},
  {"entry": "9b0d77aa", "status": "not-a-request"}
]}
```

```sh
teyla intent load <product> audit.json --dry && teyla intent load <product> audit.json
```

## 5. Report

Print the summary line `teyla intent audit <product>` starts with, then the open and partial requests,
oldest first, with their quotes. Say which entries you could not judge and why.
