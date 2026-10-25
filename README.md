<h1 align="center"><picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/lockup-dark.svg">
  <img alt="Teyla" src="brand/lockup.svg" width="200">
</picture></h1>

Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting on you, and fixes the waste. Nothing about your sessions leaves your Mac unless you turn it on.

![The Start page of teyla web: what 30 days of sessions cost, and the first changes that would save money](docs/img/web-start.png)

## Set it up with your agent

Paste this into Claude Code or Codex:

```
Set up https://github.com/zaitsew/teyla
```

The agent reads [AGENTS.md](AGENTS.md), installs Teyla, and shows you what your sessions cost. It then asks about each change on its own, with the saving and the way back, and changes no setting without your yes.

## Or by hand

You need a Mac and [uv](https://docs.astral.sh/uv/). It downloads Python 3.12 (about 25 MB) if the Mac has no Python 3.11 to 3.13.

```bash
uv tool install --python 3.12 git+https://github.com/zaitsew/teyla
teyla start          # the diagnosis, then each change: yes, no or explain
```

Try it first without installing it. It changes no setting of your tools; it keeps its counts in `~/.teyla`:

```bash
uvx --python 3.12 --from git+https://github.com/zaitsew/teyla teyla start
```

## Cost and waste

`teyla start` reads the Claude Code, Codex, Grok, Cursor and Hermes sessions already on your disk and prints a card like this one (the numbers are made up):

```
Last 30 days: $1,840 at API list price over 212 sessions on 24 days (claude-code $1,610, codex $230).
41% of it ($754) was re-reading and storing context; 9 sessions ran past 250k tokens of context and cost $402.
Subagents cost $390; Opus ran 64% of that.
  O1 Compact long sessions earlier: about $95-$190 a month
  O2 Run subagents on Sonnet unless they say otherwise: about $60-$140 a month
```

*List price* is what the tokens would cost through the API; a subscription bills differently. *Context* is everything a session has read so far, and the agent re-reads all of it on every turn. A *subagent* is a helper agent a session starts for one side task. Each change shows its saving, its trade-off and its undo. `teyla spend --days 7` and `teyla web` show the same numbers later.

## What's waiting on you

A session ends on a question, the desktop app archives it, and nobody reads it again. `teyla today` is the daily screen: the questions waiting by product, the notes in your Inbox, this week's spend against last week's, and one next step. `teyla asks` lists every open question, oldest first, with a link that reopens the session.

## Your products and notes

A *product* is a repo, or a few, that you ship as one thing. `teyla product init` proposes the list from your repos; `--write` saves it. `teyla product` lists them with their stage. `teyla note "try a dark icon"` keeps an idea as you typed it and files it under a product, or in your Inbox. `teyla notes` lists them. The Mac app adds a quick note on a shortcut (⌥Space by default).

## One policy for every agent

Your rules live in one tool; switch to another and it has never heard of them. `teyla policy init --owner "Your Name"` writes one `POLICY.md`, and `teyla policy sync` hands it to Claude Code, Codex, Grok, Cursor and Hermes. `teyla harness sync` adds *hooks* to them: small scripts an agent runs at set moments, such as session start. The offer in `teyla start` that runs it also installs the Claude Code plugin. `teyla routine install` schedules a daily and a weekly check. [GUIDE](docs/GUIDE.md) has the detail.

## The Mac app

Teyla for Mac is a window and a menu-bar icon: today's brief, the questions you can answer in place, the diagnosis and your products. It runs the `teyla` command, so install that first. The app is built from this repo for local use (macOS 15, Xcode):

```bash
brew install xcodegen && git clone https://github.com/zaitsew/teyla && cd teyla/apps/mac && ./install.sh
```

## Privacy

Teyla reads files on your Mac. It sends nothing about your sessions unless you run one of these:

- **Update check.** On by default: once a day, to GitHub, with the version number and nothing else.
- **Lookups through `gh`, `git` or `ssh` under your own login.** Examples: `teyla spend`, `teyla reviews`, `teyla state`. They send repo names, PR numbers and your login and org names.
- **Text to your model provider under your own login.** Only when you ask: `teyla answer`, `teyla run`, `--model` flags and `harness verify --live`. The one-line morning brief is off until you turn it on.
- **`teyla relay on`** writes your open questions and session titles to a folder in iCloud Drive. Off by default.

`teyla web` listens on 127.0.0.1 only. Safe mode, `teyla config set safe.enabled=true`, closes most of these calls; one you type by hand can open with `--allow-network`. Every call, with its host and what it sends: [docs/PRIVACY.md](docs/PRIVACY.md).

## Undo and uninstall

```bash
teyla changes              # every change Teyla made, and whether it is undone
teyla undo O1              # put back only the setting Teyla wrote (O1 to O4)
teyla uninstall --dry      # list what Teyla would remove: links, hooks, jobs
teyla uninstall && uv tool uninstall teyla
```

Each setting change makes a backup first. `teyla undo` does not reverse O5, O6 or O7 (policy, hooks, routines); `teyla uninstall` does.

## Links

[Guide](docs/GUIDE.md) · [Commands](docs/COMMANDS.md) · [`teyla start`](docs/START.md) · [`teyla web`](docs/WEB.md) · [Privacy](docs/PRIVACY.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [License](LICENSE) (Apache-2.0)
