# teyla sessions tidy

The Claude desktop app archives a session after 7 idle days, including one that ends on a
question to you: 27 of the 40 open questions in `teyla asks` sat in the archive. `teyla sessions tidy`
is the inverse rule: it archives only the sessions where nothing is needed from you.

## Use

    teyla sessions tidy [--idle-hours 24] [--json]   the plan: what would be archived, the rest counted by reason
    teyla sessions tidy --apply                      Codex: `codex archive <uuid>` for each candidate (mode on only)
    teyla sessions record <session-id>...            log Claude desktop sessions an agent archived with the app's tool
    teyla sessions undo --last | <id-prefix>...      Codex: `codex unarchive`; Claude: prints the ids to unarchive
    teyla sessions log [--days 7] [--json]           what was archived, or would have been
    teyla sessions report                            the dry-week verdict
    teyla sessions mode [dry|on|off]                 show or set the mode

## The rule

A session is archived only when all of this holds:

1. It is not archived, and its last activity is at least `--idle-hours` ago (24).
2. `teyla asks` has no ask for it that is not done. Open, snoozed and muted (parked product) asks keep it. A done ask, an ask
   `settle` closed (PR merged, report, task off, TestFlight current) and a duplicate (folded into a newer
   ask, which keeps its own session) do not. The asks are collected and settled by the same code as `teyla asks`.
3. It has no open PR. Every PR the session names needs a known state (the `teyla asks` PR check and
   its cache); an unknown state keeps the session. No new network call is made.
4. Its worktree, if it still exists, is clean (`git status --porcelain` is empty) and its HEAD is on a remote
   branch (`git branch -r --contains HEAD`). The app removes the worktree on archive, so anything else is
   kept with the reason `worktree has unpushed work`.
5. Codex: interactive sessions only. `codex exec` runs and spawned agents are skipped.

The app itself refuses to archive a running or pinned session.

## Modes

State is `~/.teyla/sessions-tidy.json` (mode, `dry_until`) and the append-only log
`~/.teyla/sessions-tidy.jsonl`: time, run, harness, session, title, product, action
(`would_archive`, `archived`, `unarchived`), reason. Both files are private (mode 600).

| mode | `tidy` | `tidy --apply` |
|---|---|---|
| `dry` (default) | prints the plan, logs each candidate once as `would_archive` | refused |
| `on` | prints the plan; `--json` has `"mode": "on"` | archives the Codex candidates |
| `off` | prints the plan and says it is off | refused |

The first run sets `dry_until` seven days ahead. `teyla sessions report` counts the logged sessions by harness and
product, and the mistakes: sessions that got a human prompt after they were logged (Claude: the desktop
`lastActivityAt` moved and the transcript has a later human turn; Codex: a later user message in the rollout). It ends
with one line: `mode on` when there are none, else the titles of the mistakes.

## The daily desktop agent

Claude desktop sessions are archived by the app's own tool, not by Teyla. The agent runs

    teyla sessions tidy --json

and, when `"mode"` is `"on"`, calls `archive_session` for each row with `"harness": "claude-desktop"` and
`"verdict": "archive"`, then `teyla sessions record <session-id>...` so the log and `report` see them. In
`dry` or `off` mode the agent archives nothing. `--json` lists the kept rows too, with their reasons.

## Undo

`teyla sessions undo --last` reverses the last run, `undo <id-prefix>` one session. A Codex session is
unarchived with `codex unarchive`. For a Claude session the command prints the ids, and the agent calls the app's
`unarchive_session`. An undone session can become a `would_archive` row again.
