"""Reading a shell command and its output: is it a test run, a commit, a PR, a review?

Detection works on the command with quoted strings and heredocs blanked out, so a commit message
that says "pytest passes now" is not a test run. The raw command is only used to read arguments
(a PR title) once the shape is known.
"""
from __future__ import annotations

import re
import shlex

_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n[ \t]*\2\b", re.S)
_DQ = re.compile(r'"(?:[^"\\]|\\.)*"')
_SQ = re.compile(r"'[^']*'")
_SUBST = re.compile(r"\$\([^()]*\)|`[^`]*`")
_WRAP = re.compile(r"^\s*(?:bash|sh|zsh)\s+-l?c\s+(['\"])(.*)\1\s*$", re.S)
_PREFIX_WORDS = {"time", "sudo", "env", "nohup", "exec", "command", "npx", "caffeinate"}


def _strip_prefix(seg: str) -> str:
    toks = seg.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", t) or t in _PREFIX_WORDS or re.fullmatch(r"\d*[<>]&?\S*", t):
            i += 1
        elif t in ("uv", "poetry", "pipenv") and i + 1 < len(toks) and toks[i + 1] == "run":
            i += 2
        elif t == "--" and i > 0:
            i += 1
        else:
            break
    return " ".join(toks[i:])


def segments(cmd: str) -> list[str]:
    """The command's simple commands, wrappers stripped, quoted text blanked."""
    for _ in range(3):
        m = _WRAP.match(cmd or "")
        if not m:
            break
        cmd = m.group(2)
    s = _HEREDOC.sub(" ", cmd or "")
    s = _DQ.sub('""', s)
    s = _SQ.sub("''", s)
    s = _SUBST.sub(" ", s)
    return [_strip_prefix(p.strip()) for p in re.split(r"&&|\|\||;|\||\n", s) if p.strip()]


TEST_RUNNERS = (
    ("pytest", re.compile(r"^(?:\S*/)?(?:python[\d.]*\s+-m\s+)?pytest\b|^(?:\S*/)?python[\d.]*\s+-m\s+pytest\b")),
    ("check.sh", re.compile(r"^(?:(?:ba)?sh\s+)?(?:\S*/)?check\.sh\b")),
    ("swift test", re.compile(r"^swift\s+test\b")),
    ("xcodebuild test", re.compile(r"^xcodebuild\b.*\btest(?:-without-building)?\b")),
    ("npm test", re.compile(r"^(?:npm|yarn|pnpm)\s+(?:run\s+)?test\b")),
    ("bun test", re.compile(r"^bun\s+(?:run\s+)?test\b")),
    ("cargo test", re.compile(r"^cargo\s+test\b")),
    ("go test", re.compile(r"^go\s+test\b")),
)
_GIT = r"git(?:\s+-C\s+\S+|\s+-c\s+\S+)*"
_COMMIT = re.compile(rf"^{_GIT}\s+commit\b")
_PR = re.compile(r"^gh\s+pr\s+(create|merge)\b")
_REVIEW = re.compile(r"^(?:\S*/)?(codex-review|claude-review)\b")
BORING = {
    "cd", "ls", "cat", "echo", "pwd", "grep", "rg", "find", "head", "tail", "sed", "awk", "wc", "sleep", "which",
    "mkdir", "test", "[", "true", "false", "export", "source", "printf", "date", "whoami", "ps", "kill", "diff",
    "sort", "uniq", "cut", "tr", "xargs", "jq", "open", "touch", "cp", "mv", "ln", "chmod", "stat", "file", "du",
    "df", "tee", "less", "more", "read", "set", "unset", "type", "basename", "dirname", "realpath", "readlink",
    "tree", "lsof", "pgrep", "wait", "git-status", "teyla", "python3", "python", "node",
}
BORING_GIT = {"status", "diff", "log", "show", "branch", "fetch", "add", "checkout", "switch", "stash", "rev-parse",
              "remote", "worktree", "config", "restore", "ls-files", "blame", "grep", "pull", "reset", "clean", "rm", "mv"}
NOTABLE = re.compile(r"^(?:git\s+(?:-C\s+\S+\s+)?(?:push|merge|rebase|tag)|xcodebuild|swift\s+build|npm\s+run\s+build|"
                     r"make\b|uv\s+(?:pip|sync)|pip\d?\s+install|brew\s+install|docker|vercel|wrangler|testflight|"
                     r"(?:\S*/)?testflight|fastlane|gradlew?\b|\./gradlew|cargo\s+build|go\s+build|npm\s+(?:run\s+)?(?:build|deploy))")


def test_runner(cmd: str) -> str | None:
    for seg in segments(cmd):
        for label, rx in TEST_RUNNERS:
            if rx.match(seg):
                return label
    return None


def is_commit(cmd: str) -> bool:
    return any(_COMMIT.match(s) and "--dry-run" not in s for s in segments(cmd))


def pr_action(cmd: str) -> str | None:
    for seg in segments(cmd):
        m = _PR.match(seg)
        if m:
            return m.group(1)
    return None


