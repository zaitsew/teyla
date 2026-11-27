"""The PR size gate: one PR per logical unit, in every harness.

Owner rule: "One PR per logical unit - what I would review in one sitting." Claude sessions mostly follow it;
Codex shipped PRs of 1,500+ lines. This is the PreToolUse hook (`plugin/hooks/pr-size-gate.sh`, matcher `Bash`,
Claude Code and Codex) that refuses `gh pr create` and `gh pr merge` for a PR over the limits.

Size is the PR's diff in changed lines (added + deleted) and files, minus what nobody reviews line by line:
lock files, `*.pbxproj`, string catalogs, images, fonts and media, snapshot files, generated directories and
CHANGELOG.md.
  create: `git diff --numstat -z <base>...<head>`; the base is `--base`/`-B` (origin/<base>, then a local ref) or
          origin/HEAD; the head is `--head`/`-H` (`branch` or `owner:branch`: the local branch, else origin/<branch>)
          or HEAD (local, no network).
  merge:  `gh pr view <n|url|branch|current> --json files,additions,deletions,body` (one read-only GitHub call;
          GitHub returns at most 100 files, and a PR of 100 files is over any file limit anyway).

Config, `~/.teyla/config.toml`:
  [pr_size]
  max_lines = 800
  max_files = 20
  mode = "refuse"          # refuse | warn | off

Over the limit, exit 2 and a stderr message with the counts, the top directories and a split hint.
Escape: a line `Size-OK: <reason>` in the PR body (create: the parsed --body value, the --body-file file and a
heredoc on stdin; merge: the PR's body), or `TEYLA_SIZE_OK="<reason>"` in the hook's environment or as a leading assignment word.
Either allows and logs the reason. Every error allows (fail open). When the size cannot be computed (no base, a head that
does not exist, `gh` failing, no checkout) the call is allowed and a row with the reason `unsized: <why>` is logged.
`gh pr merge <URL>` takes owner/repo from the URL, or from `-R/--repo`, so it works outside a checkout.

Rows go to `~/.teyla/pr-size-gate.tsv` (`$TEYLA_HOME` overrides the directory):
`date, harness, repo, PR, lines, files, reason` where the reason is the override text, `refused`, `warned` or `unsized: <why>`.
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import json
import os
import pathlib
import re
import subprocess
import sys

from . import orchestrator_gate as og

LOG_NAME = "pr-size-gate.tsv"
MODES = ("refuse", "warn", "off")
DEFAULTS = {"max_lines": 800, "max_files": 20, "mode": "refuse"}
CALL_TIMEOUT = 7
SPLIT_HINT = ("One PR per logical unit, one sitting of review: e.g. design docs / one screen / data layer. "
              "Split the branch, or say why it cannot be split.")

LOCK_NAMES = {"uv.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "podfile.lock", "package.resolved",
              "cargo.lock", "gemfile.lock", "changelog.md"}
EXCLUDED_GLOBS = ("*.pbxproj", "*.xcstrings", "*.strings", "*.stringsdict", "strings.xml", "*.snap",
                  "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.heic", "*.avif", "*.ico", "*.icns", "*.svg",
                  "*.pdf", "*.ttf", "*.otf", "*.woff", "*.woff2", "*.mp3", "*.mp4", "*.mov", "*.m4a", "*.wav",
                  "*.aif", "*.aiff", "*.webm", "*.car")
EXCLUDED_DIRS = {"__snapshots__", "dist", "build", "generated", "locales"}
OVERRIDE_RE = re.compile(r"(?m)^[ \t>*-]*Size-OK:[ \t]*(\S.*?)['\")\s]*$")


def is_excluded(path: str) -> bool:
    p = path.replace("\\", "/").strip("/")
    low = p.lower()
    name = low.rsplit("/", 1)[-1]
    if name in LOCK_NAMES or name.endswith(".golden") or "_golden" in name:
        return True
    if any(fnmatch.fnmatch(name, g) for g in EXCLUDED_GLOBS):
        return True
    parts = low.split("/")[:-1]
    if any(d in EXCLUDED_DIRS for d in parts):
        return True
    return any(d.startswith("values") and name == "strings.xml" for d in parts) or name == "strings.xml"


def count(entries: list[tuple[str, int]]) -> tuple[int, int, dict[str, int]]:
    """(lines, files, lines per top directory) over the entries that are not excluded."""
    lines = files = 0
    by_dir: dict[str, int] = {}
    for path, n in entries:
        if is_excluded(path):
            continue
        lines += n
        files += 1
        d = os.path.dirname(path.strip("/"))
        key = "/".join(d.split("/")[:2]) if d else "(root)"
        by_dir[key] = by_dir.get(key, 0) + n
    return lines, files, by_dir


def load_config(environ=os.environ) -> dict:
    import tomllib
    cfg = dict(DEFAULTS)
    try:
        data = tomllib.loads((og.home_dir(environ) / "config.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cfg
    sec = data.get("pr_size")
    if isinstance(sec, dict):
        for k in ("max_lines", "max_files"):
            v = sec.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v > 0:
                cfg[k] = v
        m = sec.get("mode")
        if isinstance(m, str) and m.lower() in MODES:
            cfg["mode"] = m.lower()
    return cfg


def log_row(harness: str, repo: str, pr: str, lines: int, files: int, reason: str, environ=os.environ) -> None:
    try:
        d = og.home_dir(environ)
        d.mkdir(parents=True, exist_ok=True)
        clean = lambda s: re.sub(r"[\t\r\n]+", " ", str(s))[:200]
        row = "\t".join([dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), clean(harness), clean(repo), clean(pr),
                         str(lines), str(files), clean(reason)])
        with open(d / LOG_NAME, "a", encoding="utf-8") as f:
            f.write(row + "\n")
    except OSError:
        pass


# --- which command is a PR create / merge ---------------------------------------------------------------------

class Call:
    def __init__(self, action: str, args: list[str], lead_reason: str, cwd: str | None, text: str,
                 heredocs: list[str] | None = None):
        self.action, self.args, self.lead_reason, self.cwd, self.text = action, args, lead_reason, cwd, text
        self.heredocs = heredocs or []


VALUE_OPTS = {"-R", "--repo", "-B", "--base", "-H", "--head", "-b", "--body", "-F", "--body-file", "-t", "--title",
              "-a", "--assignee", "-l", "--label", "-m", "--milestone", "-p", "--project", "-r", "--reviewer",
              "--match-head-commit", "--subject", "-t", "--hostname"}


def _opt(args: list[str], shorts: tuple[str, ...], longs: tuple[str, ...]) -> list[str]:
    """Every value given for an option, in `-b x`, `-bx`, `--body x` and `--body=x` forms."""
    out, i = [], 0
    while i < len(args):
        a = args[i]
        if a in shorts + longs:
            if i + 1 < len(args):
                out.append(args[i + 1])
            i += 2
            continue
        for s in shorts:
            if len(a) > 2 and a.startswith(s) and not a.startswith("--"):
                out.append(a[2:].lstrip("="))
        for l in longs:
            if a.startswith(l + "="):
                out.append(a.split("=", 1)[1])
        i += 1
    return out


def find_calls(command: str, depth: int = 0) -> list[Call]:
    from . import leak_guard as lg
    calls: list[Call] = []
    if depth > 4:
        return calls
    for cmd in lg.lex(command):
        words = list(cmd.words)
        if not words:
            continue
        i, assigns, chdir, split = lg._normalize_ex(words)
        rest = words[i:]
        if split is not None:
            calls += find_calls(split[3], depth + 1)
            continue
        if not rest:
            continue
        exe = os.path.basename(rest[0])
        args = rest[1:]
        if exe in ("sh", "bash", "zsh", "dash", "ksh"):
            for j, a in enumerate(args):
                if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and j + 1 < len(args):
                    calls += find_calls(args[j + 1], depth + 1)
                    break
            continue
        if exe == "eval":
            calls += find_calls(" ".join(args), depth + 1)
            continue
        if exe != "gh":
            continue
        sub, after = og._first_arg(args, og.GH_VALUE_OPTS)
        act, _ = og._first_arg(after, og.GH_VALUE_OPTS)
        if sub != "pr" or act not in ("create", "merge"):
            continue
        # arguments after the action word, with gh's global options kept (-R)
        k = args.index(act, args.index("pr") + 1)
        a2 = args[:args.index("pr")] + args[k + 1:]
        lead = ""
        for a in assigns:
            if a.startswith("TEYLA_SIZE_OK="):
                lead = a.split("=", 1)[1].strip("'\"") or "override"
        calls.append(Call(act, a2, lead, cmd.cwd if isinstance(cmd.cwd, str) and cmd.cwd else chdir,
                          "\n".join([command] + cmd.heredocs), list(cmd.heredocs)))
    return calls


# --- sizing ---------------------------------------------------------------------------------------------------

def _run(argv: list[str], cwd: str | None, environ=os.environ) -> str:
    p = subprocess.run(argv, cwd=cwd or None, capture_output=True, text=True, timeout=CALL_TIMEOUT, env=dict(environ))
    if p.returncode != 0:
        raise RuntimeError(f"{' '.join(argv[:3])} exited {p.returncode}")
    return p.stdout


def default_base(cwd: str | None, environ=os.environ) -> str:
    try:
        ref = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd, environ).strip()
        if ref:
            return ref
    except Exception:
        pass
    for cand in ("origin/main", "origin/master", "main", "master"):
        try:
            _run(["git", "rev-parse", "--verify", "--quiet", cand], cwd, environ)
            return cand
        except Exception:
            continue
    raise RuntimeError("no base branch")


def _verify(ref: str, cwd: str | None, environ) -> bool:
    try:
        _run(["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"], cwd, environ)
        return True
    except Exception:
        return False


def resolve_base(base: str, cwd: str | None, environ=os.environ) -> str:
    """`--base X`: origin/X (the remote ref, also for `release/v1`), then a local ref; no --base: origin/HEAD."""
    if not base:
        return default_base(cwd, environ)
    for cand in (f"refs/remotes/origin/{base}", f"refs/heads/{base}", base):
        if _verify(cand, cwd, environ):
            return cand
    raise RuntimeError(f"base {base} not found")


def resolve_head(head: str, cwd: str | None, environ=os.environ) -> str:
    """`--head X` or `owner:X`: the local branch X, else origin/X; no --head: HEAD."""
    if not head:
        return "HEAD"
    branch = head.split(":", 1)[1] if ":" in head else head
    for cand in (f"refs/heads/{branch}", f"refs/remotes/origin/{branch}"):
        if _verify(cand, cwd, environ):
            return cand
    raise RuntimeError(f"head {head} not found locally or on origin")


def numstat(base: str, cwd: str | None, environ=os.environ, head: str = "HEAD") -> list[tuple[str, int]]:
    out = _run(["git", "diff", "--numstat", "-z", f"{base}...{head}"], cwd, environ)
    toks = out.split("\0")
    entries, i = [], 0
    while i < len(toks):
        t = toks[i]
        i += 1
        if not t:
            continue
        add, dele, path = (t.split("\t", 2) + ["", ""])[:3]
        if path == "" and i + 1 < len(toks):  # a rename: the next two tokens are the old and new path
            path = toks[i + 1]
            i += 2
        n = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
        entries.append((path, n))
    return entries


def body_text(call: Call) -> str:
    """The text of a create call that may carry `Size-OK:`: the parsed --body values, the --body-file files and
    a heredoc on stdin. Never the raw command text."""
    parts = list(_opt(call.args, ("-b",), ("--body",)))
    for f in _opt(call.args, ("-F",), ("--body-file",)):
        if f and f != "-":
            try:
                p = pathlib.Path(f).expanduser()
                if not p.is_absolute() and call.cwd:
                    p = pathlib.Path(call.cwd) / p
                parts.append(p.read_text(encoding="utf-8", errors="replace")[:200000])
            except OSError:
                pass
    parts += call.heredocs
    return "\n".join(parts)


PR_URL_RE = re.compile(r"^https?://([^/\s]+)/([^/\s]+)/([^/\s]+)/pull/\d+")


def _selector(args: list[str]) -> str:
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in VALUE_OPTS:
            skip = True
            continue
        if not a.startswith("-"):
            return a
    return ""


def repo_label(call: Call, cwd: str | None, environ=os.environ) -> str:
    """owner/repo from -R or the PR URL, else the checkout's directory name, else "unknown". Never raises."""
    repo_opt = (_opt(call.args, ("-R",), ("--repo",)) or [""])[0]
    if repo_opt:
        return repo_opt
    m = PR_URL_RE.match(_selector(call.args)) if call.action == "merge" else None
    if m:
        return f"{m.group(2)}/{m.group(3)}"
    try:
        return os.path.basename(_run(["git", "rev-parse", "--show-toplevel"], cwd, environ).strip()) or "unknown"
    except Exception:
        return "unknown"


