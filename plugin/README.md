# teyla (plugin)

A Claude Code plugin for the file-only half of Teyla: nothing here talks to a
server or a database. Everything it reads and writes lives in the repo it runs
in, in git. Nothing leaves the machine.

## Install

```sh
claude plugin add ~/repos/teyla/plugin
```

(A marketplace entry may follow later; for now this is a local path install.)

**No `claude` binary on PATH** (Claude Code running only as the desktop app — the normal
case on a managed laptop; check with `command -v claude`)? The commands above, and the
documented `claude plugin marketplace add <path>` fallback, all need that missing binary.
Run `teyla plugin install zaitsew/teyla` (or a local path to this repo) instead — it clones
the marketplace if needed, copies `plugin/` into `~/.claude/plugins/cache/...`, and writes
the same `known_marketplaces.json` / `installed_plugins.json` entries `claude plugin
install` would, backing up both registry files first. `teyla plugin uninstall teyla`
reverses it. See `src/teyla/plugin_install.py`.

**Codex has no CLI either** on a machine like that — it lives inside the ChatGPT desktop
app and is not on PATH — so there is no equivalent install step to run for it; treat it as
a harness `teyla doctor` can read logs from, not one you can drive from a shell.

## What's in it

### Skills

- **`harvest`** (`.claude/skills` auto-load, or ask for it by name) — turns
  sessions that repeatedly touched a path into a proposed skill, a
  candidate-rules list, and a routine manifest. Calls `teyla harvest <path>`
  (the `teyla` CLI, from `src/teyla` in this repo) when installed, and falls
  back to an inline grep+python equivalent when it isn't. Writes four files
  into `<path>/harvest-<date>/`: `SKILL.draft.md`, `candidate-rules.md`,
  `routine.yml`, `done-test.md`. Never overwrites an existing skill or rules
  file, and never promotes a rule on its own.
- **`adoption-review`** — runs `teyla monitor --days 30 --out
  runs/teyla/<date>.md`, reads the findings, and turns the top three into
  concrete changes: a rule (via `/teyla:rule`), a `model:` override, or a
  flagged session split. Requires the `teyla` CLI — there's no fallback for
  `monitor`, since it needs the full session-adapter set, not a one-off parse.

### Commands

- **`/teyla:rule <text> [--scope <glob>]`** — appends a one-sentence rule to
  `.claude/rules/<slug>.md` in the current repo, with a `globs:` frontmatter
  (default `**`), following the conventions in
  `~/ops/.claude/rules/README.md`. Refuses to duplicate a rule that's already
  there — it greps first and just reports the existing file. Also mirrors the
  rule into a `## Rules` section of `AGENTS.md`, but only if `AGENTS.md` is a
  real file in the repo (not a symlink onto `CLAUDE.md` or similar — mirroring
  into a symlink would write through it and double the rule).
- **`/teyla:correct <what was wrong>`** — appends `{ts, text, cwd}` to
  `.teyla/corrections.jsonl` in the current repo, then drafts a candidate rule
  sentence and scope and asks whether to promote it with `/teyla:rule`. Never
  promotes on its own.

### Hooks

Both are POSIX `sh`, exit 0 unconditionally — a broken hook must never break a
session, so every failure path (missing files, bad JSON, no `python3`) is
swallowed silently rather than surfaced.

- **`SessionStart`** (`hooks/session-start.sh`) — if `.claude/rules/*.md`
  exist in the repo, prints a one-line count so it's visible without going to
  look. If `~/.agents/POLICY.md` exists, does nothing: Claude Code already
  imports it on its own, so there's nothing useful to add.
- **`UserPromptSubmit`** (`hooks/capture-correction.sh`) — a cheap heuristic
  over the raw prompt text (`don't`, `wrong`, `not like that`, `again`,
  `revert`, and the Russian equivalents `не так`, `неправильно`, `опять`). On a
  match, appends `{ts, cwd, text[:500]}` to `.teyla/corrections.jsonl` under
  the repo the prompt was submitted in. Produces **no stdout**, match or not —
  `UserPromptSubmit` stdout is injected into the model's context, and a
  "logged your correction" note on every turn is exactly the kind of narration
  that gets a tool turned off.
- **`Stop`** — none, on purpose, for now. A real judge of "did this session's
  work actually land" needs a model call to read the transcript and decide,
  which this file-only plugin doesn't make. Planned once there's a cheap way
  to do that without a round-trip that slows every `Stop`.

## Where data goes

Everything is repo-local and gitignored data, not committed source, mirroring
the `runs/` convention in `~/ops/CLAUDE.md`:

| Path | Written by | Contents |
|---|---|---|
| `.teyla/corrections.jsonl` | `UserPromptSubmit` hook, `/teyla:correct` | one JSON object per line: `ts`, `text`, `cwd` |
| `.claude/rules/<slug>.md` | `/teyla:rule`, or you, by hand | committed — rules are decisions, not data |
| `AGENTS.md` (`## Rules` section) | `/teyla:rule`, when the file is real | committed, mirrors `.claude/rules/` |
| `<path>/harvest-<date>/*` | `harvest` skill | proposals for a human to review and merge |
| `runs/teyla/<date>.md` | `adoption-review` skill (via `teyla monitor`) | one monitor report per run |

Add `.teyla/` and `runs/teyla/` to `.gitignore` in any repo where you don't
want generated logs and reports committed — they're recoverable by rerunning,
same as any other `runs/` directory.

## What it needs

The `teyla` CLI (`pip install -e .` from this repo, or however it ends up
packaged) for `harvest` and `monitor`. `python3` on `PATH` for the hooks —
if it's missing, the hooks just do nothing, same as any other failure mode.
