# Onboard Teyla on a new machine

Paste this whole file to an AI agent (Claude Code, Codex or Grok) on the target machine and
say: **"Set up Teyla from https://github.com/zaitsew/teyla."**

## What to do

1. **Install**, stopping at the first that works:
   - `uv tool install git+https://github.com/zaitsew/teyla`
   - `pipx install git+https://github.com/zaitsew/teyla`
   - `git clone https://github.com/zaitsew/teyla ~/repos/teyla && cd ~/repos/teyla`, then use
     `PYTHONPATH=src python3 -m teyla <cmd>` instead of `teyla` below.
2. Run `teyla doctor` (reads local logs, and asks `api.github.com` whether a newer release
   exists — the network table below lists every call). Report what it finds; "absent" just
   means that harness isn't installed here.
3. `teyla policy init --owner "<name>"`, then `teyla policy sync` — writes `~/.agents/POLICY.md`
   and wires it into every harness doctor found.
4. **Edit `~/.agents/POLICY.md` for this org**: which model providers exist, and which model is
   each provider's top (orchestrating) tier. Ask rather than guess.
5. Install the Claude Code plugin:
   `claude plugin marketplace add zaitsew/teyla && claude plugin install teyla@teyla`.
   If the marketplace add fails, clone the repo and add the local path instead:
   `claude plugin marketplace add ~/repos/teyla`.
   **No `claude` on PATH at all** (Claude runs only as the desktop app — check with
   `command -v claude` first): both commands above are unavailable, and so is the documented
   fallback, since it needs the same missing binary. Run `teyla plugin install zaitsew/teyla`
   instead — it clones the marketplace, copies the plugin into the cache path, and writes the
   registry entries `claude plugin install` would have written, by hand but safely (backs up
   both registry files first, and `teyla plugin uninstall teyla` reverses it).
   **Codex has no CLI either** on a machine like this — `codex` lives inside the ChatGPT
   desktop app and is not on PATH — so `codex exec` fan-outs and `codex review` are
   unavailable even though the credential and session history exist. There is no install
   step to substitute here; treat Codex as a harness `teyla doctor` can still read logs from,
   not one you can drive. The cross-provider review practice's no-CLI fallback (§2 of
   `templates/POLICY.md`) is a same-provider review, not a Codex one, on such a machine.
6. `teyla monitor --days 30`. Read the advice. Apply only pure file edits in this workspace (a
   rule file, a `model:` override); leave anything needing a human decision.
7. `teyla feedback`. Hand the resulting `teyla-feedback-<date>.md` to the human — the whole
   feedback loop on a machine that can't push to GitHub.
8. Tell the human how to take it all back: `teyla uninstall --dry` lists every file Teyla
   wrote on this machine, `teyla uninstall` reverses it.

## Corporate notes — what touches the network, what is written, how to undo it

Teyla sends no telemetry and uploads nothing: no report, transcript, path or name leaves the
machine unless you carry a file out yourself (`teyla monitor --share`, `teyla feedback` —
both redacted). It does make the outbound calls below, and nothing else does.

**What touches the network:**

| what | when it runs | contacts |
|---|---|---|
| `teyla update` | by hand; **the daily LaunchAgent at 07:00**, or at the next session start after a run the Mac missed | `api.github.com` (latest release / tags); on a newer release it **installs it by itself** (`uv`/`pipx`/`git` → `github.com`), then re-wires: `policy sync`, `policy refresh`, `plugin refresh`, `harness sync`, `routine install` — and that last step installs the daily and weekly LaunchAgents if they are missing |
| `teyla update --check` | by hand; the plugin's session-start hook, in the background, at most once a day | `api.github.com`, read-only |
| `teyla doctor`, `teyla feedback` (includes a doctor pass) | by hand; the daily job; the session-start hook | `api.github.com`, only when the cached check in `~/.teyla/update-check.json` is older than 24 h (15 min after a failure); `doctor --refresh` forces it |
| `teyla plugin install owner/repo`, `claude plugin marketplace add` | by hand | `github.com` (git clone / pull) |
| `teyla routines` | by hand; the daily job | `gh run list` for GitHub-Actions routines, only if `gh` is installed and logged in; `--issues` opens GitHub issues through `gh` |
| `teyla models --refresh`, `--write-prices` | by hand | `models.dev` |
| `teyla platform` (without `--no-net`) | by hand | ssh to the configured server, a DNS lookup, `supabase projects list` |
| `teyla run <product:routine>` | by hand, or a `teyla triggers` LaunchAgent | whatever that routine's steps run |