def measure(call: Call, cwd: str | None, environ=os.environ) -> tuple[int, int, dict[str, int], str, str, str]:
    """(lines, files, by_dir, PR label, repo, PR body text) for the call."""
    repo = repo_label(call, cwd, environ)
    if call.action == "create":
        base = resolve_base((_opt(call.args, ("-B",), ("--base",)) or [""])[0], cwd, environ)
        head = resolve_head((_opt(call.args, ("-H",), ("--head",)) or [""])[0], cwd, environ)
        lines, files, by_dir = count(numstat(base, cwd, environ, head))
        return lines, files, by_dir, "create", repo, body_text(call)
    sel = _selector(call.args)
    repo_opt = (_opt(call.args, ("-R",), ("--repo",)) or [""])[0]
    m = PR_URL_RE.match(sel)
    # a PR URL names its repository; gh needs no checkout and no -R for it
    argv = ["gh", "pr", "view"] + ([sel] if sel else []) + (["-R", repo_opt] if repo_opt and not m else []) + \
           ["--json", "files,additions,deletions,body"]
    data = json.loads(_run(argv, cwd, environ))
    entries = [(f.get("path", ""), int(f.get("additions", 0)) + int(f.get("deletions", 0)))
               for f in data.get("files") or [] if isinstance(f, dict)]
    lines, files, by_dir = count(entries)
    return lines, files, by_dir, sel or "current", repo, str(data.get("body") or "")


