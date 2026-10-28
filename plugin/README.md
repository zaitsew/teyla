# Teyla for Claude Code

Teyla turns repeated work into skills and rules. It reads the sessions you already ran,
proposes a skill from what you did the same way every time, records your corrections
outside the repo, reviews a diff before you merge, and tidies the rule files that load into
every session. Everything is a local file. There is no server, no account and no upload.

## Install

```sh
/plugin install teyla --marketplace zaitsew/teyla
```

That is all you need for `/teyla:rule`, the `review` skill and the hooks. The `harvest`,
`tidy`, `wiki-pass` and `adoption-review` skills and `/teyla:correct` call the separate
Teyla CLI. Install it once (Python 3.11 or newer):

```sh
uv tool install --python 3.12 git+https://github.com/zaitsew/teyla      # or: pipx install git+https://github.com/zaitsew/teyla
```

Without the CLI each of those skills and commands says so in one line and stops. `harvest`
is the exception: it falls back to a plain `grep` and `python3` pass over your transcripts.
Every hook exits 0 without a sound when the CLI is missing, so a session never breaks.

No `claude` binary on PATH (the desktop app only)? Install the CLI, then run
`teyla plugin install zaitsew/teyla`. It writes the same registry entries
`/plugin install` would, after backing both files up. `teyla plugin uninstall teyla`
reverses it.

## What is in it

### Skills

| Skill | What it does | Needs the CLI |
|---|---|---|
| `harvest` | Turns sessions that repeatedly touched a path into `SKILL.draft.md`, `candidate-rules.md`, `routine.yml` and `done-test.md` in `<path>/harvest-<date>/`. Only steps done the same way every time go into the skill. Never overwrites a skill or a rules file. | No (fallback) |
| `review` | One review pass on the branch diff, P1/P2 only, at most two rounds. Uses a second-provider review script when one is on PATH, otherwise one fresh sub-agent that sees only the diff. | No |
| `tidy` | Proposes edits that shorten `CLAUDE.md`, `AGENTS.md`, `.claude/rules` and memory files: dated anecdotes become rules, near-duplicates merge. Shows a diff and writes only what you approve. | Yes |
| `wiki-pass` | Files this session's facts into a markdown wiki, marked agent-drafted until a person confirms them. | Yes |
| `adoption-review` | Runs `teyla monitor` over the last 30 days and turns the top three findings into a rule, a `model:` override or a session split. | Yes |

### Commands

- **`/teyla:rule <text> [--scope <glob>]`** appends a one-sentence rule to
  `.claude/rules/<slug>.md` with a `globs:` front matter. It refuses to duplicate a rule. It
  mirrors the rule into the `## Rules` section of `AGENTS.md` only when that is a real file,
  not a symlink. No CLI needed.
- **`/teyla:correct <what was wrong>`** runs `teyla correct`: the text goes to
  `~/.teyla/corrections/` with tokens, keys and `password=` values replaced by `[redacted]`.
  Then it drafts a rule and asks before promoting it with `/teyla:rule`.

### Hooks

Hooks run in Claude Code and Cowork. Claude chat on the web ignores them. All are POSIX `sh`
(one also runs a stdlib-only Python file), and every failure path exits 0 without output.

| Event | Script | What it does | Default |
|---|---|---|---|
| `SessionStart` | `session-start.sh` | Prints how many `.claude/rules/*.md` files the repo has. With the CLI, adds its one-line notices (see Privacy). | on |
| `UserPromptSubmit` | `capture-correction.sh` | Records prompts that look like a correction, scrubbed, in `~/.teyla/corrections/`. Writes nothing without the CLI. | on, CLI only |
| `UserPromptSubmit` | `capture-intent.sh` | Keeps a prompt of 400 characters or more, scrubbed, in `~/.teyla/intent/<repo>.md`. Writes nothing without the CLI. | on, CLI only |
| `PreToolUse` | `pre-tool-use.sh` | The kill switch. It denies every tool call while `~/.teyla/KILL` exists, and it enforces capability grants only for a run you started with `teyla run`. Without those files it allows the call. | on |
| `PreToolUse` (Bash) | `machine-guard.sh` | Refuses a build, a simulator boot or a headless agent while the machine is out of memory. Needs the CLI, otherwise allows. It fails open. | on, CLI only |
| `Stop` | `land-check.sh` | Once per session, notes work that never reached a remote. | off (`teyla config set hooks.land_check=true`) |
| `SessionStart`, `UserPromptSubmit`, `PostToolUse` | `context-budget.sh` | Asks the model to write a handoff note before a long session compacts, and puts it back after. | off (`teyla config set hooks.context_budget=true`) |

`pre-tool-use.sh` is the one script that can exit 2 on purpose: only when you created
`~/.teyla/KILL` or started a `teyla run` with grants. A plain install has neither.

The two opt-in hooks stay off because a machine that already runs its own copies would see
every note twice.

### MCP server

`.mcp.json` registers `teyla mcp`, a local server that gives Claude six tools. It needs the
`teyla` CLI on PATH (see Install). It speaks MCP over stdio only: no network listener, no
port. Each tool runs one Teyla command as a child process.

| Tool | What it does |
|---|---|
| `teyla_asks` | Lists the questions your agent sessions are waiting on. Read-only. |
| `teyla_answer` | Sends your answer to the session that asked. It resumes that local Claude Code or Codex session, as `teyla answer` does. Claude sends only text you wrote or approved. |
| `teyla_intent` | Returns your own prompts for a product, word for word. Read-only. |
| `teyla_load` | Says whether this Mac can take heavy work now (OK, BUSY or CRITICAL). Read-only. |
| `teyla_routines` | Shows whether each product's scheduled routines and checks ran. Read-only. |
| `teyla_monitor` | Summarises your AI session usage from local logs. Read-only. |

