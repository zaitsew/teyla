# Writing

Teyla keeps one writing contract in the policy ("Writing and reporting" in `templates/POLICY.md`),
in three registers. This page covers the tools around it.

| Register | Where it applies | Rules come from |
|---|---|---|
| (a) | Agent replies, status, internal docs | The policy: answer first, short sentences, a ban list, a session-end card |
| (b) | Product UI copy | The voice section of the product's `DESIGN.md` |
| (c) | Marketing and social | The product's voice chart, one section per language |

## Measure replies: `teyla prose`

```
teyla prose [--days 7] [--project SUBSTR] [--json]
```

It reads the last text of each turn the human saw, from Claude Code and Codex sessions.
Subagent and headless sessions are skipped. Per harness and per project it reports:

- median and 90th-percentile words, and the share of replies over 150 words
- the share of sentences over 25 words
- ban-list hits per 1,000 words, and the top five phrases
- the share of replies that open with a preamble ("Let me", "I'll", "Great", "Sure", "Okay")

Code blocks and table rows do not count. Each finding above its threshold prints one advice
line. The weekly digest adds "reply length: median N words (target <= 150)" when the week's
median is over the target. The ban list is `BAN_LIST` in `src/teyla/prose.py`.

## Write a voice chart: `templates/voice/VOICE.md`

Copy it into the product repo (for example `docs/VOICE.md`) and fill in the placeholders.
It holds 3 or 4 traits ("We are X, not Y"), a tone table per channel, one section each for
English, Spanish and Russian, and a checklist before posting. Write each language from the
same brief. Never translate one language into another.

## Lint with Vale (optional)

`templates/vale/` holds a Vale config and a `Teyla` style. `Filler.yml` flags the ban list.
`Sentences.yml` flags a document whose average sentence is over 25 words; it needs Vale 3.21
or later and is untested, because Vale was not installed when it was written.

To adopt it in a repo:

1. Install Vale (`brew install vale`).
2. Copy `templates/vale/.vale.ini` and `templates/vale/styles/` to the repo root.
3. Run `vale README.md docs`. Fix the warnings, or delete a rule you disagree with.

For Russian text, Glavred (glvrd.ru) is the matching checker. It is a web service: paste
only text that is already public. Vale is free and open source, so no paid tone tool is needed.
