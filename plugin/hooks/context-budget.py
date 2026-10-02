#!/usr/bin/env python3
"""Claude Code hook: keep a long session cheap without ending it. Opt-in
(`teyla config set hooks.context_budget=true`); started by context-budget.sh only when on.

Every turn re-reads the whole context, so a turn at 450k costs about nine times one at 50k.
The 27 Sept 2026 audit found orchestrator sessions spending 43% of their turns above 400k;
`teyla spend` priced that re-reading at $772 of $2,696 for the week to 1 Oct.

Stopping the session at 300k and continuing in a fresh one saved the tokens but split one
project across several windows, so the session shrinks in place instead:

  1. ~/.claude/settings.json sets "autoCompactWindow": 400000. Claude Code then compacts at
     about 365k (window minus the output reserve minus 13k) and carries on: same window, same
     session id. `teyla doctor` warns when the key is missing; it never writes the file.
  2. This hook, at `[hooks] context_budget_first` (300000) and again every
     `context_budget_step` (40000) after, has the model write a handoff (state, open work,
     decisions, next steps, file paths) to ~/.teyla/handoff/<session_id>.md and keep working.
     It is the part of the context the compaction summary must not lose.
  3. On SessionStart with source "compact" it puts that handoff back into the context, so work
     resumes from what the model chose to keep, not only from the automatic summary, and resets
     the reminder level. A handoff is used once: it is renamed <session_id>.prev.md, so a later
     compaction never brings back an older cycle's decisions as current. Lookup is by session
     id only (it survives compaction); another session's note in the same repo is never used.

Ported from the owner's ~/ops/bin/context-budget-hook so the work MacBook, which has no ~/ops,
gets it pinned with the plugin. Differences: handoffs live under ~/.teyla/handoff/ (0700, files
0600 — they hold the session's working state, often an employer's file paths) instead of
~/.cache, and the thresholds come from ~/.teyla/config.toml instead of the environment.

Stdlib only: it may run on whatever python3 the wrapper found, which need not have `teyla`
importable (and before 3.11 has no tomllib). Never blocks; exits 0 on any error.
"""
import json
import os
import re
import sys

HANDOFF_MAX = 24_000  # characters put back after a compaction; the rest stays on disk
TAIL = 3_000_000      # bytes of transcript read from the end; the last usage record is near it


def teyla_dir():
    return os.path.expanduser(os.environ.get("TEYLA_HOME") or "~/.teyla")


def thresholds():
    """(first, step) from `[hooks]` in ~/.teyla/config.toml (not TEYLA_HOME: the wrapper and
    `teyla config` both read the config from HOME), defaults 300000 / 40000."""
    first, step = 300_000, 40_000
    path = os.path.expanduser("~/.teyla/config.toml")
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return first, step
    hooks = {}
    try:
        import tomllib
        hooks = tomllib.loads(text).get("hooks") or {}
    except Exception:  # noqa: BLE001 — no tomllib (python < 3.11), or a file that does not parse
        inside = False
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("["):
                inside = line.replace(" ", "") == "[hooks]"
            elif inside and "=" in line:
                k, v = (x.strip().strip("\"'") for x in line.split("=", 1))
                hooks[k] = v
    try:
        first = int(hooks.get("context_budget_first", first))
    except (TypeError, ValueError):
        pass
    try:
        step = max(1, int(hooks.get("context_budget_step", step)))
    except (TypeError, ValueError):
        pass
    return first, step


def private_dir(d):
    """mkdir -p at 0700, tightened if it exists looser (as teyla.config.private_dir)."""
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        if os.stat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def write_private(path, text):
    private_dir(os.path.dirname(path))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def safe_id(sid):
    """The session id as a file name: a payload is input, and `../x` must not become a path."""
    s = re.sub(r"[^A-Za-z0-9_-]", "", str(sid or ""))
    return s or "unknown"


def last_context(path):
    """Input + cache-read + cache-creation tokens of the last main-thread usage record: what the
    next turn re-reads. Sidechain (subagent) records have their own, smaller context."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - TAIL))
        lines = f.read().decode("utf-8", "ignore").splitlines()
    for line in reversed(lines):
        if '"usage"' not in line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain"):
            continue
        u = (d.get("message") or {}).get("usage")
        if u:
            return (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                    + u.get("cache_creation_input_tokens", 0))
    return 0


def emit(event, note):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": note}}))


def on_compact(data, hdir):
    sid = safe_id(data.get("session_id"))
    try:
        os.remove(os.path.join(hdir, f"{sid}.level"))
    except OSError:
        pass
    path, prev = os.path.join(hdir, f"{sid}.md"), os.path.join(hdir, f"{sid}.prev.md")
    if not os.path.exists(path):
        old = f" The one from the previous compaction is {prev}; it may be stale." if os.path.exists(prev) else ""
        emit("SessionStart",
             "Context budget: the session was just compacted and no handoff was written since the last "
             "one." + old + " Rebuild the working state before continuing: git status and the open PRs/MRs "
             "of this repo, running lanes, and the compaction summary above.")
        return
    with open(path, encoding="utf-8", errors="ignore") as f:
        text = f.read()
    # Used once: a later compaction must not bring back this cycle's decisions as current.
    os.replace(path, prev)
    cut = "" if len(text) <= HANDOFF_MAX else f"\n\n[cut at {HANDOFF_MAX} characters; the full note is {prev}]"
    emit("SessionStart",
         f"Context budget: the session was just compacted to keep it cheap. This is the handoff you "
         f"wrote before it (now {prev}). Continue the work from it; do not start a new session and do "
         f"not ask the user to.\n\n{text[:HANDOFF_MAX]}{cut}")


def on_turn(data, hdir):
    path, sid = data.get("transcript_path"), safe_id(data.get("session_id"))
    if not path or not os.path.isfile(path):
        return
    first, step = thresholds()
    ctx = last_context(path)
    if ctx < first:
        return
    level = (ctx - first) // step
    mark = os.path.join(hdir, f"{sid}.level")
    try:
        with open(mark) as f:
            seen = int(f.read().strip())
    except (OSError, ValueError):
        seen = -1
    if level <= seen:
        return
    write_private(mark, str(level))
    target = os.path.join(hdir, f"{sid}.md")
    verb = "Rewrite" if os.path.exists(target) else "Write"
    emit(data.get("hook_event_name") or "UserPromptSubmit",
         f"Context budget: this session is at ~{ctx // 1000}k tokens of context. Claude Code will compact "
         f"it (at about 365k with \"autoCompactWindow\": 400000) and carry on in this same session. "
         f"{verb} the handoff now, at {target}: state of the work, open PRs/MRs and running lanes, "
         "decisions taken and why, next steps, file paths. Keep it under 300 lines. Then keep working; "
         "it is put back into the context after the compaction. Do not stop and do not ask the user "
         "to start a new session.")


def main():
    data = json.load(sys.stdin)
    hdir = private_dir(os.path.join(teyla_dir(), "handoff"))
    if data.get("hook_event_name") == "SessionStart":
        if data.get("source") == "compact":
            on_compact(data, hdir)
        return
    on_turn(data, hdir)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — a broken hook must never break the session
        pass
    sys.exit(0)