def review_tool(cmd: str) -> str | None:
    for seg in segments(cmd):
        m = _REVIEW.match(seg)
        if m:
            return m.group(1)
    return None


def notable(cmd: str) -> int:
    """2: a build, deploy or push; 1: some other command that changes or runs something; 0: a read."""
    best = 0
    for seg in segments(cmd):
        if not seg:
            continue
        if NOTABLE.match(seg):
            return 2
        first = seg.split()[0]
        if first == "git":
            sub = [t for t in seg.split()[1:] if not t.startswith("-")]
            if not sub or sub[0] in BORING_GIT:
                continue
        elif first.rsplit("/", 1)[-1] in BORING:
            continue
        best = 1
    return best


# --- reading what a command printed --------------------------------------------------------

_COMMIT_LINE = re.compile(r"^\[([^\]\s]+)(?: \(root-commit\))? ([0-9a-f]{7,40})\] (.+)$", re.M)


def commits_in(output: str) -> list[tuple[str, str]]:
    """(sha, subject) for each `[branch sha] subject` line git commit printed."""
    return [(m.group(2), m.group(3).strip()) for m in _COMMIT_LINE.finditer(output or "")]


def pr_title(cmd: str) -> str | None:
    """The --title/-t argument of a `gh pr create`."""
    m = re.search(r"(?:--title|-t)(?:\s+|=)(\"(?:[^\"\\]|\\.)*\"|'[^']*'|\S+)", cmd or "")
    if not m:
        return None
    try:
        return shlex.split(m.group(1))[0]
    except (ValueError, IndexError):
        return m.group(1).strip("\"'")


def pr_number(cmd: str, output: str) -> int | None:
    for text in (output or "", cmd or ""):
        m = re.search(r"/pull/(\d+)", text) or re.search(r"pull request [\w./-]*#(\d+)", text, re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"\bgh\s+pr\s+merge\s+(?:\S+\s+)*?(\d+)\b", cmd or "")
    return int(m.group(1)) if m else None


def pr_merge_title(output: str) -> str | None:
    m = re.search(r"Merged pull request [\w./-]*#\d+ \((.+)\)", output or "")
    return m.group(1) if m else None


def review_counts(output: str) -> tuple[int, int] | None:
    """(P1, P2) from a review script's summary line, or counted from its finding lines."""
    m = re.search(r"P1=(\d+)\s+P2=(\d+)", output or "")
    if m:
        return int(m.group(1)), int(m.group(2))
    p1 = len(re.findall(r"^[-* ]*\**P1\b", output or "", re.M))
    p2 = len(re.findall(r"^[-* ]*\**P2\b", output or "", re.M))
    if p1 or p2 or re.search(r"No P1/P2", output or ""):
        return p1, p2
    return None


def test_outcome(runner: str, output: str, exit_code: int | None, failed: bool) -> tuple[bool, int | None, int | None]:
    """(passed, tests passed, tests failed) for one test run. Counts are None when the output has none."""
    out = output or ""
    tail = out[-6000:]
    passed = failed_n = None

    def last(rx: str, text: str = tail):
        ms = re.findall(rx, text)
        return int(ms[-1]) if ms else None

    if runner in ("pytest", "check.sh"):
        passed = last(r"(\d+) passed")
        failed_n = last(r"(\d+) failed")
        err = last(r"(\d+) errors?\b")
        if err:
            failed_n = (failed_n or 0) + err
    elif runner in ("swift test", "xcodebuild test"):
        ms = re.findall(r"Executed (\d+) tests?, with (\d+) failures?", out)
        if ms:
            n, f = int(ms[-1][0]), int(ms[-1][1])
            passed, failed_n = n - f, f
        else:
            m = re.findall(r"Test run with (\d+) tests? .*?(passed|failed)", out)
            if m:
                n = int(m[-1][0])
                passed, failed_n = (n, 0) if m[-1][1] == "passed" else (0, n)
    elif runner == "npm test":
        m = re.search(r"Tests:\s+(?:(\d+) failed,\s*)?(?:(\d+) skipped,\s*)?(?:(\d+) passed)?", tail)
        if m and (m.group(1) or m.group(3)):
            failed_n, passed = int(m.group(1) or 0), int(m.group(3) or 0)
    elif runner == "bun test":
        pm = re.findall(r"^\s*(\d+) pass\b", tail, re.M)
        fm = re.findall(r"^\s*(\d+) fail\b", tail, re.M)
        passed = int(pm[-1]) if pm else None
        failed_n = int(fm[-1]) if fm else None
    elif runner == "cargo test":
        rs = re.findall(r"test result: \w+\. (\d+) passed; (\d+) failed", out)
        if rs:
            passed, failed_n = sum(int(a) for a, _b in rs), sum(int(b) for _a, b in rs)
    elif runner == "go test":
        if re.search(r"^FAIL\b", out, re.M):
            failed_n = len(re.findall(r"^--- FAIL", out, re.M)) or 1
    if failed_n or "** TEST FAILED **" in out:
        ok = False
    elif passed is not None or "** TEST SUCCEEDED **" in out:
        ok = True
    else:
        ok = not failed and exit_code in (0, None)
    return ok, passed, failed_n
