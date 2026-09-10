# The control plane

`teyla routines` reports on work scheduled elsewhere. The control plane **runs**
it — under stated capabilities, through a gate, leaving a receipt.

One constraint, from [MANUAL.md §2](MANUAL.md): *the model is subject to the
loop, not the author of it.* So the loop is code (`src/teyla/control/`) and the
model runs in exactly one box inside it. It cannot skip the gate, because nothing
it emits is consulted about whether the gate happens.

Wire it up with one line in `cli.py`: `control.register(sp)`.

## The loop

```
  clock trigger (launchd)   or   teyla run <product>:<routine>
   │
   ▼ [1] kill switch? ── on ──▶ REFUSE. Nothing is created.
   ▼ [2] idempotency key ── receipt exists ──▶ SKIP (0). --force overrides.
   ▼ [3] run dir: run.json, grants.json, actions.jsonl
   │         TEYLA_GRANTS points the hook at it
   ▼ [4] rules: .claude/rules/*.md whose globs match the context paths,
   │         plus AGENTS.md "## Rules"
   ▼ [5] DRAFT ─── the only box a model runs in ──▶ draft.md
   │         every tool call → PreToolUse hook → allow/deny
   ▼ [6] GATE  A ─▶ inbox item "needs you". Stop.
   │          B ─▶ act, write undo.md, inbox "acted — review".
   │          C ─▶ critic (PASS/FAIL on line 1) → act only on PASS.
   ▼ [7] receipt.json + ~/.teyla/receipts.jsonl
```

## Manifest

Extends `[[routine]]` in a product's `teyla.toml`. A routine is control-plane
**iff it declares a `step`**; legacy `kind`/`label`/`every` routines are
unchanged, and both may sit in one file.

```toml
[[routine]]
name         = "morning-digest"
gate         = "A"                     # A | B | C   (default A)
idempotency  = "date"                  # date | none | input-hash
trigger      = { type = "clock", at = "07:00", tz = "Europe/Madrid", days = "mon-fri" }
step         = { kind = "command", run = "./bin/digest" }
#            or { kind = "agent", harness = "claude", skill = "digest-draft",
#                 prompt = "…", context = ["notes/**"] }
act          = { kind = "command", run = "./bin/send" }   # required at B and C
critic       = { harness = "claude", prompt = "…" }       # required at C
capabilities = ["fs.write:runs/**", "shell:git push", "net:*",
                "send:telegram", "tool:mcp__loco__*"]
caps         = { max_minutes = 20, max_output_tokens = 200000,
                 max_writes = 50, max_sends = 1, max_turns = 30 }
```

Artifacts land in `<repo>/runs/<date>/<routine>/<run-id>/`, gitignored by
convention.

**Idempotency.** `date` = once per calendar day (default); `none` = never
collides; `input-hash` = the manifest plus the bytes of every context path. A
receipt of `ok` or `needs-you` counts as done; `blocked`/`failed` do not, so a
critic rejection retries on the next trigger.

**Harnesses.** `claude -p --output-format json` (usage and cost reach the
receipt), `codex exec`, `grok -p`. The one named must be on PATH.

## Gates

| | behaviour | earned by |
|---|---|---|
| **A** | drafts, stops, files an inbox item. Nothing leaves. | the starting point |
| **B** | acts, writes `undo.md`, files "acted — review". | 10 clean receipts, each approved with no `--note` |
| **C** | a critic checks the draft against the same rules; acts only on `PASS`. | that, plus a `critic` |

`teyla promote` prints that evidence when it refuses; `--force` overrides and is
recorded in `~/.teyla/promotions.jsonl`. An approval carrying a `--note` breaks
the streak: a run you had to correct was not safe unattended.

## Enforced by code / left to the model

**Code.** The kill switch (`~/.teyla/KILL`: `teyla run` refuses, the hook exits 2
on every call). Idempotency. Which gate runs, and whether `act` runs.
`max_minutes`, as a wall clock per step. The five schemes, per tool call, in the
hook: `fs.write:` globs on Write/Edit, `shell:` verbs on *every segment* of a
Bash command, `net:` hosts on WebFetch, `tool:` globs on MCP and other
non-built-in tools, `send:` as a budget spent by anything that looks like a send.
`max_writes`/`max_sends`, counted in a state file. Every decision, allow and
deny, appended to `actions.jsonl` and summarised in the receipt.

**The model.** Following the injected rules. Content quality. The critic's
PASS/FAIL. Writing a usable `undo.md`.

Two holes, stated rather than papered over: `shell:` can write files `fs.write:`
would refuse (redirection), and `net:` can exfiltrate anything the run can read.
`max_output_tokens` is checked after the fact and flagged; it does not stop
generation.

## Commands

```
teyla run <product>:<routine> [--dry] [--force] [--repo PATH]
teyla inbox [list | show <id> | approve <id> | reject <id> [--note "…"]]
teyla kill [on|off|status] [--reason "…"]
teyla triggers [list | install <ref> [--no-load] | uninstall <ref>]
teyla promote <ref> --gate B|C [--force] [--note "…"]
teyla receipts <ref> [-n 10]
```

`approve` runs the act step under **the grants the draft ran under** — copied
from the original `grants.json`, not re-derived from a manifest that may have
widened since. `reject --note` writes the note to the repo's
`.teyla/corrections.jsonl`, where the harvest finds it. `~/.teyla/inbox.jsonl` is
append-only: an approval is a new record, not an edit.

## Not built

- **`event` and `webhook` triggers.** They parse, so the intent is declarable;
  nothing installs or fires them. Only `clock` becomes a launchd agent.
- **Per-capability grants outside Claude Code.** Codex gets one `--sandbox`
  flag, Grok a `--deny` list from the ungranted schemes. A `send:`-free manifest
  is not proof a Codex step could not send.
- **Durable multi-step state.** A run is one process; a crash loses it and the
  next trigger starts fresh. Escalate to a workflow engine only on a limit you
  have hit.
- **Timezones in launchd.** `tz` reaches the receipt, but launchd fires on local
  time. `triggers install` warns when the two differ.
- **Sandboxing of `command` steps.** They get the timeout and the environment;
  the shell is not confined. The hook governs harness tool calls, not `/bin/sh`.