`teyla mcp --list-tools` prints the same list. Without the CLI the server does not start and
the plugin's skills and hooks work as before.

## Privacy

**Short answer:** this plugin uploads nothing. Its hook scripts and skills contain no
network call. Everything it reads and writes is on your machine, in the places listed
below. Claude Code already sends your session to Claude; Teyla adds no second destination,
with the one optional exception under Network.

### What it reads

- The input each hook receives from Claude Code: your prompt text, the tool name, the Bash
  command about to run, the working directory, the session id and the transcript path.
- Session transcripts under `~/.claude/projects/`: when you run `harvest` or
  `adoption-review`, and, if you turn on `context-budget`, the last usage record.
- `.claude/rules/*.md`, `AGENTS.md` and `CLAUDE.md` in your repo and home folder: by
  `/teyla:rule`, `tidy`, the rule count, and `land-check` (it reads the
  `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md`, if you have one).
- Git state of the current repo (status, remote URL, diff): by `review` and `land-check`.

### What it writes

| Where | Written by | Contents |
|---|---|---|
| `.claude/rules/<slug>.md`, `AGENTS.md` (`## Rules`) | `/teyla:rule` | the rule you gave |
| `<path>/harvest-<date>/` | `harvest` | four proposal files for you to review |
| `runs/teyla/<date>.md` | `adoption-review` | one monitor report |
| wiki pages, `index.md`, `log.md`, `inbox.md` | `wiki-pass` | facts you or the session established |
| your rule and memory files | `tidy` | only the edits you approve |
| `~/.teyla/corrections/<repo>-<hash>.jsonl` (mode 0600) | `/teyla:correct`, `capture-correction.sh` | timestamp, text, directory; secrets replaced by `[redacted]` |
| `~/.teyla/intent/<repo>.md` (mode 0600) | `capture-intent.sh` | prompts of 400+ characters, word for word, secrets scrubbed |
| `~/.teyla/handoff/<session>.md` (mode 0600) | `context-budget` (opt-in) | the model's own handoff note |
| `$TMPDIR/teyla-land-check/<session>` | `land-check` (opt-in) | an empty marker file |
| `~/.teyla/*` (stamps, notice files) | the CLI and `session-start.sh`, on a machine where Teyla is set up | small state files |

Corrections and intent live outside the repo on purpose: they are raw prompt text, and a
work repo would commit them with the next `git add -A`. The two capture hooks write only
when the CLI is installed, because the secret scrubber is in it. Without the CLI the hook
writes nothing instead of an unscrubbed prompt. Turn the intent capture off with
`teyla config set intent.enabled=false`.

Nothing is deleted or expired automatically. Remove `~/.teyla/` to remove what the hooks
kept. `teyla uninstall --dry` lists everything Teyla put on a machine, and
`teyla uninstall` reverses it.

### Network

- **The plugin's own files** (hooks, skills, commands): none. Searching `plugin/` for
  `curl`, `wget`, `socket`, `urllib` and `ssh` finds no call (two comments in
  `land-check.sh` mention ssh remote URLs), and the only URLs are text: the install lines
  and links to documentation.
- **The MCP server (`teyla mcp`).** It opens no port and makes no request itself. Its tools run the
  Teyla commands named above. `teyla_routines` may ask GitHub for workflow status through your
  own `gh` login, unless `TEYLA_SAFE=1`. `teyla_answer` starts your local `claude` or `codex`,
  which sends the answer to your provider under your account.
- **`review`, optional second reviewer.** If a `codex-review` or `claude-review` script is on
  your PATH, the skill runs it, and that script sends the diff to the provider it wraps. The
  skill labels the result "cross-provider review". Without such a script, a sub-agent of
  your own Claude session reviews the diff and nothing else is contacted.
- **`wiki-pass`.** When your wiki is a git repository, it pushes a branch and opens a pull
  request with `gh` or `glab`, to your own git host.
- **The Teyla CLI, started in the background by `session-start.sh`.** Only on a machine
  where `~/.teyla/config.toml` exists (written by `teyla policy init` or `teyla config set`,
  never by installing the plugin or the CLI). At most once a day it starts
  `teyla update --check` (a read-only release lookup on `api.github.com`; it sends no
  session data), `teyla doctor`, `teyla routine catch-up` (runs Teyla's own scheduled jobs
  that macOS skipped, and may rewrite them) and `teyla asks`. It also runs
  `teyla policy sync` when a Teyla-generated `~/.codex/AGENTS.md` or `~/.grok/AGENTS.md` is
  out of date. What each command reads, writes and contacts is documented in
  [docs/WORK.md](https://github.com/zaitsew/teyla/blob/main/docs/WORK.md). Set
  `TEYLA_SAFE=1` (or `teyla config set safe.enabled=true`) and the CLI makes no network
  request unless you type `--allow-network`.

### Not for children

Teyla is a developer tool. It is not directed at people under 18 and collects no account
or profile data.

## Uninstall

```sh
/plugin uninstall teyla
rm -r ~/.teyla        # only if you also want the recorded corrections and notes gone
```

## Support and license

Questions and bugs: <https://github.com/zaitsew/teyla/issues>. Source and the full manual:
<https://github.com/zaitsew/teyla>. Apache-2.0, see `LICENSE`.
