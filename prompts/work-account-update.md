# Teyla on a second machine — update to 0.7.0+ and switch on auto-updates

Paste this whole file into Claude Code on the machine to update. It was written for a
managed corporate laptop: Claude Code as the desktop app (there may be no `claude` binary
on PATH), no `gh`, `codex` or `grok`, pushes go to GitLab rather than GitHub, and Teyla
was installed once from https://github.com/zaitsew/teyla. Absent tools are a different
scope, not a broken install — `teyla doctor` reports them as INFO, never as failures.

Links: repo https://github.com/zaitsew/teyla · README https://github.com/zaitsew/teyla#readme ·
what keeps itself current: https://github.com/zaitsew/teyla/blob/main/docs/MANUAL.md (§4b) ·
the original kickoff: https://github.com/zaitsew/teyla/blob/main/prompts/work-account-kickoff.md ·
releases: https://github.com/zaitsew/teyla/releases

---

You are updating an existing Teyla install on this machine and switching on its
self-maintenance. Do every step, verify each with a command, and report at the end in the
format given. Do not ask me whether to proceed; stop only at a real blocker.

## 1. Find out how Teyla was installed here

```
which teyla; teyla --version
uv tool list 2>/dev/null | grep -i teyla
pipx list 2>/dev/null | grep -i teyla
python3 -c "import teyla, os; print(os.path.dirname(teyla.__file__))"
```

The path tells you the method: `.../uv/tools/teyla/...` → uv tool; `.../pipx/venvs/teyla/...`
→ pipx; a directory with `.git` and `pyproject.toml` two levels up → git checkout; anything
else → pip.

## 2. One-time bootstrap to 0.7.0 (this is the only manual upgrade, ever)

Versions before 0.7.0 have no `update` command, so this one step is by hand, with the same
method you found:

```
uv tool install --force git+https://github.com/zaitsew/teyla@v0.7.0        # uv tool
pipx install --force git+https://github.com/zaitsew/teyla@v0.7.0           # pipx
python3 -m pip install --user --upgrade git+https://github.com/zaitsew/teyla@v0.7.0   # pip
git -C <checkout> pull --ff-only && python3 -m pip install -e <checkout>   # checkout
```

If GitHub is not reachable from this machine over git, say so — that is a blocker only I can
resolve (a proxy or a mirror), and nothing below depends on you guessing.

`teyla --version` must print 0.7.0 or newer before you continue.

## 3. Wire everything the new version maintains

```
teyla update --wire
```

This runs, in order, and prints each: `policy sync` (import line, symlinks for harnesses
that exist here), `policy refresh` (records the shipped POLICY template as the merge base
— from now on template changes merge three-way and local edits survive), `plugin refresh`
(brings the plugin copy Claude Code actually loads to 0.7.0; works without a `claude`
binary), `routine install --if-stale` (a daily launchd agent at 07:00 that runs
`teyla update` then `teyla doctor`, and the weekly one on Monday 07:30), then `doctor`.

If launchd agents are blocked on this machine (MDM), `routine install` will say so. That is
fine: the plugin's session-start hook runs the daily update check itself when the last one
is older than a day, so auto-update still happens — at session start instead of 07:00.
Say which of the two paths is the active one here.

## 4. Doctor must be clean

```
teyla doctor
```

Every `FIX` line names the command that repairs it; run it and re-run doctor until no FIX
remains. `WARN` lines are for me to see; `INFO` lines about absent codex/grok/gh and the
same-provider second-opinion fallback are expected on this machine. Paste the full output.

## 5. Verify the routines and the hook

```
teyla routine status
launchctl list | grep zaitsew.teyla
cat ~/.teyla/doctor.summary
```

Then start a new Claude Code session in any repo and confirm the first line it prints is
either the rule count, the doctor summary, or nothing (when all is clear). Report which.

## 6. Send the feedback file back

```
teyla feedback --days 14 --out ~/Downloads/teyla-feedback-$(date +%F).md
```

It is redacted (pseudonymous projects, no text, no paths) and now includes the doctor
checklist, so I can see whether the install is wired here. Tell me where the file is.

## 7. Report

```
machine: <what is present: claude binary yes/no, launchd yes/no, gh/codex/grok yes/no>
install: <method> <old version> → <new version>
update --wire: <the lines it printed>
doctor: <FIX count> <WARN count>; <paste>
auto-update path: launchd daily | session-start hook
feedback file: <path>
blockers: <none | what only I can do, with the exact step>
```