def override_reason(call: Call, body: str, environ=os.environ) -> str:
    env = (environ.get("TEYLA_SIZE_OK") or "").strip()
    if env:
        return env
    if call.lead_reason:
        return call.lead_reason
    m = OVERRIDE_RE.search(body)
    return m.group(1) if m else ""


def message(action: str, lines: int, files: int, by_dir: dict[str, int], cfg: dict) -> str:
    top = sorted(by_dir.items(), key=lambda kv: -kv[1])[:5]
    dirs = "; ".join(f"{d} {n}" for d, n in top)
    verb = "create" if action == "create" else "merge"
    return (f"teyla PR size gate: this PR changes {lines} lines in {files} files (limits {cfg['max_lines']} lines, "
            f"{cfg['max_files']} files; lock files, generated files, string catalogs and media not counted). "
            f"Top directories by changed lines: {dirs or 'none'}. {SPLIT_HINT} "
            f"To {verb} anyway, put a line `Size-OK: <reason>` in the PR body"
            + (" (and merge again)" if action == "merge" else "")
            + " or run once with TEYLA_SIZE_OK=\"<reason>\" <command>.")


def decide(payload: dict, environ=os.environ) -> str | None:
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return None
    command = og.command_of(ti)
    if "gh" not in command or "pr" not in command:
        return None
    cfg = load_config(environ)
    if cfg["mode"] == "off":
        return None
    calls = find_calls(command)
    if not calls:
        return None
    harness = og.harness_of(payload)
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else None
    for call in calls:
        where = call.cwd or cwd
        if where and not os.path.isabs(where) and cwd:
            where = os.path.join(cwd, where)
        try:
            lines, files, by_dir, pr, repo, body = measure(call, where, environ)
        except Exception as e:  # fail open, but leave a row `teyla monitor` can count
            why = f"{type(e).__name__}: {e}"
            log_row(harness, repo_label(call, where, environ), call.action, 0, 0, f"unsized: {why}", environ)
            print(f"teyla PR size gate: not sized ({why[:100]}); allowed", file=sys.stderr)
            continue
        if lines <= cfg["max_lines"] and files <= cfg["max_files"]:
            continue
        reason = override_reason(call, body, environ)
        if reason:
            log_row(harness, repo, pr, lines, files, reason, environ)
            continue
        text = message(call.action, lines, files, by_dir, cfg)
        if cfg["mode"] == "warn":
            log_row(harness, repo, pr, lines, files, "warned", environ)
            print(text.replace("teyla PR size gate:", "teyla PR size gate (warn):", 1), file=sys.stderr)
            continue
        log_row(harness, repo, pr, lines, files, "refused", environ)
        return text
    return None


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return 0
        text = decide(payload, os.environ)
    except Exception as e:  # fail open
        try:
            print(f"teyla PR size gate: skipped ({type(e).__name__}: {str(e)[:100]})", file=sys.stderr)
        except Exception:
            pass
        return 0
    if text:
        print(text, file=sys.stderr)
        return 2
    return 0


def monitor_line(days: int = 7, environ=os.environ, now: dt.datetime | None = None) -> str:
    p = og.home_dir(environ) / LOG_NAME
    try:
        rows = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    cutoff = ((now or dt.datetime.now()) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    counts = {"refused": 0, "warned": 0, "overridden": 0, "unsized": 0}
    for r in rows:
        f = r.split("\t")
        if len(f) >= 7 and f[0] >= cutoff:
            counts["refused" if f[6] == "refused" else "warned" if f[6] == "warned"
                   else "unsized" if f[6].startswith("unsized:") else "overridden"] += 1
    parts = ", ".join(f"{n} {k}" for k, n in counts.items() if n)
    return f"PR size gate, last {days} days: {parts}.\n" if parts else ""


if __name__ == "__main__":
    sys.exit(main())
