"""Where a correction is kept, and what is taken out of it before it is.

    ~/.teyla/corrections/<repo-key>.jsonl     one file per repo, 0600, in a 0700 directory
    ~/.teyla/corrections/misc.jsonl           prompts typed outside any git repo

A correction used to be appended to `<cwd>/.teyla/corrections.jsonl`, inside the repo, with
the umask's 0644. The security review of 2026-09-29 found what that costs: work repos do not
ignore `.teyla/`, so an agent's `git add -A` commits whatever was pasted into a prompt —
500 raw characters of it, keys included — into a repo other people clone. The store is
therefore outside every repo by default, every write goes through `scrub()` first, and the
old in-repo file is still read (never deleted) but `.teyla/` is added to that repo's
`.git/info/exclude` the first time Teyla touches it, so it cannot be committed by accident.

`teyla config set corrections.store=repo` keeps the old location for someone who wants the
corrections in the repo; the exclude is still added — a file you want in the repo is still
not a file you want committed by an agent.

The repo key is the main checkout's directory name plus eight hex of a hash of its path:
`teyla-3f9c2a1b`. Worktrees resolve to their main checkout (the `.git` file's `commondir`),
so a correction typed in `~/.worktrees/teyla/<branch>` lands with the rest of the repo's and
does not vanish with the worktree; 13 worktrees under ~/.worktrees on the machine this was
written on would otherwise have been 13 separate stores. The key is computed from the
filesystem alone — no `git` subprocess: on a Mac without the Command Line Tools, /usr/bin/git
is a stub that pops an install dialog, and the capture hook runs on every prompt.

Everything here is stdlib and safe to import from the hook (`hook_main`).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

LEGACY = pathlib.Path(".teyla") / "corrections.jsonl"
MAX_TEXT = 500
REDACTED = "[redacted]"
# A record equal to the last one within this many seconds is the same prompt delivered twice:
# Grok loads ~/.cursor/hooks.json as well as its own hooks, so one prompt fires the hook twice.
DEDUPE_S = 10


# --- scrubbing ----------------------------------------------------------------------------

# Specific shapes first, so a key is replaced whole before the generic blob rule sees it.
_SECRET_RES = [
    # PEM blocks, including one cut off by truncation before its END line.
    re.compile(r"-----BEGIN [^\n-]*KEY[^\n-]*-----.*?(?:-----END [^\n-]*-----|\Z)", re.S),
    re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"),            # https://user:password@host
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                 # GitHub classic tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),              # GitHub fine-grained
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}"),                # Anthropic
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),                    # OpenAI (sk-, sk-proj-, …)
    re.compile(r"\bxai-[A-Za-z0-9_\-]{16,}"),                   # xAI
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),               # AWS access key ids
    re.compile(r"\bxox[abposr]-[A-Za-z0-9\-]{10,}"),            # Slack
    re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),                    # Google API keys
    re.compile(r"\b(?:glpat|glptt|gldt)-[A-Za-z0-9_\-]{16,}"),   # GitLab
    re.compile(r"\b(?:hf|npm)_[A-Za-z0-9]{30,}"),               # Hugging Face, npm
    re.compile(r"\bpypi-[A-Za-z0-9_\-]{40,}"),                  # PyPI
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}(?:\.[A-Za-z0-9_\-]{4,}){0,2}"),  # JWTs
    re.compile(r"(?i)(?<=\bbearer )[A-Za-z0-9._~+/=\-]{16,}"),  # Authorization: Bearer …
    re.compile(r"(?i)(?<=\bbasic )[A-Za-z0-9+/=]{12,}"),         # Authorization: Basic …
]
# `password=hunter2`, `API_KEY: "…"`, `"client_secret": "x"`, `--token x`, `password x` (as in
# .netrc): the name stays (it says what was there), the value goes. `pwd` is deliberately
# absent — it is the shell command far more often than a password. The bare-space form is
# limited to a `--flag value` or to `password`/`passwd` themselves: "the token expired" must
# survive, "password hunter2" must not.
_SECRET_NAME = r"[A-Za-z0-9_\-]*?(?:password|passwd|token|secret|api[_-]?key|access[_-]?key|private[_-]?key)"
_VALUE = r"(\"[^\"\n]*\"|'[^'\n]*'|[^\s,;'\"}]+)"
_ASSIGN_RE = re.compile(r"(?i)\b(" + _SECRET_NAME + r"[\"']?)(\s*[:=]\s*)" + _VALUE)
_FLAG_RE = re.compile(r"(?i)((?<!\S)--" + _SECRET_NAME + r")(\s+)(?!\[redacted\])" + _VALUE)
# `password hunter2`: only a value with a digit or a symbol in it — "reset my password then" is prose.
_BARE_RE = re.compile(r"(?i)(\b(?:password|passwd))(\s+)(?!\[redacted\])(?=[^\s,;]*(?:\d|_|[^\s\w,;]))([^\s,;'\"}]+)")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{40,}\b")
_BLOB_RE = re.compile(r"[A-Za-z0-9+/_\-]{40,}={0,2}")


def _blob(m: re.Match) -> str:
    """A long run of base64 characters is a secret when it mixes upper case, lower case and
    digits and is not mostly separators. The separator cap is what keeps paths: a transcript
    path like `/private/tmp/claude-501/-Users-…/def1dd1e-d751-…/tasks/a25794…` is 13% `/`
    and `-`; an AWS secret access key is 0–5%."""
    s = m.group(0)
    seps = sum(s.count(c) for c in "/-_")
    if (any(c.isupper() for c in s) and any(c.islower() for c in s) and any(c.isdigit() for c in s)
            and seps <= len(s) * 0.10):
        return REDACTED
    return s


def scrub(text: str) -> str:
    """`text` with every secret-shaped substring replaced by `[redacted]`. Deliberately
    over-eager: a 40-hex git SHA or a long camelCase identifier with digits goes too. A
    correction loses nothing by that; a leaked key cannot be un-leaked."""
    if not text:
        return text
    for r in _SECRET_RES:
        text = r.sub(REDACTED, text)
    text = _ASSIGN_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    text = _FLAG_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    text = _BARE_RE.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    text = _HEX_RE.sub(REDACTED, text)
    return _BLOB_RE.sub(_blob, text)


def scrub_record(rec: dict) -> dict:
    """Every string value but `ts` scrubbed — `cwd` too: the hook takes it from the payload —
    and `text` truncated to MAX_TEXT after scrubbing (truncating first could cut a key below
    the length its pattern needs, and leave the rest of it)."""
    out = {}
    for k, v in rec.items():
        if isinstance(v, str) and k != "ts":
            v = scrub(v)
            if k in ("text", "draft_excerpt"):
                v = v[:MAX_TEXT]
        out[k] = v
    return out


# --- where --------------------------------------------------------------------------------

def teyla_home() -> pathlib.Path:
    """`TEYLA_HOME` or ~/.teyla, read at call time so a test's (or a hook's) HOME is honoured."""
    return pathlib.Path(os.environ.get("TEYLA_HOME") or (pathlib.Path.home() / ".teyla")).expanduser()


def store_dir() -> pathlib.Path:
    return teyla_home() / "corrections"


def store_mode(cfg: dict | None = None) -> str:
    """"home" (the default: ~/.teyla/corrections/) or "repo" (<repo>/.teyla/corrections.jsonl)."""
    try:
        if cfg is None:
            from . import config
            cfg = config.load(teyla_home() / "config.toml")
        mode = str(((cfg or {}).get("corrections") or {}).get("store") or "home").strip().lower()
    except Exception:  # noqa: BLE001 — a broken config must not stop a capture; default wins
        mode = "home"
    return "repo" if mode == "repo" else "home"


def find_repo(cwd) -> tuple[pathlib.Path | None, pathlib.Path | None]:
    """(main checkout, git common dir) for `cwd`, or (None, None) outside any repo. Pure
    filesystem: `.git` is a directory in a main checkout, and a file `gitdir: <path>` in a
    worktree, whose gitdir holds `commondir` pointing back at the main `.git`."""
    try:
        p = pathlib.Path(cwd).expanduser().resolve()
    except (OSError, RuntimeError):
        return None, None
    for d in (p, *p.parents):
        g = d / ".git"
        if g.is_dir():
            return d, g
        if g.is_file():
            try:
                line = g.read_text(errors="replace").strip()
            except OSError:
                return d, None
            if not line.startswith("gitdir:"):
                return d, None
            gitdir = pathlib.Path(line[len("gitdir:"):].strip())
            if not gitdir.is_absolute():
                gitdir = (d / gitdir)
            gitdir = gitdir.resolve()
            try:
                common = (gitdir / (gitdir / "commondir").read_text().strip()).resolve()
            except OSError:
                return d, gitdir  # a submodule: its own repo, keyed by its own path
            return _main_of(common), common
    return None, None


def _main_of(common: pathlib.Path) -> pathlib.Path:
    """The main checkout of a git common dir: its parent when it is `<checkout>/.git`, else
    `core.worktree` from its config (a `--separate-git-dir` repo), else the dir itself (bare)."""
    if common.name == ".git":
        return common.parent
    try:
        m = re.search(r"^\s*worktree\s*=\s*(.+?)\s*$", (common / "config").read_text(errors="replace"), re.M)
        if m:
            wt = pathlib.Path(m.group(1))
            return (wt if wt.is_absolute() else common / wt).resolve()
    except OSError:
        pass
    return common


def repo_key(root: pathlib.Path | None) -> str:
    if root is None:
        return "misc"
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-.") or "repo"
    return f"{name}-{hashlib.sha1(str(root).encode()).hexdigest()[:8]}"


def path_for(cwd, cfg: dict | None = None) -> pathlib.Path:
    """The file a correction typed in `cwd` is appended to."""
    root, _ = find_repo(cwd)
    if store_mode(cfg) == "repo":
        return (root or pathlib.Path(cwd).expanduser().resolve()) / LEGACY
    return store_dir() / f"{repo_key(root)}.jsonl"


def legacy_paths(cwd) -> list[pathlib.Path]:
    """In-repo files older versions wrote: the main checkout's, and — when `cwd` is inside a
    worktree or a subdirectory — the one next to where the prompt was typed."""
    root, _ = find_repo(cwd)
    here = pathlib.Path(cwd).expanduser().resolve()
    out = []
    for base in dict.fromkeys(b for b in (root, _toplevel(here), here) if b is not None):
        f = base / LEGACY
        if f.is_file():
            out.append(f)
    return out


def _toplevel(p: pathlib.Path) -> pathlib.Path | None:
    for d in (p, *p.parents):
        if (d / ".git").exists():
            return d
    return None


# --- the exclude --------------------------------------------------------------------------

def ensure_excluded(cwd) -> bool:
    """Add `.teyla/` to the repo's `.git/info/exclude` (shared by all its worktrees) unless a
    line there already covers it. True when a line was added. Never touches `.gitignore`:
    that is committed, and whether a repo ignores Teyla is not Teyla's decision to commit."""
    root, common = find_repo(cwd)
    if common is None or not common.is_dir():
        return False
    exclude = common / "info" / "exclude"
    try:
        text = exclude.read_text(errors="replace") if exclude.exists() else ""
        if any(l.strip() in (".teyla", ".teyla/", "/.teyla", "/.teyla/") for l in text.splitlines()):
            return False
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lead = "" if not text or text.endswith("\n") else "\n"
        with exclude.open("a") as f:
            f.write(f"{lead}# teyla: local correction records, never committed\n.teyla/\n")
        return True
    except OSError:
        return False


