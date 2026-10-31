"""The agent boundary: what `plugin/hooks/leak-guard.sh` hands to Python once a command has matched a token.

The shell script does the coarse, fixed-string screen. A command with none of its tokens never reaches
this module. A command with one is parsed here, as a shell would split it, and checked against five rules:

  1. A credential path (an SSH private key, the AWS credentials, the private-terms list, an App Store
     Connect key, a harness auth file, a key or certificate outside the repo) is not read, copied or edited.
     `ls -l` and `stat` on it are metadata and pass.
  2. `security find-generic-password -w` (also `-g`, `find-internet-password`) and `dump-keychain` print a
     secret from the Keychain: refused.
  3. `gh repo edit --visibility public` is the owner's decision: refused. Creating a public repo is not.
  4. The text a command publishes (the title, body, notes, message, comment or description of a `gh pr`,
     `gh issue`, `gh release`, `gh gist` or `gh repo` call; a `git commit`, `git tag` or `git merge`
     message; a file passed with `-F`; a heredoc) goes to `teyla leak --text -`. A finding is refused with
     the scanner's masked lines. The hook never prints the text it scanned.
  5. Anything this module cannot decide on a matched command (the scanner is missing, crashes, times out,
     or the body is a variable or a pipe it cannot read) is a refusal. Exit 2, with the reason.

Exit 0 allows the call, exit 2 refuses it and puts stderr in front of the model. There is no third answer.
This is one door of four (`docs/SHIELD.md`, SH3 and SH6), not the wall: a payload that is encoded, or that
is built from a variable set in an earlier call, passes.
"""
from __future__ import annotations

import datetime
import itertools
import json
import os
import re
import shutil
import subprocess
import sys

SCAN_TIMEOUT = 25            # seconds; the hook's own timeout in hooks.json is longer, so this fires first
MAX_FILE = 5_000_000         # a body file larger than this is not scanned, so it is refused
MAX_SHOWN = 20

SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
WRAPPERS = {"env", "command", "builtin", "time", "sudo", "doas", "nice", "nohup", "exec", "caffeinate", "stdbuf",
            "timeout", "xcrun", "arch", "setsid", "then", "do", "else", "elif", "if", "while", "until", "!", "{", "("}
INTERPRETERS = SHELLS | {"python", "python3", "node", "ruby", "perl", "osascript", "php", "deno", "bun", "awk", "gawk"}
METADATA_ONLY = {"ls", "stat", "test", "[", "[[", "cd", "pushd"}      # they read a name, never the content
PRINTERS = {"echo", "printf"}
READERS = {"cat", "head", "tail", "tac", "nl"}
READ_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}

# (group, verb) pairs of `gh` that publish text, and the flags that carry it.
GH_TEXT_VERBS = {
    ("pr", "create"), ("pr", "edit"), ("pr", "comment"), ("pr", "review"), ("pr", "merge"), ("pr", "close"),
    ("issue", "create"), ("issue", "comment"), ("issue", "edit"), ("issue", "close"),
    ("release", "create"), ("release", "edit"), ("gist", "create"), ("gist", "edit"),
    ("repo", "create"), ("repo", "edit"),
}
GIT_TEXT_VERBS = {"commit", "tag", "merge"}
GH_TEXT_LONG = {"title", "body", "notes", "message", "comment", "description", "desc", "subject"}
GH_FILE_LONG = {"body-file", "notes-file", "add"}       # `gh gist edit --add FILE` publishes FILE
API_TEXT_KEYS = {"body", "title", "message", "description", "text", "note", "content"}

# Credential paths. A pattern must start a path segment. HOME ones count unless the path is inside the repo
# (a repo's own `.codex/config.toml` is a fixture, not a credential); the private-terms list counts anywhere.
HOME_CREDS = (
    ("an SSH private key", r"\.ssh/id_[\w.*?\[\]-]*"),
    ("the AWS credentials file", r"\.aws/credentials"),
    ("the App Store Connect key directory", r"\.appstoreconnect(?![\w-])"),
    ("the Grok config", r"\.grok/config\.toml"),
    ("the Codex auth file", r"\.codex/auth\.json"),
    ("the Codex config", r"\.codex/config\.toml"),
    ("the Claude credentials file", r"\.claude/\.credentials\.json"),
    ("the .netrc file", r"\.netrc(?![\w])"),
    ("the Docker config", r"\.docker/config\.json"),
)
_GROUPS = itertools.count(1)              # ids of subshell / substitution scopes, for tracking `cd`
_PATH_PREFIX = r"([^\s'\"`=:()<>|;&,]*)"


class Refuse(Exception):
    """Carries the lines of one refusal."""

    def __init__(self, lines: list[str]):
        super().__init__(lines[0])
        self.lines = lines


# --- a small shell lexer ---------------------------------------------------------------------------------

class Cmd:
    __slots__ = ("words", "heredocs", "stdin_files", "subs", "prev_pipe", "text_idx", "grp", "cwd", "skip")

    def __init__(self):
        self.words: list[str] = []
        self.heredocs: list[str] = []       # heredoc bodies and here-strings that feed this command's stdin
        self.stdin_files: list[str] = []    # `< file`
        self.subs: list["Cmd"] = []         # commands inside $( ) and backticks in this command's words
        self.prev_pipe: "Cmd | None" = None  # the command whose stdout this one reads (`a | b`)
        self.text_idx: set[int] = set()     # word positions that are prose, not paths
        self.grp: tuple = ()                # the subshells and substitutions this command sits in
        self.cwd: str | None = ""           # the directory it runs in (None: cannot be known); set by the analysis
        self.skip = False                   # started with a leading TEYLA_LEAK_GUARD=0 assignment


