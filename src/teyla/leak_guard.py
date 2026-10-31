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
GH_FILE_LONG = {"body-file", "notes-file"}
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
_PATH_PREFIX = r"([^\s'\"`=:()<>|;&,]*)"


class Refuse(Exception):
    """Carries the lines of one refusal."""

    def __init__(self, lines: list[str]):
        super().__init__(lines[0])
        self.lines = lines


# --- a small shell lexer ---------------------------------------------------------------------------------

class Cmd:
    __slots__ = ("words", "heredocs", "stdin_files", "subs", "prev_pipe", "text_idx")

    def __init__(self):
        self.words: list[str] = []
        self.heredocs: list[str] = []       # heredoc bodies and here-strings that feed this command's stdin
        self.stdin_files: list[str] = []    # `< file`
        self.subs: list["Cmd"] = []         # commands inside $( ) and backticks in this command's words
        self.prev_pipe: "Cmd | None" = None  # the command whose stdout this one reads (`a | b`)
        self.text_idx: set[int] = set()     # word positions that are prose, not paths


class Lex:
    """Splits a shell command line into simple commands: quotes, escapes, $( ), backticks and heredocs. It does
    not expand anything. A text it cannot make sense of becomes words, never an exception."""

    def __init__(self, src: str, depth: int = 0):
        self.s = src
        self.i = 0
        self.depth = depth
        self.out: list[Cmd] = []

    def new(self) -> Cmd:
        c = Cmd()
        self.out.append(c)
        return c

    def run(self) -> list[Cmd]:
        self.commands(None)
        return [c for c in self.out if c.words or c.heredocs or c.stdin_files]

    def _sub(self, cur: Cmd, closer: str) -> None:
        a = len(self.out)
        self.commands(closer)
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
                split(False)
                self.i += 1
                continue
            if c == ")":
                if parens > 0:
                    parens -= 1
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
        inner = Lex(self.s[a + 1:b], self.depth + 1)
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
        terms = environ.get("TEYLA_PRIVATE_TERMS", "")
        self.terms = os.path.normpath(self.expand(terms)) if terms else ""
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

    def resolve(self, p: str) -> str:
        p = self.expand(p)
        return os.path.normpath(p if p.startswith("/") else os.path.join(self.cwd, p))

    def inside_repo(self, path: str) -> bool:
        """Under the repo root, where the root does not hold the home directory (a session started in ~
        has no 'inside': everything in the home directory is outside)."""
        r = self.root
        if not (path == r or path.startswith(r.rstrip("/") + "/")):
            return False
        return not (self.home == r or self.home.startswith(r.rstrip("/") + "/"))


def credential_hits(text: str, env: Env) -> list[str]:
    """Labels of the credential paths named in a text (a word, a file_path, a heredoc fed to an interpreter)."""
    hits: list[str] = []

    def add(label: str):
        if label not in hits:
            hits.append(label)

    if re.search(r"\$\{?TEYLA_PRIVATE_TERMS", text) or re.search(r"private-terms\.txt", text):
        add("the private-terms list")
    if env.terms and env.terms in env.expand(text):
        add("the private-terms list")
    for label, pat in HOME_CREDS:
        for m in re.finditer(_PATH_PREFIX + "(" + pat + ")", text):
            prefix, found = m.group(1), m.group(2)
            if label == "an SSH private key" and found.endswith(".pub"):
                continue
            if prefix and not prefix.endswith("/"):
                continue
            if not env.inside_repo(env.resolve(prefix + found)):
                add(label)
    for m in re.finditer(_PATH_PREFIX + r"(\.(?:pem|p8))(?![\w])", text):
        if not env.inside_repo(env.resolve(m.group(1) + m.group(2))):
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


class Analysis:
    def __init__(self, env: Env):
        self.env = env
        self.pubs: list[Pub] = []
        self.hard: list[str] = []            # lines of a refusal that no skip can lift
        self.unscannable: list[str] = []
        self.cmds: list[Cmd] = []


