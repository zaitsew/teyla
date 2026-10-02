# teyla (plugin)

A Claude Code plugin for the file-only half of Teyla: nothing here talks to a
server or a database, and nothing is uploaded. Rules live in the repo it runs in, in git;
corrections live in `~/.teyla/corrections/`, outside every repo. The one outbound call: when
the `teyla` CLI is installed, the session-start hook starts a background `teyla update --check`
(a GitHub release lookup) at most once a day, never in safe mode. `teyla uninstall` removes the
plugin with the rest.

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
- **`review`** (`/teyla:review`) — one review pass on the branch's diff
  (`git diff $(git merge-base origin/<default> HEAD)`, or one fix commit in
  round two), P1/P2 only, `P1 path:line — defect — scenario` or exactly
  `No P1/P2`. Uses `~/ops/bin/codex-review` or a `codex-review`/`claude-review`
  on PATH when one exists (cross-provider); otherwise one fresh sub-agent given
  only the diff, labelled "same-provider review". At most two rounds.

### Commands

- **`/teyla:rule <text> [--scope <glob>]`** — appends a one-sentence rule to
  `.claude/rules/<slug>.md` in the current repo, with a `globs:` frontmatter
  (default `**`), following the conventions in
  `~/ops/.claude/rules/README.md`. Refuses to duplicate a rule that's already
  there — it greps first and just reports the existing file. Also mirrors the
  rule into a `## Rules` section of `AGENTS.md`, but only if `AGENTS.md` is a
  real file in the repo (not a symlink onto `CLAUDE.md` or similar — mirroring
  into a symlink would write through it and double the rule).
- **`/teyla:correct <what was wrong>`** — runs `teyla correct`, which appends
  `{ts, text, cwd, source}` to `~/.teyla/corrections/<repo>-<hash>.jsonl` (secrets
  replaced by `[redacted]`), then drafts a candidate rule
  sentence and scope and asks whether to promote it with `/teyla:rule`. Never
  promotes on its own.

### Hooks

All are POSIX `sh`, exit 0 unconditionally — a broken hook must never break a
session, so every failure path (missing files, bad JSON, no `python3`) is
swallowed silently rather than surfaced.

- **`SessionStart`** (`hooks/session-start.sh`) — if `.claude/rules/*.md`
  exist in the repo, prints a one-line count so it's visible without going to
  look. If `~/.agents/POLICY.md` exists, does nothing: Claude Code already
  imports it on its own, so there's nothing useful to add.
- **`UserPromptSubmit`** (`hooks/capture-correction.sh`) — the same
  correction test `teyla monitor` counts with (`teyla.adapters.is_correction`:
  pushback such as "wrong", "no, I mean…", "don't … at all", "you use too much…",
  "не так", "я же говорил", "сделай сам"; not instructions like "don't forget
  to…"), skipping retries and headless runs (`claude -p`, `grok -p` via the
  `<user_query>` envelope, `hermes -z`). On a match, appends `{ts, cwd, text[:500]}` to `~/.teyla/corrections/<repo>-<hash>.jsonl`
  for the repo the prompt was submitted in (worktrees count as their main
  checkout), after `teyla.corrections.scrub` has replaced tokens, keys, JWTs,
  `password=`-style values and long base64/hex blobs with `[redacted]`. It runs
  the installed `teyla`'s own interpreter, or a `python3` that will not pop the
  macOS developer-tools dialog; with neither, it records nothing. Turns the harness injects as if the
  user typed them — `<task-notification>` (a background subagent finished),
  `<system-reminder>`, `[SYSTEM NOTIFICATION …]`, slash-command expansions —
  are skipped before the heuristic runs; they are not corrections, and their
  boilerplate matches it. Produces **no stdout**, match or not —
  `UserPromptSubmit` stdout is injected into the model's context, and a
  "logged your correction" note on every turn is exactly the kind of narration
  that gets a tool turned off.
- **`Stop`** (`hooks/land-check.sh`) — **opt-in**, `[hooks] land_check = true`.
  Once per session, when the repo has uncommitted files or commits on no remote
  (`git log HEAD --not --remotes`: without `HEAD` a never-pushed repo reads as
  pushed), it tells the model the fact and how to land it: one PR/MR per
  logical unit; merge only when origin's `owner/repo` (GitHub or GitLab, nested
  groups whole) is in the `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md`,
  else open the PR/MR and stop. `additionalContext`, never a block. Not a judge
  of whether the work is *done* — only of whether it reached a remote.
- **Context budget** (`hooks/context-budget.sh` → `context-budget.py`) —
  **opt-in**, `[hooks] context_budget = true`. On `UserPromptSubmit` and every
  `PostToolUse` it reads the transcript's last usage record; at 300k tokens of
  context (`context_budget_first`) and every 40k after (`context_budget_step`)
  it asks the model to write a handoff to `~/.teyla/handoff/<session>.md`; on
  `SessionStart` with source `compact` it puts that handoff back, once. Pair it
  with `"autoCompactWindow": 400000` in `~/.claude/settings.json`. Off, the
  wrapper is one `awk` over `~/.teyla/config.toml` and starts no Python.

Both opt-in hooks are off by default because the owner's personal Mac runs its
own `~/ops` copies; turning them on there would double every note.

## Where data goes

Corrections are kept outside the repo: they are raw prompt text, and a work
repo that does not ignore `.teyla/` would commit them with the next
`git add -A`. Everything else is repo-local, mirroring the `runs/` convention in
`~/ops/CLAUDE.md`:

| Path | Written by | Contents |
|---|---|---|
| `~/.teyla/corrections/<repo>-<hash>.jsonl` | `UserPromptSubmit` hook, `/teyla:correct` | one JSON object per line: `ts`, `text`, `cwd`; 0600, outside the repo |
| `.claude/rules/<slug>.md` | `/teyla:rule`, or you, by hand | committed — rules are decisions, not data |
| `AGENTS.md` (`## Rules` section) | `/teyla:rule`, when the file is real | committed, mirrors `.claude/rules/` |
| `<path>/harvest-<date>/*` | `harvest` skill | proposals for a human to review and merge |
| `runs/teyla/<date>.md` | `adoption-review` skill (via `teyla monitor`) | one monitor report per run |

A pre-0.12 `<repo>/.teyla/corrections.jsonl` is still read (never moved or
deleted), and the first time Teyla touches such a repo it adds `.teyla/` to
`.git/info/exclude`. `teyla config set corrections.store=repo` keeps writing
there instead of `~/.teyla/corrections/`; the exclude is added either way. Add
`runs/teyla/` to `.gitignore` in any repo where you don't want generated reports
committed.

## What it needs

The `teyla` CLI (`uv tool install git+https://github.com/zaitsew/teyla`, or
`pip install -e .` from this repo) for `harvest`, `monitor`, `/teyla:correct`
and the capture hook: the secret scrubber and the correction store are in it,
and without them the hook writes nothing rather than an unscrubbed prompt. If
it's missing, the hooks just do nothing, same as any other failure mode.