class Lex:
    """Splits a shell command line into simple commands: quotes, escapes, $( ), backticks and heredocs. It does
    not expand anything. A text it cannot make sense of becomes words, never an exception."""

    def __init__(self, src: str, depth: int = 0, stack=()):
        self.s = src
        self.i = 0
        self.depth = depth
        self.stack: list[int] = list(stack)
        self.out: list[Cmd] = []

    def new(self) -> Cmd:
        c = Cmd()
        c.grp = tuple(self.stack)
        self.out.append(c)
        return c

    def run(self) -> list[Cmd]:
        self.commands(None)
        return [c for c in self.out if c.words or c.heredocs or c.stdin_files]

    def _sub(self, cur: Cmd, closer: str) -> None:
        a = len(self.out)
        depth0 = len(self.stack)
        self.stack.append(next(_GROUPS))
        self.commands(closer)
        del self.stack[depth0:]
        cur.subs.extend(self.out[a:])

    def _heredoc_body(self, delim: str, strip: bool) -> str:
        s, n, i, lines = self.s, len(self.s), self.i, []
        while i < n:
            j = s.find("\n", i)
            line, nxt = (s[i:], n) if j < 0 else (s[i:j], j + 1)
            i = nxt
            if (line.lstrip("\t") if strip else line) == delim:
                self.i = i
                return "\n".join(lines)
            lines.append(line)
        self.i = n
        return "\n".join(lines)             # never terminated: the rest of the text is the body

    def commands(self, closer: str | None) -> None:
        s, n = self.s, len(self.s)
        cur = self.new()
        word: list[str] | None = None
        mode = None                          # "in": next word is a stdin file; "here": a here-string
        pending: list[tuple[str, bool, Cmd]] = []
        parens = 0

        def flush():
            nonlocal word, mode
            if word is None:
                return
            w, word = "".join(word), None
            if mode == "in":
                cur.stdin_files.append(w)
            elif mode == "here":
                cur.heredocs.append(w)
            else:
                cur.words.append(w)
            mode = None

        def part(text: str):
            nonlocal word
            if word is None:
                word = []
            word.append(text)

        def split(pipe: bool):
            nonlocal cur
            flush()
            prev = cur
            cur = self.new()
            if pipe:
                cur.prev_pipe = prev

        while self.i < n:
            c = s[self.i]
            if c == "\\":
                nx = s[self.i + 1:self.i + 2]
                self.i += 2
                if nx and nx != "\n":
                    part(nx)
                continue
            if c == "'":
                j = s.find("'", self.i + 1)
                j = n if j < 0 else j
                part(s[self.i + 1:j])
                self.i = j + 1
                continue
            if c == '"':
                self.i += 1
                part("")
                while self.i < n and s[self.i] != '"':
                    d = s[self.i]
                    if d == "\\" and s[self.i + 1:self.i + 2] in ('"', "\\", "$", "`", "\n"):
                        if s[self.i + 1] != "\n":
                            part(s[self.i + 1])
                        self.i += 2
                    elif d == "$" and s[self.i + 1:self.i + 2] == "(" and self.depth < 8:
                        start = self.i
                        self.i += 2
                        self._sub(cur, ")")
                        part(s[start:self.i])
                    elif d == "`" and self.depth < 8:
                        j = self._backtick_end(self.i)
                        self._backtick(cur, self.i, j)
                        part(s[self.i:j + 1])
                        self.i = j + 1
                    else:
                        part(d)
                        self.i += 1
                self.i += 1
                continue
            if c == "$" and s[self.i + 1:self.i + 2] == "(" and self.depth < 8:
                start = self.i
                self.i += 2
                self._sub(cur, ")")
                part(s[start:self.i])
                continue
            if c == "`" and self.depth < 8:
                j = self._backtick_end(self.i)
                self._backtick(cur, self.i, j)
                part(s[self.i:j + 1])
                self.i = j + 1
                continue
            if c == "<":
                if s.startswith("<<<", self.i):
                    flush()
                    mode = "here"
                    self.i += 3
                    continue
                if s.startswith("<<", self.i):
                    flush()
                    self.i += 2
                    strip = s[self.i:self.i + 1] == "-"
                    if strip:
                        self.i += 1
                    while self.i < n and s[self.i] in " \t":
                        self.i += 1
                    delim = []
                    while self.i < n and s[self.i] not in " \t\n;&|()<>":
                        d = s[self.i]
                        if d in "'\"":
                            j = s.find(d, self.i + 1)
                            j = n if j < 0 else j
                            delim.append(s[self.i + 1:j])
                            self.i = j + 1
                        elif d == "\\":
                            delim.append(s[self.i + 1:self.i + 2])
                            self.i += 2
                        else:
                            delim.append(d)
                            self.i += 1
                    if delim:
                        pending.append(("".join(delim), strip, cur))
                    continue
                if s.startswith("<(", self.i) and self.depth < 8:
                    start = self.i
                    self.i += 2
                    self._sub(cur, ")")
                    part(s[start:self.i])
                    continue
                flush()
                mode = "in"
                self.i += 1
                continue
            if c in " \t":
                flush()
                self.i += 1
                continue
            if c == "\n":
                split(False)
                self.i += 1
                for delim, strip, owner in pending:
                    owner.heredocs.append(self._heredoc_body(delim, strip))
                pending = []
                continue
            if c == "#" and word is None:
                j = s.find("\n", self.i)
                self.i = n if j < 0 else j
                continue
            if c == ";":
                split(False)
                self.i += 1
                continue
            if c == "&":
                split(False)
                self.i += 1
                continue
            if c == "|":
                pipe = s[self.i + 1:self.i + 2] != "|" and s[self.i - 1:self.i] != "|"
                split(pipe)
                self.i += 1
                continue
            if c == "(":
                parens += 1
                self.stack.append(next(_GROUPS))
                split(False)
                self.i += 1
                continue
            if c == ")":
                if parens > 0:
                    parens -= 1
                    self.stack.pop()
                    split(False)
                    self.i += 1
                    continue
                if closer == ")":
                    flush()
                    self.i += 1
                    return
            part(c)
            self.i += 1
        flush()

    def _backtick_end(self, start: int) -> int:
        j = start + 1
        while j < len(self.s) and self.s[j] != "`":
            j += 2 if self.s[j] == "\\" else 1
        return min(j, len(self.s) - 1)

    def _backtick(self, cur: Cmd, a: int, b: int) -> None:
        inner = Lex(self.s[a + 1:b], self.depth + 1, self.stack + [next(_GROUPS)])
        inner.commands(None)
        self.out.extend(inner.out)
        cur.subs.extend(inner.out)