def _normalize(words: list[str]) -> int:
    """The index of the command word, after VAR=x, env, sudo, time and their flags."""
    i = 0
    while i < len(words):
        w = words[i]
        if re.match(r"[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
            continue
        if os.path.basename(w) in WRAPPERS:
            i += 1
            while i < len(words) and (words[i].startswith("-") or re.fullmatch(r"[0-9.]+[smhd]?", words[i])
                                      or re.match(r"[A-Za-z_][A-Za-z0-9_]*=", words[i])):
                i += 1
            continue
        break
    return i


def _flags(args: list[str], base_idx: int, short_text: str, short_file: str, long_text, long_file,
           value_short: str = "", value_long=(), cluster_ok: str = "") -> tuple[list[tuple[str, str, int]], list[tuple[str, int]]]:
    """Message and file values among a command's arguments.

    Returns ([(kind, value, word index)], [(positional, word index)]). `kind` is "text" or "file". A short flag
    may be glued to its value (`-mmsg`) and, where `cluster_ok` lists the boolean letters, follow others
    (`git commit -am msg`). A long flag may be `--body=x` or `--body x`. `value_short` and `value_long` name
    flags whose value is neither text nor a file but must not be mistaken for a positional."""
    out: list[tuple[str, str, int]] = []
    pos: list[tuple[str, int]] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            pos += [(x, base_idx + k) for k, x in enumerate(args[i + 1:], i + 1)]
            break
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            kind = "text" if name in long_text else "file" if name in long_file else "skip" if name in value_long else None
            if kind:
                vi = base_idx + i
                if not eq:
                    if i + 1 >= len(args):
                        break
                    i += 1
                    val, vi = args[i], base_idx + i
                if kind != "skip":
                    out.append((kind, val, vi))
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:], 1):
                if ch in short_text or ch in short_file or ch in value_short:
                    kind = "text" if ch in short_text else "file" if ch in short_file else "skip"
                    val, vi = a[k + 1:], base_idx + i
                    if not val:
                        if i + 1 >= len(args):
                            break
                        i += 1
                        val, vi = args[i], base_idx + i
                    if kind != "skip":
                        out.append((kind, val, vi))
                    break
                if ch not in cluster_ok:
                    break
            i += 1
            continue
        pos.append((a, base_idx + i))
        i += 1
    return out, pos


