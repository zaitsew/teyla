# The same manner in every harness

Claude Code in the Claude desktop app has the whole loop: the policy imported by
`~/.claude/CLAUDE.md`, the plugin's skills (`harvest`, `adoption-review`, `wiki-pass`), the
two commands (`/teyla:rule`, `/teyla:correct`), and the hooks that show the doctor summary at
session start and capture corrections as they are typed. This page is what the other three
desktop-app harnesses get, how, and what each one cannot do. Every fact about a harness was
read from that harness's own files on one machine on 2026-09-14 (Cursor 3.19.7, Codex CLI
0.153.4 inside ChatGPT 26.908, Grok CLI 1.0.0, Hermes Agent 0.20.4); the file is named so
a newer version can be re-checked against it.

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
| **Codex** (ChatGPT app / CLI) | `~/.codex/AGENTS.md` → `POLICY.md` symlink | `AGENTS.md` per directory | `~/.codex/skills/teyla-*/SKILL.md` | none — `codex --help` has no hook events, only `notify` | `~/.codex/sessions/**/rollout-*.jsonl` |
| **Grok CLI** | `~/.grok/AGENTS.md` → `POLICY.md` symlink | `Agents.md`/`CLAUDE.md`/`AGENTS.md` per directory, repo root down to cwd (`12-project-rules.md`) | `~/.grok/skills/teyla-*/SKILL.md`; also scans `~/.claude/skills`, `~/.cursor/skills`, `.agents/skills` (`08-skills.md`) | `~/.grok/hooks/teyla.json`: `SessionStart`, `UserPromptSubmit`; it also loads `~/.cursor/hooks.json` and `~/.claude/settings.json` (`10-hooks.md`), so the capture hook de-duplicates | `~/.grok/sessions/<cwd>/<id>/` |
| **Hermes** (app / CLI) | an "Operating policy" section in `~/.hermes/SOUL.md` | `AGENTS.md` chain from the git root (`context-files.md`; `.hermes.md` → `AGENTS.md` → `CLAUDE.md` → `.cursorrules`, first match) | `~/.hermes/skills/teyla/teyla-*/SKILL.md`, each also a slash command (`skills.md`) | a `hooks:` block in `~/.hermes/config.yaml`: `on_session_start`, `pre_llm_call` shell hooks; Hermes asks once per hook before running it (`hooks.md`, "Shell hooks") | `~/.hermes/state.db` |

The skills are rendered from the plugin's own `SKILL.md` files with `/teyla:rule` and
`/teyla:correct` replaced by the CLI — `teyla rule "<sentence>" --scope <glob>` and
`teyla correct "<what was wrong>"` do the same two file writes the Claude commands do — and
each copy says which source it was generated from. Edit the source; the next sync overwrites
the copy. The hook scripts are one copy each in `~/.teyla/hooks/`, the plugin's own two
scripts, which read every harness's stdin shape.

## What is not the same, and why

- **Session-start orientation.** Claude Code injects the hook's stdout into the model's
  context; that is where "teyla: 2 warning(s)" and the product's routine line come from. Grok
  ignores `SessionStart` stdout (`10-hooks.md`: "stdout is ignored"); Cursor's docs do not say
  what `sessionStart` output does; Hermes's `on_session_start` return is ignored. In those
  three the session-start hook still runs — it starts the background update check and
  `teyla routine catch-up` — but the model does not see the line. `teyla doctor` is the
  command to run by hand there.
- **Correction capture** works in all four (Cursor `beforeSubmitPrompt`, Grok
  `UserPromptSubmit`, Hermes `pre_llm_call` with `extra.user_message`). Codex has no hook, so
  in Codex a correction is recorded only when the skill `teyla-correct` is invoked.
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
```

Then, in each app, ask for something the skills cover ("run the adoption review", "make
that a rule: never use npm here") and check that `~/.teyla/hooks/capture-correction.sh`
wrote to `.teyla/corrections.jsonl` after a "no, not like that". Hermes prompts once for
each hook the first time it fires.