def lex(src: str, depth: int = 0) -> list[Cmd]:
    return Lex(src, depth).run()


# --- paths -----------------------------------------------------------------------------------------------

class Env:
    """Where the call runs: the working directory, the repo root, the home directory."""

    def __init__(self, cwd: str, environ):
        self.environ = environ
        self.home = os.path.normpath(environ.get("HOME") or os.path.expanduser("~"))
        self.cwd = os.path.normpath(cwd) if cwd else os.getcwd()
        self.root = self._root(self.cwd)
        self.real_root = os.path.realpath(self.root)
        self.real_home = os.path.realpath(self.home)
        terms = environ.get("TEYLA_PRIVATE_TERMS", "")
        self.terms = os.path.normpath(self.expand(terms)) if terms else ""
        self.real_terms = os.path.realpath(self.terms) if terms else ""
        self.log = os.path.join(environ.get("TEYLA_HOME") or os.path.join(self.home, ".teyla"), "leak-skips.log")

    @staticmethod
    def _root(cwd: str) -> str:
        d = cwd
        while True:
            if os.path.exists(os.path.join(d, ".git")):
                return d
            parent = os.path.dirname(d)
            if parent == d:
                return cwd
            d = parent

    def expand(self, p: str) -> str:
        p = p.replace("${HOME}", self.home).replace("$HOME", self.home)
        return re.sub(r"(?<![\w$])~(?=/|$)", self.home, p)

    def resolve(self, p: str, cwd: str | None = None) -> str:
        p = self.expand(p)
        return os.path.normpath(p if p.startswith("/") else os.path.join(cwd or self.cwd, p))

    def inside_repo(self, path: str) -> bool:
        """Under the repo root once symlinks are resolved (a repo path that links to ~/.aws/credentials is
        outside), where the root does not hold the home directory (a session started in ~ has no 'inside':
        everything in the home directory is outside)."""
        path, r = os.path.realpath(path), self.real_root
        if not (path == r or path.startswith(r.rstrip("/") + "/")):
            return False
        return not (self.real_home == r or self.real_home.startswith(r.rstrip("/") + "/"))


def credential_hits(text: str, env: Env, cwd: str | None = None) -> list[str]:
    """Labels of the credential paths named in a text (a word, a file_path, a heredoc fed to an interpreter).
    A word that is a path is also followed through its symlinks: a link that ends at a credential is one."""
    hits = _credential_hits(text, env, cwd)
    if text and len(text) < 2048 and not re.search(r"[\s$`]", text):
        full = env.resolve(text, cwd)
        real = os.path.realpath(full)
        if real != full:
            hits += [h for h in _credential_hits(real, env, cwd) if h not in hits]
    return hits


def _credential_hits(text: str, env: Env, cwd: str | None) -> list[str]:
    hits: list[str] = []

    def add(label: str):
        if label not in hits:
            hits.append(label)

    if re.search(r"\$\{?TEYLA_PRIVATE_TERMS", text) or re.search(r"private-terms\.txt", text):
        add("the private-terms list")
    if env.terms and (env.terms in env.expand(text) or env.real_terms in env.expand(text)):
        add("the private-terms list")
    for label, pat in HOME_CREDS:
        for m in re.finditer(_PATH_PREFIX + "(" + pat + ")", text):
            prefix, found = m.group(1), m.group(2)
            if label == "an SSH private key" and found.endswith(".pub"):
                continue
            if prefix and not prefix.endswith("/"):
                continue
            if not env.inside_repo(env.resolve(prefix + found, cwd)):
                add(label)
    for m in re.finditer(_PATH_PREFIX + r"(\.(?:pem|p8))(?![\w])", text):
        if not env.inside_repo(env.resolve(m.group(1) + m.group(2), cwd)):
            add("a key or certificate file outside the repo")
    return hits


def credential_lines(label: str) -> list[str]:
    return [f"teyla leak-guard: refused — this file is a credential ({label}); the agent never reads it.",
            "  Reference it by path or use the tool that consumes it."]


# --- the analysis ----------------------------------------------------------------------------------------

class Pub:
    """One command that publishes text, and where its text comes from."""

    def __init__(self, name: str, cmd: Cmd):
        self.name = name
        self.cmd = cmd
        self.texts: list[str] = []
        self.files: list[str] = []
        self.stdin = False
        self.refusals: list[str] = []       # why the guard cannot tell what this command publishes
        self.sub_text = False               # a text argument holds a $( ) or backtick substitution


class Analysis:
    def __init__(self, env: Env):
        self.env = env
        self.pubs: list[Pub] = []
        self.hard: list[str] = []            # lines of a refusal that no skip can lift
        self.cmds: list[Cmd] = []


ASSIGN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
DURATION = re.compile(r"[0-9.]+[smhd]?")
SKIP_ASSIGN = "TEYLA_LEAK_GUARD=0"
KEY_EXEC = {"gh", "git", "security"}

