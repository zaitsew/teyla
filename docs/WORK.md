# Teyla on a work laptop

For a managed Mac: a TLS-inspecting corporate proxy, the employer's code in every transcript, no say over
what runs at night. Teyla has one switch for this, **safe mode**. This page says what it
guarantees, how to move to a new release, and what to use day to day.

Setup from scratch is in the [README](../README.md#install). The step-by-step version for an
agent is [`prompts/work-account-update.md`](../prompts/work-account-update.md).

## What safe mode guarantees

`teyla policy init --work` turns it on (`teyla config set safe.enabled=true` does the same).
`teyla doctor` prints `safe: on` as its first line.

- **No network** unless the command you typed carries `--allow-network`. The session hook and the daily routine never pass it.
- **No self-update.** The CLI changes only when you set `update.pin` and run `teyla update --allow-network --wire`.
- **The plugin is pinned too.** With `update.pin` set to a release, you add the plugin from the same tag (`zaitsew/teyla#v<pin>`), so its hooks are never newer than the CLI. `teyla doctor` warns (`plugin:pin`) when they are.
- **No repo code runs** except `./check.sh` in the repos you list under `products.repos`. `teyla run`, triggers and agent steps are refused.
- **No hand-edited Claude Code registry.** Plugin changes are printed as `/plugin ...` commands for you to type.
- **Nothing leaves the machine.** No telemetry, no keychain query. `teyla feedback` writes one local file that you read and carry yourself.

A config file that does not parse turns safe mode on, never off.

## Update to a new release

Do this when you choose to, not when a tag appears. Replace `0.18.0` with the release you want.

1. Set the pin: `teyla config set update.pin=0.18.0`
2. Update the CLI and run the post-update steps: `teyla update --allow-network --wire`
3. Re-pin the plugin, by typing these in a Claude Code session (the first line only if the plugin is already installed from an unpinned marketplace):

   ```
   /plugin marketplace remove teyla
   /plugin marketplace add zaitsew/teyla#v0.18.0
   /plugin install teyla@teyla
   ```

   The `#v0.18.0` is what ties the hooks to that release. Without it they follow `main`.
4. Check: `teyla doctor`. No `FIX` line. No `plugin:pin` warning.
5. Start a new Claude Code session in any repo. The first line it prints is the rule count, or the doctor summary (problems first, then free disk space, for example `disk 64 GB free`).

If your organisation restricts plugin marketplaces, step 3 may be refused. Say so; do not edit `~/.claude/plugins/*.json`.

## Daily use

| Command | What it answers |
|---|---|
| `teyla doctor` | Is everything that has to be true, true? Every `FIX` line names its repair. |
| `teyla digest` | What is new since last time, and the three things worth doing this week. |
| `teyla monitor --days 7` | How did I use AI this week: sessions, tokens, waste, by project. |
| `teyla advise` | What should I change, given those numbers. Each item has a number behind it and one action. |
| `/teyla:correct <what was wrong>` | Record a correction. It is scrubbed and stored outside the repo. |
| `/teyla:rule <sentence>` | Append a one-sentence rule to `.claude/rules/` in this repo. |
| `/teyla:review` | One P1/P2-only review of this branch's diff before you ask for a merge. |
| `teyla rules propose` | Which corrections came back often enough to become a rule. Writes nothing without `--write`. |
| `teyla rules stale` | Which rules expired or were never hit: candidates to remove. |
| `teyla wiki status <path>` | Is this wiki folder in order. |
| `teyla sessions` | What sessions ran, and how they went. |
| `teyla feedback --days 14` | A report of how Teyla behaved here, for the maintainer. It stays on the machine: you read it, then carry it. |

In an employer's repo, a rule file is a change to their repo. It goes through a normal merge
request like any other change. Teyla never pushes it for you.

## Optional hooks

Three practices that are often run from personal scripts ship in the plugin too, so they
arrive pinned with it. The two hooks are off by default (a machine that already runs its own
copies would get every note twice); turn them on here:

```
teyla config set hooks.context_budget=true hooks.land_check=true
```

- **Context budget.** At 240k tokens of context, and every 30k after, the model is asked to write
  a handoff (state, open work, decisions, next steps, file paths) to `~/.teyla/handoff/` and keep
  going; after Claude Code compacts the session, the handoff is put back once. It needs
  `"autoCompactWindow": 335000` in `~/.claude/settings.json` (set it with `/config`, or add the
  key to the file, keeping the rest), which compacts at about 300k: without it Claude Code compacts
  only near the model's full window. `teyla doctor` warns when the key is missing; it never edits the file. The thresholds
  are `hooks.context_budget_first` and `hooks.context_budget_step`.
- **Land check.** When a session stops with uncommitted files or commits on no remote, the model
  is told once, with how to land it: one MR per logical unit, then **stop** — unless the repo is in the
  `MERGE-APPROVED REPOS` block of `~/.claude/CLAUDE.md` — as `owner/repo` for GitHub, and with its
  host for anything else (`git.example.com/group/sub/repo`). On a work laptop that block is usually absent, so every MR waits for you.
- **`/teyla:review`** before asking for a merge: one P1/P2-only pass on the branch's diff, by one
  fresh sub-agent (labelled "same-provider review", since there is no second provider's CLI
  here), at most two rounds.

All three are offline; safe mode allows them. `teyla doctor` prints one INFO line per hook that is on.

## What never happens in safe mode

- No request to GitHub, models.dev, or any other host, unless you typed `--allow-network`.
- No update of the CLI or the plugin by a routine, a hook, or a session.
- No `teyla run`, no trigger, no agent step.
- No write to `~/.claude/plugins/*.json`, and no `rm` under `~/.claude`, `~/.teyla` or `~/.agents`.
- No merge into `~/.agents/POLICY.md` by itself: a newer template is proposed in `~/.teyla/policy-proposed.md`, and you apply it.
- No data sent anywhere. `teyla uninstall --dry` lists every file Teyla owns here.

To allow the network for one command, add `--allow-network` to that command:

```
teyla update --check --allow-network
```

It lasts for that process only. To turn safe mode off altogether, which a managed laptop should
not need: `teyla config set safe.enabled=false`.