Everything else — `monitor`, `advise`, `sessions`, `corrections`, `connectors`, `harvest`,
`policy`, `harness`, `rule`, `correct`, `wiki`, `storage`, `uninstall` — reads and writes local
files only. To keep Teyla off the network entirely, do not install the routines (and if an
update installed them: `teyla uninstall --keep-data` removes them and keeps your data); the
session-start hook's once-a-day `update --check` goes with the plugin.

**Every file Teyla writes, and the undo.** `teyla uninstall --dry` lists exactly what is on
*this* machine, path by path; `teyla uninstall` reverses it (idempotent, touches only what
carries Teyla's marker, label or symlink target; `--keep-data` keeps `~/.teyla`).

| file | written by | undone by `teyla uninstall` |
|---|---|---|
| `~/Library/LaunchAgents/com.zaitsew.teyla.{daily,weekly}.plist`, `~/.teyla/{daily,weekly}.sh`, `~/Library/Logs/teyla-{daily,weekly}.log` | `teyla routine install`, and `teyla update`'s post-steps when missing | unloaded and removed |
| `~/Library/LaunchAgents/com.teyla.<product>.<routine>.plist` + its log | `teyla triggers install` | unloaded and removed |
| `~/.claude/CLAUDE.md`: one `@~/.agents/POLICY.md` import line | `policy sync` | the line is removed (backup `CLAUDE.md.bak-<date>`); a file `policy init --claude-md` wrote is yours and stays |
| `~/.codex/AGENTS.md`, `~/.grok/AGENTS.md` (symlinks → POLICY.md) | `policy sync` | removed, only if they point at POLICY.md |
| `~/.hermes/SOUL.md`: the `## Operating policy` section | `policy sync` | removed if unedited; an edited one is reported |
| `~/.hermes/config.yaml`: the `# teyla-hooks begin … end` block | `harness sync` | block removed |
| `~/.cursor/skills/teyla-policy/` | `policy sync` | removed |
| `~/.cursor/skills/teyla-*`, `~/.codex/skills/teyla-*`, `~/.grok/skills/teyla-*`, `~/.hermes/skills/teyla/` | `harness sync` | removed (only files with the generated-by marker) |
| `~/.cursor/hooks.json` (two entries), `~/.grok/hooks/teyla.json`, `~/.teyla/hooks/` | `harness sync` | Teyla's entries and files removed; your hooks stay |
| `~/.claude/plugins/`: the `teyla@…` row in `installed_plugins.json`, `cache/<marketplace>/teyla/`, the `teyla` entry in `known_marketplaces.json`, a `marketplaces/teyla` clone; `*.bak-<date>` registry backups | `claude plugin install` or `teyla plugin install`; `plugin refresh` (daily) | via `claude plugin uninstall` when `claude` exists, else the rows and cache copy; backups and a directory-source checkout are kept |
| `~/.teyla/` — config, update and doctor caches, reminders, acks, prices, the policy merge base, routines one-liners, storage log, control plane (signing key, inbox, receipts, kill switch) | most commands | removed (`--keep-data` keeps it, minus hooks and wrappers) |
| `~/.agents/POLICY.md` (+ `.bak-<date>` from `policy refresh`) | `policy init`, `policy refresh`, `models --write-policy` | **kept** — yours; `rm ~/.agents/POLICY.md` |
| `~/.teyla/corrections/<repo>-<hash>.jsonl` (0600, secrets scrubbed) | `/teyla:correct`, `teyla correct`, the capture hook | removed with `~/.teyla` (`--keep-data` keeps it) |
| a `.teyla/` line in `<repo>/.git/info/exclude`; an older `<repo>/.teyla/corrections.jsonl` | the same, in repos that had a `.teyla/` | **kept**, listed for repos under code_root and ops_root; others: `find ~ -maxdepth 4 -type d -name .teyla` |
| `<repo>/.claude/rules/*.md`, an AGENTS.md `## Rules` section, `.cursor/rules/*.mdc` | `teyla rule` | **kept**, listed — the repo's rules |
| `<repo>/AGENTS.md` ⇄ `CLAUDE.md` links (+ `.bak`) | `policy sync-repo` | kept — repo content |
| the ops root (`CLAUDE.md`, `.claude/`, `runs/`, `.gitignore`), `~/ops/startup/os/ai-dev/runs/<date>/` | `policy init --ops-root-init`, the weekly job | kept; the weekly reports are listed |
| files you name: `--out`, `teyla-feedback-<date>.md`, wiki pages | `monitor`, `feedback`, `harvest`, `wiki` | yours |

Last step, which uninstall prints: `uv tool uninstall teyla` (or `pipx uninstall teyla`).

If any step needs a login, a key, or a payment (SSO for `gh`, a plugin marketplace that needs
auth), stop there, name the exact command and file, and hand it back to the human — everything
else in this list should complete unattended.