def _add_values(pub: Pub, an: Analysis, found, cmd: Cmd) -> None:
    for kind, val, vi in found:
        if kind == "text":
            cmd.text_idx.add(vi)
            if re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?|\$[@*]|`[^`]*`", val):
                an.unscannable.append(f"the text of {pub.name} is a variable the guard cannot read")
            pub.texts.append(val)
        else:
            if val == "-":
                pub.stdin = True
            else:
                pub.files.append(val)


def _gh(args: list[str], off: int, cmd: Cmd, an: Analysis) -> None:
    group = verb = None
    j = 0
    while j < len(args):
        t = args[j]
        if t in ("-R", "--repo"):
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
                an.hard += ["teyla leak-guard: refused — making an existing repo public is the owner's decision. Ask the owner.",
                            "  (`gh repo create --public` for a new repo stays allowed.)"]
    if (group, verb) not in GH_TEXT_VERBS:
        return
    name = f"gh {group} {verb}"
    pub = Pub(name, cmd)
    short_text = "tbmnc" + ("d" if group in ("repo", "gist") else "")
    found, pos = _flags(rest, rbase, short_text, "F", GH_TEXT_LONG, GH_FILE_LONG,
                        value_short="f" if group == "gist" else "", value_long=("filename",) if group == "gist" else ())
    _add_values(pub, an, found, cmd)
    if (group, verb) == ("gist", "create"):         # every positional is a file that becomes public
        for p, _ in pos:
            if p == "-":
                pub.stdin = True
            else:
                pub.files.append(p)
    an.pubs.append(pub)


def _gh_api(args: list[str], base: int, cmd: Cmd, an: Analysis) -> None:
    pub = Pub("gh api", cmd)
    i = 0
    while i < len(args):
        a = args[i]
        field = None
        if a in ("-f", "-F", "--field", "--raw-field") and i + 1 < len(args):
            field = args[i + 1]
            i += 1
        elif a.startswith(("--field=", "--raw-field=")):
            field = a.partition("=")[2]
        elif a == "--input" and i + 1 < len(args):
            i += 1
            if args[i] == "-":
                pub.stdin = True
            else:
                pub.files.append(args[i])
        if field and "=" in field:
            key, _, val = field.partition("=")
            lk = key.lower()
            if (lk == "visibility" and val.lower() == "public") or (lk == "private" and val.lower() == "false"):
                an.hard += ["teyla leak-guard: refused — making an existing repo public is the owner's decision. Ask the owner.",
                            "  (`gh repo create --public` for a new repo stays allowed.)"]
            if lk in API_TEXT_KEYS:
                if val.startswith("@"):
                    pub.files.append(val[1:])
                else:
                    pub.texts.append(val)
                cmd.text_idx.add(base + i)
        i += 1
    if pub.texts or pub.files or pub.stdin:
        an.pubs.append(pub)


def _git(args: list[str], off: int, cmd: Cmd, an: Analysis) -> None:
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
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
    found, _ = _flags(args[i + 1:], off + 1 + i + 1, "m", "F", {"message"}, {"file"}, cluster_ok="asSvneqiopzNu")
    _add_values(pub, an, found, cmd)
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


def analyze_command(command: str, env: Env, an: Analysis, depth: int = 0) -> None:
    cmds = lex(command)
    for cmd in cmds:
        off = _normalize(cmd.words)
        if off >= len(cmd.words):
            continue
        base = os.path.basename(cmd.words[off])
        args = cmd.words[off + 1:]
        if base in SHELLS and depth < 4:
            for j, a in enumerate(args):
                if a.startswith("-") and not a.startswith("--") and "c" in a[1:] and j + 1 < len(args):
                    cmd.text_idx.add(off + 2 + j)
                    analyze_command(args[j + 1], env, an, depth + 1)
                    break
            else:                                                   # `sh <<EOF`: the heredoc is the script
                for body in cmd.heredocs:
                    analyze_command(body, env, an, depth + 1)
        elif base == "eval" and depth < 4:
            cmd.text_idx.update(range(off + 1, len(cmd.words)))
            analyze_command(" ".join(args), env, an, depth + 1)
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
            for label in credential_hits(t, env):
                an.hard += [x for x in credential_lines(label) if x not in an.hard]
    an.cmds += cmds


# --- gathering the text -----------------------------------------------------------------------------------

def _read(path: str, env: Env, what: str) -> str:
    hits = credential_hits(path, env)
    if hits:
        raise Refuse(credential_lines(hits[0]))
    full = env.resolve(path)
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


def _read_opt(path: str, env: Env, what: str, created_here: bool) -> str:
    """The file's text. A file that does not exist yet is fine when the same command line writes a heredoc
    (it is scanned on its own); otherwise the guard cannot know what would be published, so it refuses."""
    try:
        return _read(path, env, what)
    except FileNotFoundError:
        if created_here:
            return ""
        raise Refuse([f"teyla leak-guard: refused — the command reads {what}, which does not exist, so the guard cannot scan it.",
                      "  Write the text to the file first, then run the command."])


def _source_text(cmd: Cmd, env: Env, out: list[str], created_here: bool) -> bool:
    """Add the text a pipeline source writes to its stdout. False when the guard cannot know it."""
    off = _normalize(cmd.words)
    base = os.path.basename(cmd.words[off]) if off < len(cmd.words) else ""
    args = cmd.words[off + 1:]
    out.extend(cmd.heredocs)
    for f in cmd.stdin_files:
        out.append(_read_opt(f, env, f"`{f}`", created_here))
    if base in PRINTERS:
        out.extend(a for a in args if not a.startswith("-"))
        return True
    if base in READERS:
        for a in args:
            if not a.startswith("-"):
                out.append(_read_opt(a, env, f"`{a}`", created_here))
        return True
    return False


def collect_text(pub: Pub, env: Env, created_here: bool) -> list[str]:
    cmd = pub.cmd
    texts = list(pub.texts)
    for sub in cmd.subs:                      # "$(cat notes.md)" inside a message
        soff = _normalize(sub.words)
        sbase = os.path.basename(sub.words[soff]) if soff < len(sub.words) else ""
        if sbase in READERS:
            for a in sub.words[soff + 1:]:
                if not a.startswith("-"):
                    texts.append(_read_opt(a, env, f"`{a}`", created_here))
        elif sbase in PRINTERS:
            texts.extend(a for a in sub.words[soff + 1:] if not a.startswith("-"))
    for f in pub.files:
        texts.append(_read_opt(f, env, f"`{f}`", created_here))
    texts.extend(cmd.heredocs)
    for f in cmd.stdin_files:
        texts.append(_read_opt(f, env, f"`{f}`", created_here))
    src = cmd.prev_pipe
    while src is not None:
        if not _source_text(src, env, texts, created_here) and pub.stdin:
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


def decide_bash(command: str, env: Env) -> list[str] | None:
    """None allows the command; a list of lines refuses it."""
    an = Analysis(env)
    analyze_command(command, env, an)
    if an.hard:
        return list(dict.fromkeys(an.hard))
    if not an.pubs:
        return None
    if an.unscannable:
        return [f"teyla leak-guard: refused — {an.unscannable[0]}.",
                "  Put the text in a file and pass --body-file, or write it as a heredoc.", skip_hint(env)]
    created_here = any(c.heredocs for c in an.cmds)
    try:
        pieces: list[str] = []
        for pub in an.pubs:
            pieces += collect_text(pub, env, created_here)
    except Refuse as r:
        return r.lines
    text = "\n".join(p for p in pieces if p)
    if not text.strip():
        return None
    names = ", ".join(dict.fromkeys(p.name for p in an.pubs))
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