# What each wrapper's own options look like, so the executable is the word after them, not an option's value.
# (letters that take a value, long names that take one)
WRAP_VALUE = {
    "env": ("uCS", {"unset", "chdir", "split-string", "argv0"}),
    "sudo": ("ughpCDrtUTR", {"user", "group", "host", "prompt", "close-from", "chdir", "role", "type",
                             "other-user", "command-timeout", "chroot"}),
    "doas": ("uC", set()),
    "nice": ("n", {"adjustment"}),
    "time": ("fo", {"format", "output"}),
    "timeout": ("sk", {"signal", "kill-after"}),
    "exec": ("a", set()),
    "caffeinate": ("tw", set()),
    "stdbuf": ("ioe", {"input", "output", "error"}),
    "xcrun": ("", {"sdk", "toolchain", "log"}),
    "arch": ("", {"arch"}),
}
# (letters and long names that are plain switches). An option in neither table makes the answer uncertain.
WRAP_FLAGS = {
    "env": ("i0v", {"ignore-environment", "null", "debug"}),
    "sudo": ("AbEHnPSsVkKBeil", {"background", "login", "shell", "stdin", "non-interactive", "preserve-env",
                                  "reset-timestamp", "remove-timestamp", "validate", "set-home", "preserve-groups"}),
    "doas": ("nLs", set()),
    "time": ("pahlvV", set()),
    "command": ("pvV", set()),
    "timeout": ("fvp", {"foreground", "preserve-status", "verbose"}),
    "exec": ("cl", set()),
    "caffeinate": ("dimsu", set()),
    "xcrun": ("vnrfk", {"verbose", "no-cache", "run", "find", "kill-cache"}),
    "arch": ("", {"x86_64", "arm64", "i386", "arm64e"}),
}


def _has_expansion(s: str) -> bool:
    """A $ or backtick that the guard cannot evaluate ($HOME and ${HOME} it can)."""
    return bool(re.search(r"[$`]", s.replace("${HOME}", "").replace("$HOME", "")))


def _normalize_ex(words: list[str]) -> tuple[int, list[str], str | None]:
    """(index of the command word, the VAR=x words before it, a directory the wrapper changes to).

    Skips `VAR=x` and wrappers (env, sudo, time, nice, command ...) together with the wrapper's own options and
    those options' values: `env -u NAME gh ...` runs gh. An option the tables do not know makes the answer
    uncertain; then the first later `gh`, `git` or `security` word is taken as the command, because scanning
    one command too many is safe and skipping one is not."""
    n, i, assigns, chdir, uncertain = len(words), 0, [], None, False
    while i < n:
        w = words[i]
        if ASSIGN.match(w):
            assigns.append(w)
            i += 1
            continue
        name = os.path.basename(w)
        if name not in WRAPPERS:
            break
        i += 1
        vshort, vlong = WRAP_VALUE.get(name, ("", frozenset()))
        bshort, blong = WRAP_FLAGS.get(name, ("", frozenset()))
        need_duration = name == "timeout"
        while i < n:
            a = words[i]
            if a == "--":
                i += 1
                break
            if ASSIGN.match(a):
                assigns.append(a)
                i += 1
                continue
            if a == "-" and name == "env":
                i += 1
                continue
            if a.startswith("--") and len(a) > 2:
                nm, eq, v = a[2:].partition("=")
                i += 1
                if nm in vlong and not eq:
                    v = words[i] if i < n else ""
                    i += 1
                elif nm not in vlong and nm not in blong and nm not in ("help", "version"):
                    uncertain = True
                if nm == "chdir":
                    chdir = v
                continue
            if a.startswith("-") and len(a) > 1:
                i += 1
                if a[1:] in vlong:                      # `xcrun -sdk NAME`
                    i += 1 if i < n else 0
                    continue
                if a[1:] in blong:
                    continue
                for k, ch in enumerate(a[1:], 1):
                    if ch in vshort:
                        v = a[k + 1:]
                        if not v:
                            v = words[i] if i < n else ""
                            i += 1
                        if (name == "env" and ch == "C") or (name == "sudo" and ch == "D"):
                            chdir = v
                        break
                    if ch not in bshort and not ch.isdigit():
                        uncertain = True
                continue
            if need_duration and DURATION.fullmatch(a):
                need_duration = False
                i += 1
                continue
            break
    if uncertain and (i >= n or os.path.basename(words[i]) not in KEY_EXEC):
        for j in range(i, n):
            if os.path.basename(words[j]) in KEY_EXEC:
                i = j
                break
    return i, assigns, chdir


def _normalize(words: list[str]) -> int:
    return _normalize_ex(words)[0]


def _chdir(base: str | None, target: str | None, env: Env) -> str | None:
    """The directory after a change into `target`; None when it cannot be known."""
    if base is None or target is None or target == "-" or _has_expansion(target):
        return None
    if target.startswith("~") and target != "~" and not target.startswith("~/"):
        return None
    return env.resolve(target, base)


def _flags(args: list[str], base_idx: int, short_text: str, short_file: str, long_text, long_file,
           value_short: str = "", value_long=(), cluster_ok: str = "", bool_long=frozenset(),
           unknown_value: bool = False) -> tuple[list[tuple[str, str, int]], list[tuple[str, int]]]:
    """Message and file values among a command's arguments.

    Returns ([(kind, value, word index)], [(positional, word index)]). `kind` is "text" or "file". A short flag
    may be glued to its value (`-mmsg`) and, where `cluster_ok` lists the boolean letters, follow others
    (`git commit -am msg`). A long flag may be `--body=x` or `--body x`; names in `bool_long` take no value.
    `value_short` and `value_long` name flags whose value is neither text nor a file but must not be mistaken
    for a positional. With `unknown_value`, a flag the tables do not know takes the next word that is not a flag
    as its value, and that word is scanned as text (and kept as a positional): scanning too much is safe."""
    out: list[tuple[str, str, int]] = []
    pos: list[tuple[str, int]] = []
    n, i = len(args), 0
    while i < n:
        a = args[i]
        if a == "--":
            pos += [(x, base_idx + k) for k, x in enumerate(args[i + 1:], i + 1)]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name in bool_long and not eq:
                i += 1
                continue
            kind = "text" if name in long_text else "file" if name in long_file else "skip" if name in value_long else None
            if kind:
                vi = base_idx + i
                if not eq:
                    if i + 1 >= n:
                        break
                    i += 1
                    val, vi = args[i], base_idx + i
                if kind != "skip":
                    out.append((kind, val, vi))
            elif unknown_value and name not in bool_long:
                if eq:
                    out.append(("text", val, base_idx + i))
                elif i + 1 < n and not args[i + 1].startswith("-"):
                    i += 1
                    out.append(("text", args[i], base_idx + i))
                    pos.append((args[i], base_idx + i))
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            took = unknown = False
            for k, ch in enumerate(a[1:], 1):
                if ch in short_text or ch in short_file or ch in value_short:
                    kind = "text" if ch in short_text else "file" if ch in short_file else "skip"
                    val, vi = a[k + 1:].removeprefix("="), base_idx + i
                    if not a[k + 1:]:
                        if i + 1 >= n:
                            break
                        i += 1
                        val, vi = args[i], base_idx + i
                    if kind != "skip":
                        out.append((kind, val, vi))
                    took = True
                    break
                if ch not in cluster_ok:
                    unknown = True
                    break
            if unknown and unknown_value and not took and i + 1 < n and not args[i + 1].startswith("-"):
                i += 1
                out.append(("text", args[i], base_idx + i))
                pos.append((args[i], base_idx + i))
            i += 1
            continue
        pos.append((a, base_idx + i))
        i += 1
    return out, pos