def _touch_legacy(cwd, mode: str) -> None:
    """First touch of a repo that has (or, in repo mode, will have) an in-repo `.teyla/`."""
    root, _ = find_repo(cwd)
    if root is None:
        return
    if mode == "repo" or (root / ".teyla").exists() or legacy_paths(cwd):
        ensure_excluded(cwd)


# --- write --------------------------------------------------------------------------------

def _private_dir(d: pathlib.Path) -> None:
    from . import config
    config.private_dir(d)


def _append_line(path: pathlib.Path, line: str) -> None:
    """Append one line, 0600. O_NOFOLLOW: in repo mode the path is inside a repo, and a
    `.teyla/corrections.jsonl` symlink committed there must not redirect the write (or the
    chmod) to another file. The mode is fixed on the descriptor before anything is written:
    O_CREAT's mode only applies to a new file, and one an older version wrote is 0644."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise OSError(f"not a regular file: {path}")
        if st.st_mode & 0o077:
            os.fchmod(fd, 0o600)
        data = line.encode("utf-8")
        # A torn last line (a hook killed mid-write, a hand edit) must not swallow this record.
        if st.st_size and os.pread(fd, 1, st.st_size - 1) != b"\n":
            data = b"\n" + data
        os.write(fd, data)
    finally:
        os.close(fd)


def append(cwd, rec: dict, cfg: dict | None = None) -> pathlib.Path:
    """Scrub `rec`, append it to `cwd`'s store, return the file. The only writer."""
    mode = store_mode(cfg)
    path = path_for(cwd, cfg)
    _touch_legacy(cwd, mode)
    if mode == "home":
        _private_dir(teyla_home())
        _private_dir(path.parent)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    _append_line(path, json.dumps(scrub_record(rec), ensure_ascii=False, default=str) + "\n")
    return path


