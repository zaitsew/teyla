# teyla asks

One list of every question an AI session left waiting on you. A session ends on a
question, the desktop app archives it, and nobody reads it again. In 14 days 40 Claude
Code sessions ended that way and 1 got an answer. `teyla asks` finds them.

## Use

    teyla asks                       open items, grouped by product, oldest first
    teyla asks --html --open         the same as one page (~/.teyla/asks.html), readable on a phone
    teyla asks done <id> [--note T]  close one; a prefix of 3+ characters is enough
    teyla asks snooze <id> <days>    hide one until the days pass
    teyla asks --all --json          include done and snoozed; machine-readable
    teyla asks --days 60 --product P widen the window, or keep one repo

The header reads "N waiting on you (M in archived sessions)". Each item shows the question
word for word, a short context line, the options the agent offered, and a link that reopens the
session (`claude://claude.ai/epitaxy/local_...`, or `codex resume <id>` for Codex).

## Where items come from

| Source | An item is |
|---|---|
| Claude desktop session metadata | a session whose summary is `blocked` or has a `needs_action` line |
| Claude Code transcripts | a last turn that calls `wrap_up` with an `ask`, or ends with a question |
| Codex rollouts | a `request_user_input_async` call with no output, or a final message ending in a question |
| Teyla | a pending gated run (`teyla inbox`); a reminder overdue or due within 7 days |

A desktop session and its transcript are one item. Question text priority: the `ask`, then
`needs_action`, then the trailing question. `codex exec` runs, spawned agents and `claude -p`
sessions are automation and are skipped. Everything is read-only; secrets are scrubbed and
text is cut at 600 characters.

An item closes by itself when a later human prompt appears in its session. Done and snoozed
items live in `~/.teyla/asks.json`. The default window is 21 days.

## Session start

The daily routine and a background refresh (at most hourly, started by the session-start hook)
run `teyla asks --quiet`, which writes `~/.teyla/asks.count`. The hook prints that one line when
the file is under 3 days old: "3 questions wait for you — teyla asks". It scans nothing itself.
Reminders are not counted; they already reach the banner.

## Privacy

`teyla asks` output holds session text. It never goes into `monitor --share` or `feedback`;
`tests/test_share_leaks.py` plants a waiting session and checks that. Override the desktop
metadata root with `TEYLA_CLAUDE_SESSIONS` (tests do).