def _add_values(pub: Pub, found, cmd: Cmd) -> None:
    for kind, val, vi in found:
        if kind == "text":
            cmd.text_idx.add(vi)
            if re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?|\$[@*]", val):
                pub.refusals.append(f"the text of {pub.name} is a variable the guard cannot read")
            if re.search(r"\$\(|`", val):
                pub.sub_text = True
            pub.texts.append(val)
        elif val == "-":
            pub.stdin = True
        else:
            if _has_expansion(val):
                pub.refusals.append(f"{pub.name} reads a file whose name holds an expansion the guard cannot resolve")
            pub.files.append(val)


def _public_json(text: str) -> bool:
    """True when a JSON document sets `private` to false or `visibility` to public (a GitHub API call that
    makes a repository public)."""
    try:
        data = json.loads(text)
    except ValueError:
        return False

    def walk(o) -> bool:
        if isinstance(o, dict):
            for k, v in o.items():
                lk = str(k).lower()
                if lk == "private" and str(v).lower() == "false":
                    return True
                if lk == "visibility" and str(v).lower() == "public":
                    return True
                if walk(v):
                    return True
        elif isinstance(o, list):
            return any(walk(x) for x in o)
        return False

    return walk(data)


VISIBILITY_LINES = ["teyla leak-guard: refused — making an existing repo public is the owner's decision. Ask the owner.",
                    "  (`gh repo create --public` for a new repo stays allowed.)"]

# Per (group, verb): (letters that carry text, letters that carry a file, boolean letters). A letter in none of
# them is unknown, and the word after it is scanned. `-d` is a draft switch for a PR or release and a description
# for a repo or gist; `-c` is a comment for `pr close` and a switch for `pr review`.
GH_SHORT = {
    ("pr", "create"): ("tbm", "F", "dfwe"), ("pr", "edit"): ("tbm", "F", ""), ("pr", "comment"): ("b", "F", "ew"),
    ("pr", "review"): ("b", "F", "arc"), ("pr", "merge"): ("tb", "F", "dmrs"), ("pr", "close"): ("c", "", "d"),
    ("issue", "create"): ("tbm", "F", "we"), ("issue", "comment"): ("b", "F", "ew"), ("issue", "edit"): ("tbm", "F", ""),
    ("issue", "close"): ("c", "", ""), ("release", "create"): ("tn", "F", "dp"), ("release", "edit"): ("tn", "F", "dp"),
    ("gist", "create"): ("d", "", "pw"), ("gist", "edit"): ("d", "a", ""),
    ("repo", "create"): ("d", "", "c"), ("repo", "edit"): ("d", "", ""),
}
GH_BOOL_LONG = frozenset({
    "approve", "request-changes", "web", "draft", "fill", "fill-first", "fill-verbose", "no-maintainer-edit",
    "admin", "auto", "delete-branch", "squash", "merge", "rebase", "public", "private", "internal", "clone",
    "disable-issues", "disable-wiki", "prerelease", "latest", "generate-notes", "verify-tag", "editor",
    "include-all-branches", "add-readme", "push", "dry-run", "yes", "help", "edit-last", "create-if-none",
    "recreate-on-failure", "disable-auto", "delete-last", "enable-issues", "enable-wiki", "enable-projects",
    "enable-discussions", "enable-merge-commit", "enable-squash-merge", "enable-rebase-merge", "enable-auto-merge",
    "delete-branch-on-merge", "allow-forking", "template", "add-readme", "accept-visibility-change-consequences",
})


def _gh(args: list[str], off: int, cmd: Cmd, an: Analysis) -> None:
    group = verb = None
    j = 0
    while j < len(args):
        t = args[j]
        if t in ("-R", "--repo"):                 # names a repository; it does not change the directory
            j += 2
            continue
        if t.startswith("-"):
            j += 1
            continue
        if group is None:
            group = t
        else:
            verb = t
            break
        j += 1
        if group == "api":
            break
    base = off + 1
    if group == "api":
        _gh_api(args[j:], base + j, cmd, an)
        return
    if verb is None:
        return
    rest, rbase = args[j + 1:], base + j + 1
    if (group, verb) == ("repo", "edit"):
        for k, t in enumerate(rest):
            val = t.partition("=")[2] if t.startswith("--visibility=") else rest[k + 1] if t == "--visibility" and k + 1 < len(rest) else ""
            if val.lower() == "public":
                an.hard += VISIBILITY_LINES
    if (group, verb) not in GH_TEXT_VERBS:
        return
    name = f"gh {group} {verb}"
    pub = Pub(name, cmd)
    st, sf, sb = GH_SHORT[(group, verb)]
    review = (group, verb) == ("pr", "review")
    long_text = GH_TEXT_LONG - {"comment"} if review else GH_TEXT_LONG
    bool_long = GH_BOOL_LONG | {"comment"} if review else GH_BOOL_LONG
    gist = group == "gist"
    found, pos = _flags(rest, rbase, st, sf, long_text, GH_FILE_LONG, value_short="R" + ("f" if gist else ""),
                        value_long=("repo", "filename") if gist else ("repo",), cluster_ok=sb,
                        bool_long=bool_long, unknown_value=True)
    _add_values(pub, found, cmd)
    if (group, verb) == ("gist", "create"):         # every positional is a file that becomes public; none is stdin
        if not pos:
            pub.stdin = True
        _add_values(pub, [("file", p, i) for p, i in pos], cmd)
    an.pubs.append(pub)


