# The same manner in every harness

Claude Code in the Claude desktop app has the whole loop: the policy imported by
`~/.claude/CLAUDE.md`, the plugin's skills (`harvest`, `adoption-review`, `wiki-pass`), the
two commands (`/teyla:rule`, `/teyla:correct`), and the hooks that show the doctor summary at
session start and capture corrections as they are typed. This page is what the other three
desktop-app harnesses get, how, and what each one cannot do. Every fact about a harness was
read from that harness's own files on one machine on 2026-09-14 (Cursor 3.19.7, Codex CLI
0.153.4 inside ChatGPT 26.908, Grok CLI 1.0.0, Hermes Agent 0.20.4); the file is named so
a newer version can be re-checked against it. Hooks were re-checked on 2026-09-29: Codex by
running `codex exec` and `codex app-server` (0.153.4 from npm; 0.158.0-alpha.2.1, the CLI
the ChatGPT app now bundles) against a scratch `CODEX_HOME`, Hermes 0.20.4 from
`~/.hermes/hermes-agent` (`agent/shell_hooks.py`, `website/docs/user-guide/features/hooks.md`),
Grok 1.0.0 from `~/.grok/docs/user-guide/10-hooks.md`.

```
teyla policy sync      # the policy into every harness (was: Claude, Codex, Grok, Hermes; now also Cursor)
teyla harness sync     # the skills and hooks into Cursor, Codex, Grok, Hermes
teyla harness status   # what is wired where
teyla doctor           # the same, as OK/FIX lines
```

`teyla update` runs both, so a new release re-renders every copy.

## What each harness reads

| | policy | per-repo rules | skills | hooks | sessions read by `teyla monitor` |
|---|---|---|---|---|---|
| **Claude Code** | `@~/.agents/POLICY.md` in `~/.claude/CLAUDE.md` | `.claude/rules/*.md` (`globs:`), `CLAUDE.md` | the plugin (`teyla plugin install`) | plugin `hooks.json`: SessionStart, UserPromptSubmit, PreToolUse | `~/.claude/projects/**/*.jsonl` |
| **Cursor** (app) | a user skill `~/.cursor/skills/teyla-policy/SKILL.md` carrying the policy text — Cursor has no global rules file (`create-rule/SKILL.md` names only `.cursor/rules/*.mdc` per project) | `AGENTS.md` at the repo root; `.cursor/rules/<slug>.mdc` when that directory exists (`teyla rule` fills both) | `~/.cursor/skills/teyla-*/SKILL.md` (`name`, `description`, `disable-model-invocation: false`) | `~/.cursor/hooks.json`: `sessionStart`, `beforeSubmitPrompt` (JSON on stdin) | `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb` (`composerData:*`, `bubbleId:*`; model name, turns, tools; no per-message tokens) |
| **Codex** (ChatGPT app / CLI) | `~/.codex/AGENTS.md` → `POLICY.md` symlink | `AGENTS.md` per directory | `~/.codex/skills/teyla-*/SKILL.md` | `~/.codex/hooks.json`: `SessionStart`, `UserPromptSubmit` (Claude Code's shape; `codex features list`: `hooks stable true`); each runs only after you trust it once in Codex | `~/.codex/sessions/**/rollout-*.jsonl` |
| **Grok CLI** | `~/.grok/AGENTS.md` → `POLICY.md` symlink | `Agents.md`/`CLAUDE.md`/`AGENTS.md` per directory, repo root down to cwd (`12-project-rules.md`) | `~/.grok/skills/teyla-*/SKILL.md`; also scans `~/.claude/skills`, `~/.cursor/skills`, `.agents/skills` (`08-skills.md`) | `~/.grok/hooks/teyla.json`: `SessionStart`, `UserPromptSubmit`; it also loads `~/.cursor/hooks.json` and `~/.claude/settings.json` (`10-hooks.md`), so the capture hook de-duplicates | `~/.grok/sessions/<cwd>/<id>/` |
| **Hermes** (app / CLI) | an "Operating policy" section in `~/.hermes/SOUL.md` | `AGENTS.md` chain from the git root (`context-files.md`; `.hermes.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`, first match) | `~/.hermes/skills/teyla/teyla-*/SKILL.md`, each also a slash command (`skills.md`) | a `hooks:` block in `~/.hermes/config.yaml`: `on_session_start`, and two `pre_llm_call` shell hooks (capture; first-turn orientation); Hermes asks once per hook before running it (`hooks.md`, "Shell hooks") | `~/.hermes/state.db` |

The skills are rendered from the plugin's own `SKILL.md` files with `/teyla:rule` and
`/teyla:correct` replaced by the CLI — `teyla rule "<sentence>" --scope <glob>` and
`teyla correct "<what was wrong>"` do the same two file writes the Claude commands do — and
each copy says which source it was generated from. Edit the source; the next sync overwrites
the copy. The hook scripts are one copy each in `~/.teyla/hooks/`, the plugin's own two
scripts, which read every harness's stdin shape.

## What is not the same, and why

- **Session-start orientation** reaches the model in three of five. Claude Code injects the
  hook's stdout into the model's context; that is where "teyla: 2 warning(s)" and the
  product's routine line come from. **Codex** does the same: plain `SessionStart` stdout
  becomes a developer message tagged `hooks.additional_context` in the rollout (verified
  2026-09-29 with `codex exec` and with `codex app-server`, the path the ChatGPT app uses;
  `{"hookSpecificOutput": {"additionalContext": …}}` works too). **Hermes** ignores what
  `on_session_start` prints, but adds a `pre_llm_call` shell hook's `{"context": "…"}` to the
  user message (`agent/shell_hooks.py` `_parse_response`); `session-start.sh --context-json`
  answers only when the payload says `"is_first_turn": true`, so the lines arrive once, with
  the first message. Grok ignores `SessionStart` stdout and `UserPromptSubmit` output alike
  (`10-hooks.md`, "Passive Hooks": "stdout is ignored"; only `PreToolUse` and `Stop` outputs
  are read); Cursor's docs do not say what `sessionStart` output does. In those two the hook
  still runs — it starts the background update check and `teyla routine catch-up` — but the
  model does not see the line; `teyla doctor` is the command to run by hand there.
- **`codex exec` is not a person.** Codex fires both hooks for `codex exec` too (509 of 520
  Codex sessions in September 2026 were `codex exec` reviews). The payload names
  `transcript_path`; when that rollout's first record says `"originator":"codex_exec"`,
  `session-start.sh --codex` prints nothing and starts nothing, and the capture hook records
  nothing — the same test the monitor uses to call a Codex session batch.
- **Correction capture** works in all five (Claude Code and Codex `UserPromptSubmit`, Cursor
  `beforeSubmitPrompt`, Grok `UserPromptSubmit`, Hermes `pre_llm_call` with
  `extra.user_message`); the skill `teyla-correct` records one by hand anywhere.
- **Approval, once, in the harness.** Codex runs a new or changed hook only after you trust
  it: open Codex in a terminal (`codex`), answer "Hooks need review" with *Trust all and
  continue*, or use `/hooks`. Until then it skips the hook silently, `codex exec` included
  (`--dangerously-bypass-hook-trust` exists for automation; Teyla does not use it). Trust
  lives in `~/.codex/config.toml` as `[hooks.state."<hooks.json>:<event>:<group>:<handler>"]
  trusted_hash`, a sha256 of the hook's normalized definition, so `teyla harness status`
  reads it and says `approved 2/2` or `NOT APPROVED 0/2` — Teyla never writes it. Hermes
  asks once per `(event, command)` on a terminal and records the answer in
  `~/.hermes/shell-hooks-allowlist.json`; the desktop app and `hermes -z` are not a terminal
  and skip an unapproved hook, so run `hermes` in a terminal once (or set
  `hooks_auto_accept: true`). Status reads that file too. A resync that changes a hook's
  command or timeout makes Codex call it "modified" and ask again.
- **Codex's hooks.json is strict.** Any top-level key other than `description` and `hooks`
  makes Codex skip the whole file ("failed to parse hooks config … unknown field"), so
  Teyla's marker there is not a comment: its entries are the ones whose command is under
  `~/.teyla/hooks/`, and the file's `description` says so. Delete those entries (or the
  file, if nothing else is in it) to undo; `teyla harness sync` keeps every other entry.
