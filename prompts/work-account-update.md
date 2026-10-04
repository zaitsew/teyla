# Teyla on the work MacBook — bring it to 0.16.0, in safe mode

Paste this whole file into Claude Code on the machine to update. It was written for a
managed corporate laptop: Claude Code as the desktop app (there may be no `claude` binary
on PATH), no `gh`, `codex` or `grok`, a Zscaler TLS-inspecting proxy, pushes to GitLab rather
than GitHub, Python 3.12 pinned, and Teyla installed once from https://github.com/zaitsew/teyla
at some older version. Absent tools are a different scope, not a broken install — `teyla
doctor` reports them as INFO, never as failures.

Target: **v0.16.0**, the newest published release when this was written. Everything below is
verified against that version's `--help`; do not use a flag that is not in it.

Links: repo https://github.com/zaitsew/teyla · README https://github.com/zaitsew/teyla#readme ·
the original kickoff: https://github.com/zaitsew/teyla/blob/main/prompts/work-account-kickoff.md ·
releases: https://github.com/zaitsew/teyla/releases · every practice and what to adapt:
https://github.com/zaitsew/teyla/blob/main/docs/HANDOVER.md

---

You are updating an existing Teyla install on this machine to 0.16.0 and putting it in safe
mode, so that from now on it does nothing on its own that touches the network. Do every step,
verify each with a command, and report at the end in the format given. Do not ask me whether
to proceed; stop only at a real blocker.

Three rules for the whole run:

- **Nothing leaves this machine.** Do not send, upload, email, paste or open an issue with
  anything Teyla prints or writes. The one file that crosses the boundary (step 10) is mine to
  read first and mine to carry.
- **Network only where a step says so.** Two steps reach GitHub, both typed by hand: the install
  in step 2 and `teyla update --allow-network` in step 6. Do not add `--allow-network` anywhere
  else, and do not run `teyla doctor --refresh`.
- **Never edit the Claude Code plugin registry files by hand,** and never `rm` anything under
  `~/.claude`, `~/.teyla` or `~/.agents`. `teyla uninstall` (step 4) is only ever run with `--dry`.

## 1. Find out how Teyla was installed here

```
which teyla; teyla --version
uv tool list 2>/dev/null | grep -i teyla
pipx list 2>/dev/null | grep -i teyla
python3 -c "import teyla, os; print(os.path.dirname(teyla.__file__))"
command -v claude gh codex grok
```

The path tells you the method: `.../uv/tools/teyla/...` → uv tool; `.../pipx/venvs/teyla/...`
→ pipx; a directory with `.git` and `pyproject.toml` two levels up → git checkout; anything
else → pip. `teyla --version` prints the bare version number (for example `0.16.0`). Write
down the old version, the method, and which of `claude`, `gh`, `codex`, `grok` exist.

## 2. Bootstrap to 0.16.0 by hand (only if the version above is older, or `teyla` is missing)

