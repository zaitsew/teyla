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

A voice chart is one Markdown file per language, in that language, with a YAML front matter
that a tool can enforce. Keep a channel's charts together, outside the repo if they hold
personal voice (for example `~/.teyla/voice/<channel>/`):

```
BRIEF.md   who writes, who reads, goals, topics, what is never posted (shared)
en.md  es.md  ru.md   one chart each, written from the brief, never translated
```

Copy the template to `<lang>.md`, set `lang`, and fill it in. The front matter holds
`max_sentence_words`, `max_post_chars` per format, `emoji_max`, `hashtags_max`,
`exclamations_max`, `banned` and `preferred`. The body holds 3 or 4 traits ("We are X, not Y"),
tone by channel, the language's register (Spanish: Spain or Latin America, tu or usted;
Russian: ty or vy), and six sample pieces that pass the check.

## Check a draft: `teyla voice check`

```
teyla voice check <file|-> --chart <dir|file> [--lang en|es|ru] [--format F] [--model] [--json]
```

`--chart` takes a chart directory (the draft's language, or `--lang`, picks `<lang>.md`) or one
chart file. `--format` is `x_post`, `x_thread_tweet`, `substack_intro`, `video_hook_15s` or
`linkedin_update`. These checks run on the machine and are exact:

- the longest sentence against `max_sentence_words`
- the length against `max_post_chars` for `--format` (an X link counts 23 characters)
- banned phrases: whole words, any case, any script; a trailing `*` matches any ending
- emoji, hashtags and exclamation marks against their limits

Each failed rule exits 1. A draft that reads as another language than the chart only warns:
the guess comes from script and stop words. `--model` adds one Claude Haiku pass that rates the
draft against the chart's traits and suggests at most three edits. It sends the draft and the
chart to the API, so safe mode refuses it. Exit 2 means a usage or chart error.

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