def import_lines(cwd, lines: list[bytes], cfg: dict | None = None) -> int:
    """Append the records in `lines` (raw JSONL, e.g. a worktree's legacy file) that `cwd`'s
    store lacks, scrubbed on the way in. Returns how many were added."""
    path = path_for(cwd, cfg)
    have = set()
    if path.is_file():
        have = {l for l in path.read_bytes().split(b"\n") if l.strip()}
    n = 0
    for raw in lines:
        if not raw.strip() or raw in have:
            continue
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:
            continue  # a torn line from a killed hook: nothing recoverable in it
        if not isinstance(rec, dict):
            continue
        line = json.dumps(scrub_record(rec), ensure_ascii=False, default=str).encode()
        if line in have:
            continue
        append(cwd, rec, cfg)
        have.add(line)
        n += 1
    return n


# --- read ---------------------------------------------------------------------------------

def _read(path: pathlib.Path) -> list[dict]:
    out = []
    try:
        # Split on \n only: splitlines() also breaks on U+2028, which JSON allows in a string.
        for line in path.read_bytes().split(b"\n"):
            if not line.strip():
                continue
            try:
                rec = json.loads(line.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if isinstance(rec, dict):
                # Pre-0.12 files were written unscrubbed; nothing leaves this module raw.
                out.append(scrub_record(rec))
    except OSError:
        pass
    return out


def records(cwd, cfg: dict | None = None) -> list[dict]:
    """Every correction recorded for `cwd`'s repo: the store, plus any legacy in-repo file
    (read, never moved or deleted). Duplicates — the same record in both — count once."""
    mode = store_mode(cfg)
    _touch_legacy(cwd, mode)
    root, _ = find_repo(cwd)
    files = [path_for(cwd, cfg)] + legacy_paths(cwd)
    seen, out = set(), []
    for f in dict.fromkeys(files):
        for rec in _read(f):
            if root is None and rec.get("cwd") and rec["cwd"] != str(pathlib.Path(cwd).expanduser().resolve()):
                continue  # misc.jsonl holds every non-repo directory; keep this one's
            k = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            if k not in seen:
                seen.add(k); out.append(rec)
    return sorted(out, key=lambda r: str(r.get("ts") or ""))


def all_records(cfg: dict | None = None) -> list[tuple[str, dict]]:
    """(repo, record) for every store file, and every legacy file one level under code_root."""
    from . import config
    cfg = cfg if cfg is not None else config.load(teyla_home() / "config.toml")
    out, seen = [], set()
    files: list[tuple[str, pathlib.Path]] = []
    d = store_dir()
    if d.is_dir():
        files += [(f.stem, f) for f in sorted(d.glob("*.jsonl"))]
    try:
        root = config.code_root(cfg)
        if root.is_dir():
            for repo in sorted(root.iterdir()):
                f = repo / LEGACY
                if f.is_file():
                    ensure_excluded(repo)
                    files.append((repo_key(repo), f))
    except OSError:
        pass
    for key, f in files:
        for rec in _read(f):
            k = json.dumps(rec, sort_keys=True, ensure_ascii=False)
            if k not in seen:
                seen.add(k); out.append((key, rec))
    return sorted(out, key=lambda kr: str(kr[1].get("ts") or ""))


# --- the capture hook ---------------------------------------------------------------------

# The hook's net: obvious correction phrasing, English and Russian. Coarse on purpose — it
# records candidates for a human to promote, it does not decide anything.
CAPTURE_RE = re.compile(
    r"\bdon't\b|\bwrong\b|\bnot like that\b|\bagain\b|\brevert\b|не так|неправильно|опять",
    re.I,
)


def _pick(d: dict):
    """The prompt, under whichever key this harness uses: Claude Code and Cursor `prompt`,
    Grok `prompt` in a camelCase envelope, Hermes `extra.user_message`."""
    for k in ("prompt", "text", "user_message", "userMessage", "message", "input"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v
    ex = d.get("extra")
    return _pick(ex) if isinstance(ex, dict) else None


def capture(data: dict, now: _dt.datetime | None = None, cfg: dict | None = None) -> pathlib.Path | None:
    """What the UserPromptSubmit hook does with one payload. The file written, or None."""
    from .adapters import is_noise_turn
    prompt = _pick(data) if isinstance(data, dict) else None
    if not isinstance(prompt, str):
        return None
    if is_noise_turn(prompt.lstrip()):
        return None
    if not CAPTURE_RE.search(prompt):
        return None
    cwd = data.get("cwd") or data.get("workspaceRoot") or data.get("workspace_root") or os.getcwd()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    rec = scrub_record({"ts": now.isoformat(timespec="seconds"), "cwd": cwd, "text": prompt})
    path = path_for(cwd, cfg)
    try:
        last = _read(path)[-1]
        if last.get("text") == rec["text"]:
            if abs((now - _dt.datetime.fromisoformat(last["ts"])).total_seconds()) < DEDUPE_S:
                return None
    except (IndexError, KeyError, ValueError, TypeError):
        pass
    return append(cwd, rec, cfg)


def hook_main(stream=None) -> None:
    """Entry point for plugin/hooks/capture-correction.sh. Never raises, never prints:
    UserPromptSubmit stdout is injected into the model's context."""
    try:
        capture(json.load(stream or sys.stdin))
    except Exception:  # noqa: BLE001 — a hook must never fail the session
        pass
