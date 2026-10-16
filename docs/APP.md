# Teyla for Mac — the coordinator window

Teyla for Mac is one window and a menu-bar icon. Every morning it says in one sentence what
matters today. Below that come the questions only you can answer, ordered by what each one
unblocks, and then where each product stands. You answer in the window, and the answer goes
into the session that asked.

Status: in development (sprint from 2026-10-16). The design is variant B, "morning brief".

## How it works

The app holds no data of its own. It runs two commands of the Teyla CLI:

| Command | Does |
|---|---|
| `teyla state --json` | One snapshot: the brief, questions, products, running sessions, today's spend. |
| `teyla answer <id> <text> [--json]` | Delivers an answer to the session behind a question, then marks it done. |

The app re-runs `teyla state --json` within 2 s of a change under the session stores
(`~/Library/Application Support/Claude/claude-code-sessions`, `~/.claude/projects`,
`~/.codex/sessions`), and every 60 s otherwise.

## Delivering an answer

`teyla answer` tries these in order and reports which one worked:

1. **Codex:** `codex queue --thread <session> --message <text>`. If that fails, `codex exec resume <session> <text>`.
2. **Claude Code and the Claude desktop app:** `claude --bg --resume <cliSessionId> <text>`,
   run in the session's own directory with its permission mode. The session continues in the
   background under the same id. `claude agents` lists it.
3. **Fallback:** the answer goes to the clipboard and the session opens in its app.

Verified on 2026-10-16: `claude -p --resume <id>` continues a session under the same id and
the same transcript file. Not verified yet: whether the desktop app shows a background
continuation of an archived session without reopening it, and `codex queue` on an archived thread.

## The snapshot (version 1)

`tests/fixtures/state.json` is the reference. Fields:

- `version`: 1. `generated`: ISO time.
- `brief`: `{line, source}`. `line` is one sentence of at most 25 words. `source` is `rules`
  or `model`. Can be null.
- `totals`: `{questions, running, spent_today_usd}`. `spent_today_usd` can be null.
- `asks[]`: the open questions, best first. Each has the `teyla asks --json` fields plus:
  - `unblocks`: short text such as "the iPhone release", or "".
  - `rank`: 1 = first.
  - `delivery`: `codex`, `claude`, or `open` — what `teyla answer` will try first.
- `products[]`: `{name, waiting, state, line, last_activity}`.
  - `state` is `waiting`, `active`, `shipped` or `quiet`.
  - `line` is one line of status, for example "iPhone 1.1.5 (126) in TestFlight".
- `running[]`: sessions active in the last 10 minutes: `{product, title, harness, model, since, link}`.

`teyla answer --json` prints `{ok, via, detail, id}`. `via` is `codex-queue`, `codex-resume`,
`claude-bg` or `opened`.