def _gh_api(args: list[str], base: int, cmd: Cmd, an: Analysis) -> None:
    pub = Pub("gh api", cmd)
    inputs: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        field = None
        if a in ("-f", "-F", "--field", "--raw-field"):
            if i + 1 < len(args):
                field = args[i + 1]
            i += 1
        elif a.startswith(("--field=", "--raw-field=")):
            field = a.partition("=")[2]
        elif a.startswith(("-f", "-F")) and len(a) > 2:         # -fbody=text, -Fprivate=false
            field = a[2:].lstrip("=")
        elif a == "--input":
            if i + 1 < len(args):
                inputs.append(args[i + 1])
            i += 1
        elif a.startswith("--input="):
            inputs.append(a.partition("=")[2])
        if field and "=" in field:
            key, _, val = field.partition("=")
            lk = key.lower()
            if (lk == "visibility" and val.lower() == "public") or (lk == "private" and val.lower() == "false"):
                an.hard += VISIBILITY_LINES
            if lk in API_TEXT_KEYS:
                if val == "@-":
                    pub.stdin = True
                elif val.startswith("@"):
                    _add_values(pub, [("file", val[1:], base + i)], cmd)
                else:
                    _add_values(pub, [("text", val, base + i)], cmd)
        i += 1
    for f in inputs:
        _add_values(pub, [("file", f, base)], cmd)
        if f == "-":
            for body in cmd.heredocs:
                if _public_json(body):
                    an.hard += VISIBILITY_LINES
        else:
            try:
                with open(an.env.resolve(f, cmd.cwd), encoding="utf-8", errors="replace") as fh:
                    if _public_json(fh.read(MAX_FILE)):
                        an.hard += VISIBILITY_LINES
            except (OSError, TypeError):
                pass                                     # a missing file is refused when the text is gathered
    if pub.texts or pub.files or pub.stdin:
        an.pubs.append(pub)