The safe-mode and uninstall commands used below first shipped in 0.13.0, so an older install
cannot run them and has to be moved by hand once, with the method you found. Pin Python 3.12
(3.13's strict X.509 check rejects the Zscaler root CA) and install the `work` extra, which
makes Python trust the macOS keychain:

```
uv tool install --force --python 3.12 "teyla[work] @ git+https://github.com/zaitsew/teyla@v0.16.0"      # uv tool
pipx install --force --python python3.12 "teyla[work] @ git+https://github.com/zaitsew/teyla@v0.16.0"   # pipx
python3.12 -m pip install --user --upgrade "teyla[work] @ git+https://github.com/zaitsew/teyla@v0.16.0" # pip
git -C <checkout> fetch --tags origin && git -C <checkout> checkout --detach v0.16.0 \
  && python3.12 -m pip install -e "<checkout>[work]"                                                      # checkout
```

`teyla --version` must print `0.16.0` before you continue. If it already did, skip this step.

If GitHub is not reachable from this machine, or the install fails on TLS (`certificate
verify failed`, a proxy error), that is a blocker only I can resolve (the proxy, the root CA
bundle, or a mirror). Say exactly what failed and stop; nothing below depends on guessing a
certificate path.

## 3. Safe mode and the work policy

Before changing anything, keep what is there:

```
teyla config show
teyla policy status
cp ~/.agents/POLICY.md ~/.agents/POLICY.md.pre-0.13 2>/dev/null
```

Then, passing the roots that `teyla config show` printed (`code_root`, `ops_root`) so they are
kept, and `--owner` with my name from `git config user.name`:

```
teyla policy init --work --owner "<name>" --code-root "<code_root>" --ops-root "<ops_root>"
```

This writes `~/.agents/POLICY.md` from the work template (approved providers only, a fresh
same-provider session for second opinions, no merge without me), records it as the merge base,
creates `~/.teyla/config.toml` if absent, and sets `safe.enabled = true`. It never touches
`~/.claude/CLAUDE.md` (that needs `--claude-md`, which I did not ask for). It exits 1 and says
what is left undone if safe mode or the work policy did not both take.

- It prints `exists: ~/.agents/POLICY.md (from the home template: it sends diffs to other
  providers)` and exits 1: this machine still has the home policy. Run the same command again
  with `--force`. That replaces the file and keeps a dated `POLICY.md.bak-<date>`; if the old
  file had edits of mine that the template lacks, list them in the report instead of
  re-adding them.
- It prints `exists:` and exits 0: the file is already the work policy; leave it.

Safe mode means: no network unless the typed command says `--allow-network`; no self-update
from the daily routine or the session hook; `./check.sh` runs only in repos listed under
`products.repos`; plugin changes are printed as `/plugin ...` commands for me to type instead
of edited into the registry; no keychain query; `teyla run`, triggers and agent steps are
refused; a config that cannot be parsed turns safe mode on rather than off.

Then freeze the update to this release and the interpreter to 3.12:

```
teyla config set update.pin=0.16.0 update.python=3.12
teyla doctor | head -6
```

Doctor's second line must read `INFO safe  on (network off, no auto-update, no repo commands)`
and the `update` line `pinned to 0.16.0`. A `FIX safe:setting` line means the config does not
parse or holds a non-boolean: run the command it prints.

If a proxy setting is needed and the install in step 2 did not already cover it (an `[env]`
entry such as `SSL_CERT_FILE`), `teyla config set env.SSL_CERT_FILE=<path>` writes it into the
config, the plists and the wrappers. Only set a path you have verified exists; if you do not
know where the corporate CA bundle is, that is a blocker for me, not a guess.

## 4. The list of everything Teyla owns here

```
teyla uninstall --dry
```

Touches nothing; prints, one line each, every file, LaunchAgent and symlink Teyla wrote on this
machine, which it would remove, and which it keeps because they are mine (`~/.agents/POLICY.md`,
repo rules, an ops root). It is the authoritative list: paste it, unedited, into the report.
Never run `teyla uninstall` without `--dry`.

## 5. Read what the installed version says about itself

```
teyla prompt onboard
```

This is the onboarding prompt shipped with 0.16.0. Read its "Corporate notes": the table of
what touches the network and the table of every file Teyla writes, with the undo for each. Do
not re-run its install steps 1–5, and above all not its `teyla policy init --owner` line
without `--work`: you already did the right version in step 3. Where its table says the daily
LaunchAgent or the session hook runs `teyla update`, that is true outside safe mode only; here
neither does. Report in three lines what can still touch the network on this machine (only a
command typed by hand with `--allow-network`: `teyla update`, `teyla models --refresh`,
`teyla routines`, `teyla spend`, `teyla platform`; plus the `/plugin` commands I type in Claude Code) and what
cannot.

## 6. Update to the pinned version and wire everything

```
teyla update --check --allow-network
teyla update --allow-network --wire
```

In safe mode `teyla update` refuses without `--allow-network`, even by hand, and prints the
refusal; that is the gate working. With the pin set the target is exactly 0.16.0: an install
that is already 0.16.0 reports `is the pinned release` and `--wire` runs the post-update steps
anyway; a different version is reinstalled from the release's commit and verified, and rolled
back if the build reports the wrong version. The post-update steps run in this order and each
prints what it did: `policy sync` (the import line and symlinks for harnesses that exist here),
`policy refresh` (in safe mode it only proposes a merge into `~/.teyla/policy-proposed.md` and
leaves `POLICY.md` alone: if it says so, read the proposal, show me the diff, do not apply it),
`plugin refresh` (in safe mode: prints the `/plugin ...` commands, edits nothing),
`harness sync` (skills and hooks for Cursor, Codex, Grok and Hermes, only those present),
`routine install --if-stale` (rewrites the daily and weekly LaunchAgents without the update
line), then `doctor`.

If GitHub cannot be reached, fix nothing by guessing: take the TLS hint the command prints,
report it, and run the five offline steps by hand instead, which need no network:

```
teyla policy sync && teyla policy refresh && teyla plugin refresh && teyla harness sync && teyla routine install --if-stale
```

If launchd agents are blocked on this machine (MDM), `routine install` says so. That is fine in
safe mode: the plugin's session-start hook runs doctor itself. `teyla routine install --dry`
lists what it would write and load without touching launchd. Say which of the two paths is
the active one here.

To move to a newer release later, I run `teyla config set update.pin=<version>` followed by
`teyla update --allow-network --wire`; do not change the pin yourself.

## 7. The plugin, which safe mode leaves to me

If `teyla doctor` still shows `FIX plugin`, or step 6 printed `/plugin ...` lines, copy those
lines verbatim into the report as "for me to type in a Claude Code session":

```
/plugin marketplace add zaitsew/teyla#v0.16.0
/plugin install teyla@teyla
```

The `#v0.16.0` pins the hooks to the same release as the CLI; without it they follow main. If
a teyla plugin from an unpinned marketplace is already installed (`teyla doctor` warns
`plugin:pin`), put `/plugin marketplace remove teyla` first in that list.

Do not run `teyla plugin install`, which in safe mode only reprints them, and do not edit
`~/.claude/plugins/*.json`. If the organisation restricts plugin marketplaces, my typing them
may be refused; say so when I report back.

## 8. Doctor must be clean

```
teyla doctor
```

Every `FIX` line names the command that repairs it; run it and re-run doctor until no FIX
remains, with these exceptions that are mine to resolve and not failures of the install:
`FIX plugin` (step 7), and any `FIX` about a harness sign-in that needs me to log in. `WARN`
lines are for me to see. `INFO` lines about absent codex, grok and gh, the same-provider
second-opinion fallback, and `network ... not probed (safe mode)` are expected on this machine.
Paste the full output.

Then confirm the routines and the hook:

```
teyla routine status
launchctl list | grep zaitsew.teyla
cat ~/.teyla/doctor.summary
```

Start a new Claude Code session in any repo and confirm the first line it prints is either the
rule count, the doctor summary, or nothing (when all is clear). Report which.

## 9. The personal Mac's habits: context budget, land check, review

Three practices from my personal Mac ship in the 0.16.0 plugin. The two hooks are off by default;
turn them on here:

```
teyla config set hooks.context_budget=true hooks.land_check=true
teyla config set hooks.context_budget_first=240000 hooks.context_budget_step=30000
teyla doctor | grep 'hooks:'
```

Doctor must print `INFO hooks:context-budget` and `INFO hooks:land-check`, and until the next part
also `WARN hooks:autocompact`. The context budget asks the model for a handoff at 240k tokens of
context (0.16.0's defaults are 300k/40k, hence the second line); Claude Code compacts at about
300k, early enough, only when `~/.claude/settings.json` has `"autoCompactWindow": 335000`. Doctor never writes that file; you add the one key. Back the file
up first, then merge the key in and keep every other key as it is:

```
cp -p ~/.claude/settings.json ~/.claude/settings.json.bak-$(date +%F) 2>/dev/null
python3.12 - <<'PY'
import json, os, pathlib
p = pathlib.Path.home() / ".claude" / "settings.json"
d = json.loads(p.read_text()) if p.exists() else {}
if not isinstance(d, dict):
    raise SystemExit(f"{p} is not a JSON object; not touched")
if "autoCompactWindow" in d:
    print(f"autoCompactWindow already {d['autoCompactWindow']}; left as is")
else:
    d["autoCompactWindow"] = 335000
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2) + "\n")
    os.replace(tmp, p)
    print(f"added autoCompactWindow 335000 to {p}")
PY
teyla doctor | grep 'hooks:'
```

If `settings.json` does not parse, the script stops with a traceback and changes nothing: report
it, do not rewrite the file. If the key already had another value, leave it and report the value.
After this, `hooks:autocompact` must be gone. (`/config` in Claude Code sets the same key.)

The land check tells the model, once per session, when work is uncommitted or on no remote, and
says "open the MR and STOP" for every repo that is not in a `MERGE-APPROVED REPOS` block of
`~/.claude/CLAUDE.md`. Do not add such a block or any repo to one: that list is mine to write.

Last, the review skill. Start a new Claude Code session (hooks and skills load at session start),
type `/teyla:` and check that `teyla:review` is in the list; or:

```
ls ~/.claude/plugins/cache/teyla/teyla/*/skills/
```

must show `review` beside `harvest`, `adoption-review` and `wiki-pass`. If it is missing, the
plugin is older than 0.16.0: that is step 7's `/plugin` lines, for me to type. From now on, run
`/teyla:review` on a branch before asking me to merge its MR.

## 10. A feedback round, for me to review

```
teyla feedback --days 14 --out ~/Downloads/teyla-feedback-$(date +%F).md
```

It reads only local logs and writes one markdown file at the path you gave. It contains the
Teyla version, Python and OS, the doctor checklist (the proxy, CA bundle, roots, reminders and
repo names are withheld), the policy wiring status, an adoption report for the last 14 days with
projects renamed p01, p02, connectors c01, c02 and private skills s01, s02, and no session ids,
no prompt or correction text, no file paths (the home directory is shown as `~`). It ends with
five questions.

Do three things, and nothing else:

1. Open the file and look for anything that identifies this machine, the company, a person, a
   ticket or a document (a hostname, a name, a path outside `~`, a project name). If you find
   any, delete that text from the file and say what kind it was, in words and without quoting it.
2. Answer the five questions at the end, briefly, from this run only: what failed, which
   command or flag you needed that did not exist, what Teyla could not read here. Counts, tool
   and command names only.
3. Tell me where the file is. **Do not send it anywhere**: no chat, email, upload or GitHub
   issue. I read it and carry it over myself.

## 11. Report

```
machine: <what is present: claude binary yes/no, launchd yes/no, gh/codex/grok yes/no>
install: <method> <old version> → <new version>
safe mode: <teyla doctor's safe and update lines; policy init exit code and whether --force was needed>
policy: <work template written | already work; POLICY.md.pre-0.13 kept; local edits not carried over>
uninstall --dry: <the full output, unedited>
update: <the lines `teyla update --allow-network --wire` printed, or the offline fallback and why>
doctor: <FIX count> <WARN count>; <paste>
plugin: <installed | for me to type: the /plugin lines>
update path: manual (safe mode: teyla update --allow-network, by me) · daily routine: launchd | none
hooks: context_budget <on|off>, land_check <on|off>; autoCompactWindow <added | already N | not set: why>; settings backup <path>; /teyla:review listed <yes|no>
feedback file: <path>; reviewed for identifying text: <yes, nothing found | removed N items of: kinds>
blockers: <none | what only I can do, with the exact step>
```
