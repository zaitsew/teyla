# Onboard Teyla on a new machine

Paste this whole file to an AI agent (Claude Code, Codex or Grok) on the target machine and
say: **"Set up Teyla from https://github.com/zaitsew/teyla."**

## What to do

1. **Install**, stopping at the first that works:
   - `uv tool install git+https://github.com/zaitsew/teyla`
   - `pipx install git+https://github.com/zaitsew/teyla`
   - `git clone https://github.com/zaitsew/teyla ~/repos/teyla && cd ~/repos/teyla`, then use
     `PYTHONPATH=src python3 -m teyla <cmd>` instead of `teyla` below.
2. Run `teyla doctor` (reads local logs only). Report what it finds; "absent" just means that
   harness isn't installed here.
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

## Corporate notes — nothing leaves this machine

Every Teyla command reads local files and writes local files. No network call is made except
the install step (cloning/downloading the package itself) and, if used, `claude plugin
marketplace add`. `teyla monitor`, `doctor`, `feedback`, `routines` and `policy` never send
data anywhere.

**Files Teyla writes, and how to undo each:**

| file | written by | to undo |
|---|---|---|
| `~/.agents/POLICY.md` | `policy init` | `rm ~/.agents/POLICY.md` |
| `~/.claude/CLAUDE.md` (one import line appended) | `policy sync` | delete the `@~/.agents/POLICY.md` line |
| `~/.codex/AGENTS.md` (symlink) | `policy sync` | `rm ~/.codex/AGENTS.md` |
| `~/.grok/AGENTS.md` (symlink) | `policy sync` | `rm ~/.grok/AGENTS.md` |
| `~/.hermes/SOUL.md` (section appended) | `policy sync` | delete the `## Operating policy` section |
| `<repo>/.teyla/corrections.jsonl` | the `/teyla:correct` plugin command, per repo | `rm -rf <repo>/.teyla` |
| `~/.teyla/weekly.sh` + a LaunchAgent | `teyla routine install` (only if run) | `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.zaitsew.teyla.weekly.plist && rm ~/Library/LaunchAgents/com.zaitsew.teyla.weekly.plist ~/.teyla/weekly.sh` |

`teyla monitor --share`, `teyla feedback`, and `teyla harvest` all write only to a file you
name or the current directory — never to a fixed system path.

If any step needs a login, a key, or a payment (SSO for `gh`, a plugin marketplace that needs
auth), stop there, name the exact command and file, and hand it back to the human — everything
else in this list should complete unattended.
