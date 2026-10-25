# Set up Teyla (a guide for an AI agent)

A person asked you to set up https://github.com/zaitsew/teyla. This file is for you. Developing Teyla
is a different job: see `CONTRIBUTING.md`.

**Goal:** a diagnosis summary in front of the person in under 3 minutes. Look things up yourself; ask
the person only for a yes on a change. Change nothing in their settings without that yes.

## What Teyla is

Teyla reads your Claude Code and Codex sessions on your Mac, shows what they cost and what's waiting
on you, and fixes the waste. It has no server and no account. Which calls leave the machine: `docs/PRIVACY.md`.

## Install

1. `uv --version`. If `uv` is missing, tell the person you are installing it, then run the official
   installer: `curl -LsSf https://astral.sh/uv/install.sh | sh`. If that cannot run, use
   `pipx install git+https://github.com/zaitsew/teyla` (Python 3.11+) and skip step 2.
2. `uv tool install git+https://github.com/zaitsew/teyla`
3. `teyla --version` prints a version. If `teyla` is not found: `uv tool update-shell`, then
   `~/.local/bin/teyla --version`.

To look before installing, run the diagnosis straight from the repo; nothing is installed or written:
`uvx --from git+https://github.com/zaitsew/teyla teyla start --agent`. Install properly before any
step that sets up a launchd job, because the job must name a `teyla` that stays on disk.

If a command needs the person's name, read `git config user.name`; if it is empty, ask once.
Never type a made-up name.

## Run the diagnosis

`teyla start --agent` reads local files only and writes nothing. It prints JSON with `summary_text`,
`diagnosis` and `offers`. A window other than the default 30 days: `--days N`.

1. Show `summary_text` to the person as it is. Do not rewrite the numbers.
2. If `diagnosis.empty` is true there are no sessions yet. Say so, then go to "What to say at the end".
3. For each offer with `applies: true`, ask one question about that one offer. Give its `title`, the
   saving (`saving_usd_month`, or `benefit` when there is no dollar figure), its `tradeoff` and its `undo`
   text word for word. Never put two offers in one question.
   Offers O1 to O4 change one setting each; `teyla undo <id>` reverses them. **O5, O6 and O7 run `policy sync`,
   `harness sync` and `routine install`. The undo command does not reverse these three.** Their `undo` text names
   the way back, usually `teyla uninstall`, which removes all of Teyla's links, hooks and jobs, not just
   this one. Say that in the question, before you ask for the yes.
4. Only after a yes: `teyla apply <id> --yes`. After a no, move on and do not ask again.
   To show a change first: `teyla apply <id> --dry`.
5. Report what changed: `teyla changes`.

## Never without the person's yes

Everything `teyla start --agent` does is read-only. These need a yes for each one, in your own question:

- any write to `~/.claude/settings.json` or `~/.codex/config.toml`
- hooks (`teyla plugin install`, `teyla harness sync`)
- launchd jobs (`teyla routine install`)
- the policy: `teyla policy init` and `teyla policy sync` write `~/.agents/POLICY.md` and wire it into every harness
- `teyla update`, and any command with `--force` or `--allow-network`

A change made through an offer is covered by the yes to that offer. Do not run these as a side effect of another yes.

## Undo

- `teyla changes` lists every change Teyla made and whether it is undone.
- `teyla undo <change-id>` or `teyla undo <offer-id>` (O1 to O4 only) puts back only the key Teyla wrote. If the key
  changed since, it stops and shows both values; `--force` reverts it anyway.
- Remove everything: `teyla uninstall --dry` shows each action, `teyla uninstall` unwires every harness
  (`--keep-data` keeps `~/.teyla`), then `uv tool uninstall teyla` (or `pipx uninstall teyla`).

## When something fails

Run `teyla doctor`. Each `FIX` line ends with its command. The common ones:

| You see | One-line fix |
|---|---|
| `teyla: command not found` | `uv tool update-shell`, then open a new shell |
| `UNREACHABLE` or a certificate error behind a company proxy | `uv tool install --force 'teyla[work] @ git+https://github.com/zaitsew/teyla'`; `docs/WORK.md` |
| `policy:file missing` | with a yes: `teyla policy init --owner "$(git config user.name)" && teyla policy sync` |
| `plugin` or `harness:<name>` not wired | with a yes: `teyla plugin install zaitsew/teyla`, `teyla harness sync` |
| `version`: a newer release exists | with a yes: `teyla update` |
| Codex ignores the hooks | Codex runs a new hook only after the person trusts it: they open `codex`, answer "Hooks need review" with "Trust all and continue", or type `/hooks`. `teyla harness status` then shows no `untrusted`. You cannot do this for them. |
| `routine:*` not installed | with a yes: `teyla routine install` |

Python below 3.11: `uv tool install --python 3.12 git+https://github.com/zaitsew/teyla`.

## What to say at the end

"Run `teyla` any time. `teyla today` is the daily screen."
