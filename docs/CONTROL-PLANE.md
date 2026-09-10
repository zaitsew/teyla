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
   ▼ [3] ~/.teyla/runs/<run-id>/: run.json, grants.json, grants-state.json,
   │         actions.jsonl.  TEYLA_GRANTS points the hook at it.
   │         ~/.teyla/active-runs/<run-id> marks the run in flight.
   ▼ [4] `command` steps checked against the grants — they never meet the hook
   ▼ [5] rules: .claude/rules/*.md whose globs match the context paths,
   │         plus AGENTS.md "## Rules"
   ▼ [6] DRAFT ─── the only box a model runs in ──▶ draft.md
   │         every tool call → PreToolUse hook → allow/deny → signed log line
   ▼ [7] GATE  A ─▶ inbox item "needs you". Stop.
   │          B ─▶ kill switch again, then act, undo.md, inbox "acted — review".
   │          C ─▶ critic (first line exactly PASS) → kill switch → act.
   ▼ [8] receipt.json (in ~/.teyla, copy in the repo) + ~/.teyla/receipts.jsonl
```

## Where a run's files live

Two directories, and the split is the point.

```
~/.teyla/runs/<run-id>/           the run cannot write here, under any grant
    grants.json                   what it was allowed to do
    grants-state.json             the counters, locked during read-modify-write
    actions.jsonl                 every decision, each line HMAC-signed
    run.json                      the manifest snapshot and the rules that applied
    receipt.json                  the canonical receipt

<repo>/runs/<date>/<routine>/<run-id>/     gitignored by convention
    draft.md  undo.md  act.md  critic.md  *.prompt.md
    receipt.json                  a COPY, written by the engine after the run
```

These used to sit in one directory — the product's `runs/`, which is exactly what
`fs.write:runs/**` grants. A routine could therefore rewrite its own `grants.json`
to widen itself, or its own `actions.jsonl` so the receipt would describe a run
that did not happen. The policy a run is judged by cannot live inside the blast
radius of that run.

Two locks on it, not one. The hook refuses any write under `~/.teyla`, and any
write whose **basename** is a control filename wherever it appears — so
`runs/2026-09-10/x/grants.json` is refused even though it is inside a granted
glob. And every line the hook appends to `actions.jsonl` carries an HMAC keyed by
`~/.teyla/hmac.key` (0600, created on first use); at receipt time, lines that do
not verify are dropped and counted, and the receipt says `actions log tampered: N
lines` rather than quietly reporting a clean run.

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
capabilities = ["fs.write:runs/**", "shell:./bin/digest", "shell:./bin/send",
                "shell:git push", "net:*", "send:telegram",
                "tool:mcp__loco__*", "tool:Agent", "tool:Skill:harvest"]
caps         = { max_minutes = 20, max_output_tokens = 200000,
                 max_writes = 50, max_sends = 1, max_turns = 30 }
```

Readable artifacts land in `<repo>/runs/<date>/<routine>/<run-id>/`, gitignored
by convention; the run's control files land in `~/.teyla/runs/<run-id>/`. See
"Where a run's files live".

**Capabilities cover `command` steps too.** A `command` step never reaches the
PreToolUse hook, so its command string is checked against these same grants before
it runs — which is why the example grants `shell:./bin/digest` and
`shell:./bin/send` for its own two steps, and why the `fs.write:` glob has to
cover anything either of them redirects into. This is stricter than it was: a
routine that used to run any shell command now has to name the verb.

**Idempotency.** `date` = once per calendar day **in the trigger's timezone**
(default); `none` = never collides; `input-hash` = the manifest plus the bytes of
every file the context globs expand to. A receipt of `ok` or `needs-you` counts as
done; `blocked`/`failed` do not, so a critic rejection retries on the next trigger.

**Harnesses.** `claude -p --output-format json` (usage and cost reach the
receipt), `codex exec`, `grok -p`. The one named must be on PATH.

## Gates

| | behaviour | earned by |
|---|---|---|
| **A** | drafts, stops, files an inbox item. Nothing leaves. | the starting point |
| **B** | acts, writes `undo.md`, files "acted — review". | 10 **consecutive** clean receipts, each approved with no `--note`, all against the current `act` |
| **C** | a critic checks the draft against the same rules; acts only when its first line is exactly `PASS`. | that, plus a `critic` |

`teyla promote` prints that evidence when it refuses, including which receipt
ended the streak; `--force` overrides and is recorded in
`~/.teyla/promotions.jsonl`. An approval carrying a `--note` breaks the streak: a
run you had to correct was not safe unattended. So does editing the `act` step —
each receipt records a hash of it, and evidence about the step you replaced is not
evidence about this one.

## Enforced by code / left to the model

**Code.**

* **The kill switch** (`~/.teyla/KILL`): `teyla run` refuses, the hook exits 2 on
  every call, and it is read **again immediately before the act step** and before
  `inbox approve`'s act. A draft can take twenty minutes, which is exactly the
  window someone reaches for the switch in.
* **Idempotency.** The `date` key is computed in the **trigger's own timezone**,
  not UTC. The `input-hash` key expands the context globs and hashes each file's
  relative path plus its length-prefixed content, keyed by the routine ref.
* Which gate runs, and whether `act` runs. `max_minutes`, as a wall clock per step.
* **The five schemes, per tool call, in the hook.** `fs.write:` globs on
  Write/Edit, matched against the path **resolved through symlinks**, with `*`
  confined to one path segment and only `**` crossing `/`. `net:` hosts on
  WebFetch. `tool:` globs on MCP and other non-built-in tools — including
  `Task`/`Agent` and `Skill`, which are **not** free: a sub-agent needs
  `tool:Agent`, a skill needs `tool:Skill:<name>` or `tool:Skill:*`. `send:` as a
  budget spent by anything that looks like a send.
* **`shell:` verbs on every segment of a Bash command**, where a segment is cut at
  `;`, `|`, `&&`, `||` and a single `&`. Within a segment: an environment prefix
  (`FOO=1 cmd`) needs `shell:env`, and `PATH=`, `GIT_CONFIG*`, `LD_*`, `DYLD_*`
  are refused even then; process substitution (`>(…)`, `<(…)`) is refused under
  every grant, `shell:*` included; and **every redirection target is checked
  against `fs.write:`**, which was previously a hole.
* **`command` steps get that same check**, before they run. They never meet the
  hook, so the manifest's own `capabilities` are enforced against the command
  string by `teyla run` and by `inbox approve`. A step that redirects into
  `$TEYLA_UNDO` still works: that path is expanded and checked like any other.
* `max_writes`/`max_sends`, counted in a state file **locked with `flock` across
  the whole read-decide-write**, so parallel tool calls cannot both slip under a cap.
* Every decision, allow and deny, appended to `actions.jsonl` **HMAC-signed**, and
  summarised in the receipt — including how many lines failed verification.
* **`inbox approve`** recomputes grants from the current `teyla.toml`, and refuses
  if the routine is gone or its capabilities have widened since the draft, printing
  the difference. Narrowing is fine; you get the smaller list.
* **`promote`** requires ten *consecutive* clean receipts, counted back from the
  newest and stopping at the first that is not clean, each carrying a hash of the
  act step as it is written now. Editing `act` resets the streak.
* **The critic's verdict** is read strictly: the first line must be exactly `PASS`.
  `PASS, though I could not check X` is a FAIL, and so is `**PASS**`.

**The model.** Following the injected rules. Content quality. The judgement behind
the critic's PASS. Writing a usable `undo.md`.

### Residual risk, stated rather than papered over

* **`net:` exfiltration.** A `net:` grant can send anything the run can read to the
  host it names, and nothing here inspects a payload. `send:` counts messages, not
  bytes over the wire. Grant `net:` to the narrowest host that works, and read a
  routine holding both `net:` and a broad read surface as capable of leaking it.
* **A broad `shell:` grant.** Redirection is checked now, but a granted verb that
  is itself an interpreter — `python`, `sh`, `perl` — or a copier such as `cp` or
  `tee` can still write where a redirection would have been refused. `shell:*` is
  arbitrary execution and should be read that way. The redirection check closes the
  accident, not the intent.
* **The nested session.** An agent under grants can spawn its own `claude -p`. That
  child inherits the environment, so it inherits `TEYLA_GRANTS` and stays governed
  — the common case is covered. A child arriving *without* it is caught by
  `~/.teyla/active-runs/`: while any run is in flight, a session with no grants is
  refused. The cost is that an unrelated session started by hand during a run is
  refused too, and the marker is only as reliable as the pid in it (a crashed run's
  marker is pruned when its process is gone). A harness that does not run the
  PreToolUse hook at all is outside this entirely.
* **`max_output_tokens`** is checked after the fact and flagged; it does not stop
  generation.
* **The `Bash` control-file check is a substring test.** A command that names
  `grants.json` or `~/.teyla` is refused, but a shell can reach a file in more ways
  than a checker can enumerate. It is a coarse net over an already-narrow grant, not
  a proof.

## Commands

```
teyla run <product>:<routine> [--dry] [--force] [--repo PATH]
teyla inbox [list | show <id> | approve <id> | reject <id> [--note "…"]]
teyla kill [on|off|status] [--reason "…"]
teyla triggers [list | install <ref> [--no-load] | uninstall <ref>]
teyla promote <ref> --gate B|C [--force] [--note "…"]
teyla receipts <ref> [-n 10]
```

`approve` runs the act step under grants **recomputed from the current
`teyla.toml`**, and refuses if the routine is gone or its capabilities have
widened since the draft — printing the difference so you can see what you would
have been agreeing to. It used to copy the original run's `grants.json`, which
sat in a directory the run could write. `reject --note` writes the note to the
repo's `.teyla/corrections.jsonl`, where the harvest finds it.
`~/.teyla/inbox.jsonl` is append-only: an approval is a new record, not an edit.

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
- **Sandboxing of `command` steps.** Their command *string* is now checked against
  the routine's `shell:` and `fs.write:` grants before they run, so an ungranted
  verb or a redirection out of bounds is refused. The process itself is still not
  confined: nothing stops a granted verb from doing more than its name suggests,
  and there is no seccomp, no sandbox profile, no filesystem jail. The hook governs
  harness tool calls, not `/bin/sh`.
