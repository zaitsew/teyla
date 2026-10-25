# teyla start

`teyla start` reads the agent sessions already on your disk, tells you what the last 30 days cost and where
the money leaked, and offers seven changes. Each change is one keystroke, saves a backup first, and can be
undone. It never changes anything without a yes.

```bash
teyla start                 # the summary card, then each offer: [y]es / [n]o / [e]xplain / [q]uit
teyla start --days 14       # another window; savings are scaled to a month
teyla apply O1 O3 --yes     # make those changes without the questions (--dry shows them and writes nothing)
teyla changes               # every change Teyla made, and whether it is undone
teyla undo O1               # put back only the key Teyla wrote
```

## The flow

1. **Diagnose.** Teyla loads every session of the window (Claude Code, Codex, Grok, Hermes, Cursor) and the
   subagent files of Claude Code. Nothing leaves the machine and nothing is written. A machine with no sessions
   prints one line saying to use an agent for a day and run `teyla start` again.
2. **Summarise.** A card of at most 12 lines, numbers first: the total at API list price, the share spent
   re-reading and storing context, the sessions that ran past 250k tokens, what subagents cost and how much of
   that was Opus, and the questions waiting on you. A subscription bills differently, and the card says so.
   An interactive `teyla start` prints one progress line to stderr first ("Reading 612 sessions from the last
   30 days..."); `--agent` and `--json` keep stdout and stderr clean. The card ends with one line per applicable
   offer, `O6 <title>: <saving or benefit>`, or says "No changes to suggest: your settings already match."
3. **Offer.** Seven offers, in order. An offer whose setting is already in place, or whose tool is not
   installed, is left out and the reason is kept for `--json`. Each shows the change, the saving (or what it
   brings when no honest dollar figure exists), the trade-off and the undo.
4. **Apply.** `y` makes the change. `e` prints the detail. `q` stops. Without a terminal nothing is asked:
   `teyla start` prints the card and the `teyla apply` commands instead.

For an AI agent that relays the result to you, `teyla start --agent` (or `--json`) prints
`{summary_text, diagnosis, offers}` and applies nothing. The agent reads `summary_text` to you, then runs
`teyla apply <ids> --yes` for the offers you accept.

`--agent` writes none of your settings. The one side effect is the existing cache of Claude desktop sessions
under `~/.teyla`, which `teyla asks` already keeps; it is refreshed only when a Claude desktop store exists.

## The window

The window is the last N local calendar days, today included (30 by default). Only turns whose own timestamp
falls inside it are counted, so a long session resumed today adds today's turns and not its history. Codex,
Hermes and Grok record no per-message time, so a session of those books all its cost on the day it was last
active.

## The offers

| id | change | writes | saving |
|---|---|---|---|
| O1 | `autoCompactWindow` 335000 | `~/.claude/settings.json`, one key | dollars |
| O2 | `env.CLAUDE_CODE_SUBAGENT_MODEL` = `sonnet` | `~/.claude/settings.json`, one key | dollars |
| O3 | a read-only `scout` agent on Haiku | `~/.claude/agents/scout.md`, only if absent | dollars |
| O4 | Codex `model_reasoning_effort` = `medium` | `~/.codex/config.toml`, one line | benefit text |
| O5 | `teyla policy sync` | the rules links of each installed harness | benefit text |
| O6 | `teyla harness sync` | hooks and skills in each installed harness | benefit text |
| O7 | `teyla routine install` | two launchd jobs | benefit text |

O1 to O4 are applicable only when the tool is installed and the setting is not already set. O4 is offered only
when Codex is at least $5 and 10% of the window's spend, and its effort is `high` or `xhigh`. O5 to O7 show no
dollar figure because their value is not a price.

## How a saving is counted

All dollars are API list price. A saving is a range: the high end is the full figure, the low end is a
haircut for what the data cannot tell. Windows other than 30 days are scaled linearly to a month, and a
saving under $1 a month is not shown as a figure.

- **O1.** A turn whose context passed the compaction point (335k window minus 35k, so about 300k) would have run
  after `floor((context - 50k) / 250k)` compactions. Each compaction drops 250k tokens from what the turn
  re-reads, priced at the model's cache-read rate. A run of such turns pays for its compactions: 300k tokens read,
  10k written as the summary and 50k cached at the one-hour write price. A run cheaper than its own compactions
  saves nothing. Sessions between 250k and 300k are not counted. Low end: 50%, because a session regrows after
  it compacts.
- **O2.** Subagent calls on Opus that named no model (the call has no `model` in its meta file) and whose agent
  type does not pin one in `~/.claude/agents/<type>.md`. The saving is their actual cost minus the same tokens
  at Sonnet 5.5. Calls that named a model, and Fable, are left out. The setting is a default: a call's own
  `model` and an agent's `model:` line win. Before Claude Code 2.1.251 the variable overrode both, so the
  trade-off line names the version. Low end: 70%.
- **O3.** Subagent calls that edited nothing (no Edit, Write, MultiEdit or NotebookEdit), that O2 does not
  cover, whose context stayed at 100k or less (Haiku has a dearer card above that), and that ran on a model
  dearer than Haiku. The saving is actual cost minus the same tokens at Haiku 5.5. The range assumes 30% to
  60% of those calls would go to the scout.
- **O4.** No dollar figure: how many reasoning tokens medium effort saves depends on the task. The offer states
  what Codex output cost in the window.

## Undo

Every change is logged in `~/.teyla/changes.jsonl` (mode 0600) with the file, the key, the old value and a hash
of the file after the write. Before a write, the file is copied to `<file>.teyla-bak-<UTC time>` (mode 0600).
Writes go to a temp file in the same directory, are renamed over the original under a lock, and keep the
JSON key order, the indent and the file mode. A symlinked settings file is followed.

`teyla undo <offer or change id>`:

- When the file is byte-for-byte what Teyla wrote, undo restores the backup exactly, or deletes the file if
  Teyla created it.
- When you edited the file since, undo reverts only the key Teyla wrote and leaves your edits.
- When the key itself was changed since, or you removed it, undo stops and says so. `--force` puts the old value back anyway.
- A file Teyla created (`scout.md`) is removed only while it is unchanged.
- O5 to O7 log each file the sync created or changed (hash before, hash after), each directory it created and
  each hook entry it added. Before the sync overwrites a file, the file is copied to `<file>.teyla-bak-<UTC time>`
  (mode 0600). Undo restores an overwritten file from that copy and removes a created file only while its hash
  still equals the hash after the apply. A directory goes only when it is empty. A file you edited since stays,
  except that the hook entries Teyla added are taken out of it; anything left in place is listed in the output.
  A policy file, a hook script or a routine you already had is not removed.

A file that is not valid JSON is never written: the offer reports it and changes nothing.