- **Rules.** `.claude/rules/*.md` is read by Claude Code only. `teyla rule` therefore mirrors
  every rule into `AGENTS.md`'s `## Rules` section, which all four other harnesses read, and
  into `.cursor/rules/<slug>.mdc` when the repo has that directory. A repo whose `AGENTS.md`
  is a symlink onto `CLAUDE.md` gets no mirror (it would write through); `teyla policy
  sync-repo` is what creates those links, and the rule text then reaches the other harnesses
  through `CLAUDE.md`, which Grok and Hermes read by that name too.
- **Tokens.** Cursor stores no per-message token counts (`tokenCount` is 0/0 on every turn
  inspected; `contextTokensUsed` is a context-window snapshot), so Cursor sessions carry
  model, turns, tools and corrections but no cost, like Grok. The monitor says "unknown" for
  their cost rather than guessing.
- **Kill switch and grants** (`teyla run`, the PreToolUse hook) stay Claude-only. Cursor
  and Hermes both have a blocking pre-tool hook (`preToolUse`, `pre_tool_call` with exit 2),
  so the control plane could be wired there later; it is not, and `teyla harness status`
  does not claim it.

## Verifying on a machine

```
teyla harness status          # present / policy / skills n/5 / hooks per harness
teyla doctor | grep harness   # the same as OK/FIX lines
teyla harness verify          # can each one work now: version, auth, last quota/auth error, 7-day volume
teyla harness verify --live   # plus one real line through each, headless (a few tokens; never from a routine)
```

"Wired" is not "working". On 2026-09-29 every line above said OK while every Grok call
answered 402 "Grok Build usage balance exhausted", Hermes had lost its xAI access token and
the `claude` CLI's OAuth session had expired (the desktop app signs in on its own).
`harness verify` reads what each harness itself recorded — Grok's
`logs/unified.jsonl`, Hermes's `auth.json` and `logs/errors.log`, Codex's `logs_2.sqlite`, rollout
errors and `rate_limits` (plan, 5-hour and weekly use), Claude's `isApiErrorMessage` records and
`claude auth status` — and prints the one command that fixes each. doctor carries the same as
`health:<harness>` lines.

Then, in each app, ask for something the skills cover ("run the adoption review", "make
that a rule: never use npm here") and check that `~/.teyla/hooks/capture-correction.sh`
wrote to `.teyla/corrections.jsonl` after a "no, not like that". Codex and Hermes each ask
once before a hook runs (see "Approval" above); `teyla harness status` shows whether they
have been approved. In Codex and Hermes, ask "what did the teyla line at the start say?" —
the model saw it if the orientation reached it.