def _git(args: list[str], off: int, cmd: Cmd, an: Analysis) -> None:
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-C":
            cmd.cwd = _chdir(cmd.cwd, args[i + 1] if i + 1 < len(args) else None, an.env)
            i += 2
            continue
        if a in ("-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args) or args[i] not in GIT_TEXT_VERBS:
        return
    verb = args[i]
    pub = Pub(f"git {verb}", cmd)
    found, _ = _flags(args[i + 1:], off + 1 + i + 1, "m", "Ft", {"message", "trailer"}, {"file", "template"},
                      value_short="Cc", value_long=("author", "date", "cleanup", "reuse-message", "reedit-message",
                                                    "fixup", "squash"),
                      cluster_ok="asSvneqiopzNu")
    _add_values(pub, found, cmd)
    an.pubs.append(pub)


def _security(args: list[str], cmd: Cmd, an: Analysis) -> None:
    sub = next((a for a in args if not a.startswith("-")), "")
    rest = args[args.index(sub) + 1:] if sub in args else []
    if sub in ("find-generic-password", "find-internet-password"):
        flag = next((a for a in rest if re.fullmatch(r"-[A-Za-z]*[wg][A-Za-z]*", a)), None)
        if flag:
            an.hard += [f"teyla leak-guard: refused — `security {sub} {flag}` prints a secret from the Keychain.",
                        "  The agent never reads one. Use the tool that consumes it (it reads the Keychain itself), or run it yourself."]
    elif sub == "dump-keychain":
        an.hard += ["teyla leak-guard: refused — `security dump-keychain` dumps the Keychain.",
                    "  The agent never reads it. Use the tool that consumes the item, or run it yourself."]


def analyze_command(command: str, env: Env, an: Analysis, depth: int = 0, cwd: str | None = "", skip: bool = False) -> None:
    """Find what `command` publishes, reads and changes. `cwd` is the directory it starts in ("" = the session's,
    None = not known); each command carries the directory it runs in once `cd`, `git -C` and `env -C` are applied.
    `skip` is true inside a command that started with TEYLA_LEAK_GUARD=0."""
    cwd = env.cwd if cwd == "" else cwd
    cmds = lex(command)
    cds: list[tuple[tuple, str | None]] = []             # (scope, directory) after each `cd`
    for cmd in cmds:
        cur = cwd
        for g, v in cds:
            if cmd.grp[:len(g)] == g:
                cur = v
        off, assigns, chdir = _normalize_ex(cmd.words)
        if chdir is not None:
            cur = _chdir(cur, chdir, env)
        cmd.cwd = cur
        cmd.skip = skip or SKIP_ASSIGN in assigns
        if off >= len(cmd.words):
            continue
        base = os.path.basename(cmd.words[off])
        args = cmd.words[off + 1:]
        if base in ("cd", "pushd", "popd"):
            if base == "popd":
                target = None
            else:
                operands = [a for a in args if a == "-" or not a.startswith("-")]
                target = operands[0] if operands else "~"
            cds.append((cmd.grp, _chdir(cur, target, env)))
        elif base in SHELLS and depth < 4:
            for j, a in enumerate(args):
                if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and j + 1 < len(args):
                    cmd.text_idx.add(off + 2 + j)
                    analyze_command(args[j + 1], env, an, depth + 1, cur, cmd.skip)
                    break
            else:                                                   # `sh <<EOF`: the heredoc is the script
                for body in cmd.heredocs:
                    analyze_command(body, env, an, depth + 1, cur, cmd.skip)
        elif base == "eval" and depth < 4:
            cmd.text_idx.update(range(off + 1, len(cmd.words)))
            analyze_command(" ".join(args), env, an, depth + 1, cur, cmd.skip)
        elif base == "gh":
            _gh(args, off, cmd, an)
        elif base == "git":
            _git(args, off, cmd, an)
        elif base == "security":
            _security(args, cmd, an)
        elif base in PRINTERS:
            cmd.text_idx.update(range(off + 1, len(cmd.words)))
    # Credential paths: every word that is not prose, in every command that does more than look at a name.
    for cmd in cmds:
        off = _normalize(cmd.words)
        base = os.path.basename(cmd.words[off]) if off < len(cmd.words) else ""
        if base in METADATA_ONLY or base in PRINTERS:
            continue
        texts = [w for i, w in enumerate(cmd.words) if i not in cmd.text_idx]
        if base in INTERPRETERS:
            texts += cmd.heredocs
        for t in texts + cmd.stdin_files:
            for label in credential_hits(t, env, cmd.cwd):
                an.hard += [x for x in credential_lines(label) if x not in an.hard]
    an.cmds += cmds


# --- gathering the text -----------------------------------------------------------------------------------

def _read(path: str, env: Env, what: str, cwd: str | None) -> str:
    hits = credential_hits(path, env, cwd)
    if hits:
        raise Refuse(credential_lines(hits[0]))
    full = env.resolve(path, cwd)
    try:
        if os.path.getsize(full) > MAX_FILE:
            raise Refuse([f"teyla leak-guard: refused — {what} is larger than {MAX_FILE // 1_000_000} MB, so the guard cannot scan it.",
                          "  Shorten it, or publish it yourself."])
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except FileNotFoundError:
        raise
    except OSError as e:
        raise Refuse([f"teyla leak-guard: refused — cannot read {what} ({e.strerror or type(e).__name__}), so the guard cannot scan it."])


def _read_opt(path: str, env: Env, what: str, cwd: str | None) -> str:
    """The file's text. A file that does not exist when the hook runs is refused, even when the same command
    line writes it: the guard cannot know what would be published."""
    try:
        return _read(path, env, what, cwd)
    except FileNotFoundError:
        raise Refuse([f"teyla leak-guard: refused — the command reads {what}, which does not exist, so the guard cannot scan it.",
                      "  Write the text to the file first, then run the command."])


def _source_text(cmd: Cmd, env: Env, out: list[str]) -> bool:
    """Add the text a pipeline source writes to its stdout. False when the guard cannot know it."""
    off = _normalize(cmd.words)
    base = os.path.basename(cmd.words[off]) if off < len(cmd.words) else ""
    args = cmd.words[off + 1:]
    out.extend(cmd.heredocs)
    for f in cmd.stdin_files:
        out.append(_read_opt(f, env, f"`{f}`", cmd.cwd))
    if base in PRINTERS:
        out.extend(a for a in args if not a.startswith("-"))
        return True
    if base in READERS:
        for a in args:
            if not a.startswith("-"):
                out.append(_read_opt(a, env, f"`{a}`", cmd.cwd))
        return True
    return False


def _unreadable_sub(cmd: Cmd) -> bool:
    """True when a $( ) or backtick in the command is anything but `cat`/`echo`/`printf` of text and files
    the guard can read: it cannot evaluate the rest."""
    for sub in cmd.subs:
        if not sub.words:
            continue
        off = _normalize(sub.words)
        base = os.path.basename(sub.words[off]) if off < len(sub.words) else ""
        if base not in READERS and base not in PRINTERS:
            return True
        if any(_has_expansion(a) for a in sub.words[off + 1:]):
            return True
    return False


def collect_text(pub: Pub, env: Env) -> list[str]:
    cmd = pub.cmd
    if pub.stdin and not (cmd.heredocs or cmd.stdin_files or cmd.prev_pipe):
        raise Refuse([f"teyla leak-guard: refused — {pub.name} reads its text from standard input, which the guard cannot read.",
                      "  Pass a file (--body-file), or feed it a heredoc."])
    texts = list(pub.texts)
    for sub in cmd.subs:                      # "$(cat notes.md)" inside a message
        soff = _normalize(sub.words)
        sbase = os.path.basename(sub.words[soff]) if soff < len(sub.words) else ""
        if sbase in READERS:
            for a in sub.words[soff + 1:]:
                if not a.startswith("-"):
                    texts.append(_read_opt(a, env, f"`{a}`", sub.cwd))
        elif sbase in PRINTERS:
            texts.extend(a for a in sub.words[soff + 1:] if not a.startswith("-"))
    for f in pub.files:
        texts.append(_read_opt(f, env, f"`{f}`", cmd.cwd))
    texts.extend(cmd.heredocs)
    for f in cmd.stdin_files:
        texts.append(_read_opt(f, env, f"`{f}`", cmd.cwd))
    src = cmd.prev_pipe
    while src is not None:
        if not _source_text(src, env, texts) and pub.stdin:
            raise Refuse([f"teyla leak-guard: refused — {pub.name} reads its text from a pipe whose source the guard cannot read.",
                          "  Put the text in a file and pass --body-file, or use a heredoc."])
        src = src.prev_pipe
    return texts


# --- the scanner ------------------------------------------------------------------------------------------

def run_scanner(text: str, env: Env) -> tuple[int, list[str]]:
    exe = shutil.which("teyla", path=env.environ.get("PATH"))
    if not exe and os.access(os.path.join(env.home, ".local", "bin", "teyla"), os.X_OK):
        exe = os.path.join(env.home, ".local", "bin", "teyla")        # a uv tool install is not on a GUI app's PATH
    argv = [exe, "leak", "--text", "-"] if exe else [sys.executable, "-I", "-m", "teyla.leak", "--text", "-"]
    cwd = env.cwd if os.path.isdir(env.cwd) else None
    try:
        timeout = int(env.environ.get("TEYLA_LEAK_GUARD_TIMEOUT") or SCAN_TIMEOUT)
    except ValueError:
        timeout = SCAN_TIMEOUT
    p = subprocess.run(argv, input=text, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=dict(env.environ))
    lines = [l[:200] for l in (p.stdout.splitlines() or p.stderr.splitlines()) if l.strip()]
    return p.returncode, lines[:MAX_SHOWN]


def skip_hint(env: Env) -> str:
    return f"  To skip the scan once: TEYLA_LEAK_GUARD=0 <command>   (logged to {env.log})"


def _log_skips(skipped: list[Pub], env: Env) -> None:
    os.makedirs(os.path.dirname(env.log), exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    kind_env = env.environ.get("TEYLA_LEAK_GUARD") == "0"
    with open(env.log, "a", encoding="utf-8") as fh:
        for _ in skipped:
            fh.write(f"{stamp}\tskip\t{'env' if kind_env else 'prefix'}\tpublication\n")


def decide_bash(command: str, env: Env) -> list[str] | None:
    """None allows the command; a list of lines refuses it."""
    an = Analysis(env)
    analyze_command(command, env, an)
    if an.hard:                               # a credential, the Keychain, visibility: no skip lifts these
        return list(dict.fromkeys(an.hard))
    if not an.pubs:
        return None
    env_skip = env.environ.get("TEYLA_LEAK_GUARD") == "0"
    skipped = [p for p in an.pubs if env_skip or p.cmd.skip]
    active = [p for p in an.pubs if p not in skipped]
    if skipped:
        try:
            _log_skips(skipped, env)
        except OSError as e:
            return [f"teyla leak-guard: refused — the skip could not be written to {env.log} ({e.strerror or type(e).__name__}); a skip is always on the record."]
    if not active:
        return None
    for pub in active:
        if pub.cmd.cwd is None:
            return [f"teyla leak-guard: refused — {pub.name} runs in a directory the guard cannot work out (a cd into a variable or a substitution), so it cannot find the files it reads.",
                    "  Use a literal directory, or an absolute path.", skip_hint(env)]
        if pub.refusals:
            return [f"teyla leak-guard: refused — {pub.refusals[0]}.",
                    "  Put the text in a file and pass --body-file, or write it as a heredoc.", skip_hint(env)]
        if pub.sub_text and pub.cmd.subs and _unreadable_sub(pub.cmd):
            return [f"teyla leak-guard: refused — the text of {pub.name} comes from a substitution the guard cannot read.",
                    "  Write the text to a file first, then pass the file.", skip_hint(env)]
    try:
        pieces: list[str] = []
        for pub in active:
            pieces += collect_text(pub, env)
    except Refuse as r:
        return r.lines
    text = "\n".join(p for p in pieces if p)
    if not text.strip():
        return None
    names = ", ".join(dict.fromkeys(p.name for p in active))
    try:
        code, lines = run_scanner(text, env)
    except subprocess.TimeoutExpired:
        return [f"teyla leak-guard: refused — the scanner did not answer in time, so {names} is not waved through.", skip_hint(env)]
    except OSError as e:
        return [f"teyla leak-guard: refused — the scanner did not start ({e.strerror or type(e).__name__}), so {names} is not waved through.",
                "  Install teyla (`teyla leak --text -` must work).", skip_hint(env)]
    if code == 0:
        return None
    if code == 1:
        return [f"teyla leak-guard: refused — the text {names} publishes has a finding:", *["  " + l for l in lines],
                "  Fix: remove the value from the text; reference where it lives instead (a path, a Keychain item name)."]
    if code == 2:
        return [f"teyla leak-guard: refused — the scanner could not read everything for {names} (exit 2); an unread surface is not a pass:",
                *["  " + l for l in lines], skip_hint(env)]
    return [f"teyla leak-guard: refused — the scanner failed (exit {code}) on {names}; a publication is not waved through without a scan.",
            *["  " + l for l in lines[:3]], "  Repair teyla (`teyla leak --text -` must work).", skip_hint(env)]


def decide_path(path: str, env: Env) -> list[str] | None:
    hits = credential_hits(path, env)
    return credential_lines(hits[0]) if hits else None


def command_of(tool_input: dict) -> str:
    cmd = tool_input.get("command")
    if isinstance(cmd, list):                 # Codex's shell tool: ["bash", "-lc", "..."]
        parts = [str(x) for x in cmd]
        if len(parts) >= 3 and os.path.basename(parts[0]) in SHELLS and parts[1].lstrip("-").endswith("c"):
            return parts[2]
        return " ".join(parts)
    return cmd if isinstance(cmd, str) else ""


def decide(payload: dict, environ) -> list[str] | None:
    ti = payload.get("tool_input") or {}
    if not isinstance(ti, dict):
        return None
    env = Env(str(payload.get("cwd") or ""), environ)
    path = ti.get("file_path") or ti.get("notebook_path")
    if isinstance(path, str) and (payload.get("tool_name") in READ_TOOLS or "command" not in ti):
        return decide_path(path, env)
    command = command_of(ti)
    return decide_bash(command, env) if command else None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("the payload is not an object")
        lines = decide(payload, os.environ)
    except Exception as e:                    # the matched path is fail-closed: a crash is a refusal
        lines = [f"teyla leak-guard: refused — the guard failed ({type(e).__name__}) on a command that publishes text or touches a credential.",
                 "  Repair teyla, or skip the publication scan once: TEYLA_LEAK_GUARD=0 <command>"]
    if lines is None:
        return 0
    print("\n".join(lines), file=sys.stderr)
    if "--grok" in argv:
        print(json.dumps({"decision": "deny", "reason": " ".join(l.strip() for l in lines)}))
    return 2


if __name__ == "__main__":
    sys.exit(main())
